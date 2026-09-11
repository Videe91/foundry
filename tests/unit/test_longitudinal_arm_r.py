"""Reconstruction Arm R runner (9P Task 13; spec §27, §28).

A fresh governor, ledger and project id at every T; every evidence version with step
``<= T`` as the "delta"; the same two-call shape as Arm F with empty known state; no
authority step and no human path. The only reasoner is a scripted fake that records the
requests it received; the Git reader is a fake keyed by ``(commit, path)``. ZERO live
calls.
"""

from __future__ import annotations

import hashlib
import importlib
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any

import pytest

import foundry.experiments.longitudinal.arm_r as arm_r_module
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics import xai_reasoner
from foundry.adapters.semantics.xai_reasoner import (
    SemanticDraftPayload,
    SemanticReasoningReceipt,
)
from foundry.application.assimilation_context import (
    ASSIMILATION_JUDGMENT_KINDS,
    CLAIM_ASSIMILATION_JUDGMENT_KINDS,
)
from foundry.application.incremental_assimilation import CALLS_PER_DELTA
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority
from foundry.domain.events import EventType
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.experiments.longitudinal.arm_r import (
    MAX_R_CALLS,
    ArmRStep,
    RecordedCalls,
    RequestRecorder,
    ledger_admissions,
    ledger_judgment_ids,
    recorded_calls,
    run_arm_r,
)
from foundry.experiments.longitudinal.timeline import (
    TIMELINE,
    VersionedEvidence,
    load_timeline,
    persistent_delta,
    reconstruction_corpus,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 11, tzinfo=UTC)
LOADED_PROJECT = "PROJ-9P"
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="9p-v1")

T1 = "097584a39dd76cf86510500acb548778ce00fad9"
T2 = "2539ff81f79f085c1eba42718947050c1b3ac61c"
T3 = "90246a8b986b0dcbcbae6a4f3484204f916afeb5"
T4 = "779a66ac90eceaea7eb7d4af0692ee4f167292fc"

CONSTITUTION = "FOUNDRY_CONSTITUTION.md"
SPEC = "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md"
REDUCER = "src/foundry/application/semantic_reducer.py"
IDENTITY = "src/foundry/domain/semantic_identity.py"

CORPUS_IDS_BY_T: dict[int, tuple[str, ...]] = {
    1: ("EV-T1-01", "EV-T1-02"),
    2: ("EV-T1-01", "EV-T1-02", "EV-T2-01"),
    3: ("EV-T1-01", "EV-T1-02", "EV-T2-01", "EV-T3-01", "EV-T3-02"),
    4: ("EV-T1-01", "EV-T1-02", "EV-T2-01", "EV-T3-01", "EV-T3-02", "EV-T4-01", "EV-T4-02"),
}

type Batch = (
    list[SemanticJudgment] | Callable[[ReasoningRequest], list[SemanticJudgment]] | BaseException
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- fakes ------------------------------------------------------------------------


class FakeGit:
    """Serves bytes for exact ``(commit, path)`` pairs; anything else does not exist."""

    def __init__(self, blobs: dict[tuple[str, str], bytes]) -> None:
        self._blobs = blobs

    def blob(self, sha: str, path: str) -> bytes:
        if (sha, path) not in self._blobs:
            raise RuntimeError(f"no blob for {sha}:{path}")
        return self._blobs[(sha, path)]

    def blob_sha(self, sha: str, path: str) -> str:
        return hashlib.sha1(b"blob " + self.blob(sha, path)).hexdigest()


class ScriptedReasoner:
    """Returns one scripted batch per call, records every request, refuses extra calls."""

    def __init__(self, batches: list[Batch], fingerprint: ReasonerFingerprint = MODEL) -> None:
        self._batches = batches
        self._fingerprint = fingerprint
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        batch = self._batches[index]
        if isinstance(batch, BaseException):
            raise batch
        if callable(batch):
            return tuple(batch(request))
        return tuple(batch)


class RecordingReasoner(ScriptedReasoner):
    """A scripted reasoner that also exposes receipts and raw drafts, like the adapter."""

    def __init__(self, batches: list[Batch]) -> None:
        super().__init__(batches)
        self._receipts: list[SemanticReasoningReceipt] = []
        self._drafts: list[SemanticDraftPayload] = []

    @property
    def receipts(self) -> tuple[SemanticReasoningReceipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[SemanticDraftPayload, ...]:
        return tuple(self._drafts)

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        invocation = f"INV-{len(self.requests) + 1}"
        self._receipts.append(
            SemanticReasoningReceipt(
                invocation_id=invocation,
                model="grok-4.6",
                reasoning_effort="high",
                input_tokens=len(request.evidence),
                output_tokens=1,
                cost_usd=0.0,
                wall_clock_ms=1,
                draft_count=0,
            )
        )
        self._drafts.append(SemanticDraftPayload(drafts=()))
        return super().propose(request)


class SpyStore(InMemoryEventStore):
    instances: list[SpyStore] = []

    def __init__(self) -> None:
        super().__init__()
        SpyStore.instances.append(self)


# --- builders ---------------------------------------------------------------------


def _blobs() -> dict[tuple[str, str], bytes]:
    return {
        (T1, CONSTITUTION): b"constitution v1\n",
        (T1, SPEC): b"spec v1\n",
        (T2, SPEC): b"spec v2\n",
        (T3, REDUCER): b"reducer v1\n",
        (T3, IDENTITY): b"identity v1\n",
        (T4, REDUCER): b"reducer v2\n",
        (T4, SPEC): b"spec v3\n",
    }


def _timeline() -> tuple[VersionedEvidence, ...]:
    return load_timeline(
        FakeGit(_blobs()),
        project_id=LOADED_PROJECT,
        observed_at_for=lambda t: T0 + timedelta(days=t),
    )


def _clock() -> Callable[[], datetime]:
    ticks: Iterator[int] = count()
    return lambda: T0 + timedelta(minutes=next(ticks))


def _id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _judgment(
    judgment_id: str, request: ReasoningRequest, proposal: JudgmentProposal, evidence_id: str
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=request.project_id,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Rationale for {judgment_id}.",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _create_from_last_evidence(t: int) -> Callable[[ReasoningRequest], list[SemanticJudgment]]:
    def batch(request: ReasoningRequest) -> list[SemanticJudgment]:
        assert request.known_addresses == (), "Arm R Call 1 must see no known addresses"
        item = request.evidence[-1]
        candidate = SemanticCandidate(
            candidate_id=f"CAND-T{t}",
            subject=f"subject T{t}",
            facet="retention",
            scope=item.scope,
            evidence_ids=(item.evidence_id,),
        )
        judgment_id = f"J-T{t}-create"
        return [
            _judgment(
                judgment_id, request, CreateAddressProposal(candidate=candidate), item.evidence_id
            )
        ]

    return batch


def _assert_at_created_address(t: int) -> Callable[[ReasoningRequest], list[SemanticJudgment]]:
    def batch(request: ReasoningRequest) -> list[SemanticJudgment]:
        assert request.known_claims == (), "Arm R Call 2 must see no known claims"
        item = request.evidence[-1]
        proposal = AssertClaimProposal(
            address_id=request.known_addresses[0].address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(t), unit="day"),
            evidence_ids=(item.evidence_id,),
            authority=Authority.OBSERVED,
        )
        return [_judgment(f"J-T{t}-assert", request, proposal, item.evidence_id)]

    return batch


def _script(overrides: dict[int, Batch] | None = None) -> list[Batch]:
    """Two batches per T (create, then assert); ``overrides`` replaces call index → batch."""
    batches: list[Batch] = []
    for t in (1, 2, 3, 4):
        batches.append(_create_from_last_evidence(t))
        batches.append(_assert_at_created_address(t))
    for index, batch in (overrides or {}).items():
        batches[index] = batch
    return batches


def _run(reasoner: ScriptedReasoner) -> tuple[ArmRStep, ...]:
    return run_arm_r(
        reasoner=reasoner,
        timeline=_timeline(),
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
        scope="intent-engine",
    )


def _event_types(step: ArmRStep) -> list[EventType]:
    return [stored.event.event_type for stored in step.ledger]


# --- tests --------------------------------------------------------------------------


def test_each_t_starts_from_an_empty_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    SpyStore.instances.clear()
    monkeypatch.setattr(arm_r_module, "InMemoryEventStore", SpyStore)
    reasoner = ScriptedReasoner(_script())

    steps = _run(reasoner)

    assert [step.t for step in steps] == [1, 2, 3, 4]
    assert all(step.status == "COMPLETED" for step in steps)
    # One fresh store per T, none shared.
    assert len(SpyStore.instances) == 4
    assert len({id(store) for store in SpyStore.instances}) == 4
    # Every ledger starts at sequence 1 in its own project, and its first events are the
    # corpus ingests; nothing from an earlier T is present.
    for step in steps:
        project_id = f"PROJ-9P-R-T{step.t}"
        assert [stored.sequence for stored in step.ledger] == list(range(1, len(step.ledger) + 1))
        assert {stored.event.project_id for stored in step.ledger} == {project_id}
        ingested = _event_types(step)[: len(step.evidence_shown)]
        assert ingested == [EventType.EVIDENCE_INGESTED] * len(step.evidence_shown)
        assert len(step.view.loci) == 1
    # No event id crosses T ledgers; the shared id factory keeps ids globally unique.
    event_ids = [stored.event.event_id for step in steps for stored in step.ledger]
    assert len(event_ids) == len(set(event_ids))
    # Every Call 1 saw no addresses and every Call 2 saw no claims: empty known state.
    assert len(reasoner.requests) == 8
    for index, request in enumerate(reasoner.requests):
        assert request.project_id == f"PROJ-9P-R-T{index // 2 + 1}"
        assert request.known_claims == ()
        if index % 2 == 0:
            assert request.known_addresses == ()
        else:
            assert len(request.known_addresses) == 1


def test_each_t_receives_all_versions_up_to_t() -> None:
    timeline = _timeline()
    reasoner = ScriptedReasoner(_script())

    steps = _run(reasoner)

    originals = {v.item.evidence_id: v.item for v in timeline}
    for step in steps:
        assert step.evidence_shown == CORPUS_IDS_BY_T[step.t]
        expected = tuple(item.evidence_id for item in reconstruction_corpus(timeline, step.t))
        assert step.evidence_shown == expected
        # R gets at least what F gets at the same T.
        assert len(step.evidence_shown) >= len(persistent_delta(timeline, step.t))
        call1, call2 = reasoner.requests[2 * (step.t - 1) : 2 * step.t]
        assert tuple(item.evidence_id for item in call1.evidence) == step.evidence_shown
        assert tuple(item.evidence_id for item in call2.evidence) == step.evidence_shown
        # Re-projected onto this T's project with content, hash, scope and lineage intact.
        for item in call1.evidence:
            original = originals[item.evidence_id]
            assert item.project_id == f"PROJ-9P-R-T{step.t}"
            assert item.content == original.content
            assert item.content_sha256 == original.content_sha256
            assert item.scope == original.scope
            assert item.observed_at == original.observed_at
            assert item.artifact_ref == original.artifact_ref
            assert item.supersedes_evidence_id == original.supersedes_evidence_id
    # T2 includes both spec versions, linked by lineage, and T2's own ledger knows both.
    t2 = steps[1]
    assert "EV-T1-02" in t2.evidence_shown
    assert "EV-T2-01" in t2.evidence_shown
    t2_items = {item.evidence_id: item for item in reasoner.requests[2].evidence}
    assert t2_items["EV-T2-01"].supersedes_evidence_id == "EV-T1-02"
    assert t2.view.current_evidence_ids == ("EV-T1-01", "EV-T2-01")
    assert t2.view.superseded_evidence_ids == ("EV-T1-02",)


def test_two_calls_per_t_eight_total_same_allowed_kinds_as_arm_f() -> None:
    reasoner = ScriptedReasoner(_script())

    steps = _run(reasoner)

    assert MAX_R_CALLS == 8 == CALLS_PER_DELTA * len(TIMELINE)
    assert len(reasoner.requests) == MAX_R_CALLS
    for index, request in enumerate(reasoner.requests):
        expected = (
            ASSIMILATION_JUDGMENT_KINDS if index % 2 == 0 else CLAIM_ASSIMILATION_JUDGMENT_KINDS
        )
        assert request.allowed_judgment_kinds == expected
    for step in steps:
        assert step.judgment_ids == (f"J-T{step.t}-create", f"J-T{step.t}-assert")
        assert [decision.route for decision in step.admissions] == [AdmissionRoute.APPLY] * 2
        assert [decision.judgment_id for decision in step.admissions] == list(step.judgment_ids)
        # The scripted reasoner exposes neither receipts nor drafts: nothing is invented.
        assert step.receipts == ()
        assert step.draft_outputs == ()
        assert step.error is None

    # A timeline with a fifth step would need a ninth call: it is never made.
    extra = _timeline()
    fifth = extra[-1].model_copy(
        update={"t": 5, "item": extra[-1].item.model_copy(update={"evidence_id": "EV-T5-01"})}
    )
    over = ScriptedReasoner([*_script(), _create_from_last_evidence(5)])
    steps = run_arm_r(
        reasoner=over,
        timeline=(*extra, fifth),
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
        scope="intent-engine",
    )
    assert len(over.requests) == MAX_R_CALLS
    assert [step.status for step in steps] == ["COMPLETED"] * 4 + ["NOT_RUN"]
    assert steps[4].error is not None
    assert "MAX_R_CALLS" in steps[4].error
    assert steps[4].ledger == ()


def test_no_authority_record_and_no_human_path_in_arm_r() -> None:
    source = Path(arm_r_module.__file__).read_text(encoding="utf-8")
    assert "record_authority" not in source
    assert "human_actor_id" not in source
    assert ".submit(" not in source
    assert "Authorizer" not in source
    assert "longitudinal.authority" not in source
    assert "SemanticJudgment(" not in source
    assert "retry" not in source.lower()

    reasoner = ScriptedReasoner(_script())
    steps = _run(reasoner)

    allowed = {
        EventType.EVIDENCE_INGESTED,
        EventType.SEMANTIC_JUDGMENT_RECORDED,
        EventType.SEMANTIC_ADMISSION_DECIDED,
    }
    for step in steps:
        assert set(_event_types(step)) <= allowed
        assert step.view.pending_judgment_ids == ()
        assert dict(step.view.satisfied_by) == {}
        for stored in step.ledger:
            payload: Any = stored.event.payload
            if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED:
                assert not payload.judgment.reasoner.is_human


def test_same_system_instruction_hash_used_by_both_arms() -> None:
    assert arm_r_module.SYSTEM_INSTRUCTION_SHA256 is xai_reasoner.SYSTEM_INSTRUCTION_SHA256
    # The digest is imported from the single adapter, never restated in the runner.
    source = Path(arm_r_module.__file__).read_text(encoding="utf-8")
    assert xai_reasoner.SYSTEM_INSTRUCTION_SHA256[:8] not in source
    try:
        arm_f_module = importlib.import_module("foundry.experiments.longitudinal.arm_f")
    except ModuleNotFoundError:
        return
    arm_f_hash = getattr(arm_f_module, "SYSTEM_INSTRUCTION_SHA256", None)
    if arm_f_hash is not None:
        assert arm_f_hash == arm_r_module.SYSTEM_INSTRUCTION_SHA256


def test_failure_isolates_to_that_t() -> None:
    reasoner = ScriptedReasoner(_script({3: RuntimeError("provider failure")}))

    steps = _run(reasoner)

    assert [step.status for step in steps] == ["COMPLETED", "FAILED", "COMPLETED", "COMPLETED"]
    failed = steps[1]
    assert failed.error is not None
    assert "provider failure" in failed.error
    # Call 1's admission is kept in T2's own ledger; nothing was rolled back or retried.
    assert failed.judgment_ids == ("J-T2-create",)
    assert [decision.route for decision in failed.admissions] == [AdmissionRoute.APPLY]
    assert len(failed.view.loci) == 1
    assert failed.evidence_shown == CORPUS_IDS_BY_T[2]
    # T3 and T4 ran from their own empty ledgers, unaffected by T2's failure.
    assert len(reasoner.requests) == MAX_R_CALLS
    assert steps[2].judgment_ids == ("J-T3-create", "J-T3-assert")
    assert steps[3].judgment_ids == ("J-T4-create", "J-T4-assert")
    assert [step.error for step in steps if step.t != 2] == [None, None, None]


def test_receipts_and_drafts_are_captured_per_t_when_the_reasoner_exposes_them() -> None:
    reasoner = RecordingReasoner(_script({5: RuntimeError("provider failure")}))

    steps = _run(reasoner)

    assert [step.status for step in steps] == ["COMPLETED", "COMPLETED", "FAILED", "COMPLETED"]
    for step in steps:
        assert [receipt.invocation_id for receipt in step.receipts] == [
            f"INV-{2 * step.t - 1}",
            f"INV-{2 * step.t}",
        ]
        assert len(step.draft_outputs) == 2
        assert all(receipt.input_tokens == len(step.evidence_shown) for receipt in step.receipts)
    assert sum(len(step.receipts) for step in steps) == len(reasoner.receipts) == MAX_R_CALLS


def test_allowed_kinds_per_call_are_recorded_from_real_requests_and_never_equivalence() -> None:
    reasoner = ScriptedReasoner(_script({5: RuntimeError("provider failure")}))

    steps = _run(reasoner)

    call_1 = tuple(sorted(kind.value for kind in ASSIMILATION_JUDGMENT_KINDS))
    call_2 = tuple(sorted(kind.value for kind in CLAIM_ASSIMILATION_JUDGMENT_KINDS))
    assert [step.status for step in steps] == ["COMPLETED", "COMPLETED", "FAILED", "COMPLETED"]
    for step in steps:
        assert step.allowed_kinds_per_call == (call_1, call_2)
        for kinds in step.allowed_kinds_per_call:
            assert JudgmentKind.EQUIVALENT.value not in kinds
            assert JudgmentKind.DISTINCT.value not in kinds
    # The log is what the reasoner actually received, call for call.
    recorded = [
        tuple(sorted(kind.value for kind in request.allowed_judgment_kinds))
        for request in reasoner.requests
    ]
    assert recorded == [kinds for step in steps for kinds in step.allowed_kinds_per_call]

    # A failure before Call 2 leaves exactly one entry; a T that never ran has none.
    reasoner = ScriptedReasoner(_script({2: RuntimeError("provider failure at call 1")}))
    steps = _run(reasoner)
    assert steps[1].status == "FAILED"
    assert steps[1].allowed_kinds_per_call == (call_1,)

    extra = _timeline()
    fifth = extra[-1].model_copy(
        update={"t": 5, "item": extra[-1].item.model_copy(update={"evidence_id": "EV-T5-01"})}
    )
    over = ScriptedReasoner([*_script(), _create_from_last_evidence(5)])
    steps = run_arm_r(
        reasoner=over,
        timeline=(*extra, fifth),
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
        scope="intent-engine",
    )
    assert steps[4].status == "NOT_RUN"
    assert steps[4].allowed_kinds_per_call == ()


def test_request_recorder_forwards_verbatim_and_refuses_calls_past_its_ceiling() -> None:
    inner = ScriptedReasoner([[], [], []])
    recorder = RequestRecorder(inner, max_calls=2)
    assert recorder.fingerprint == inner.fingerprint
    assert recorder.inner is inner

    timeline = _timeline()
    request = ReasoningRequest(
        project_id="PROJ-9P-R-T1",
        evidence=tuple(
            item.model_copy(update={"project_id": "PROJ-9P-R-T1"})
            for item in reconstruction_corpus(timeline, 1)
        ),
        allowed_judgment_kinds=ASSIMILATION_JUDGMENT_KINDS,
    )
    recorder.propose(request)
    assert inner.requests == [request]
    assert recorder.requests == [request]
    assert recorder.allowed_kinds_since(0) == (
        tuple(sorted(kind.value for kind in ASSIMILATION_JUDGMENT_KINDS)),
    )
    recorder.propose(request)
    assert recorder.since(1) == (request,)
    with pytest.raises(RuntimeError, match="max_calls"):
        recorder.propose(request)
    # The refused call never reached the reasoner.
    assert len(inner.requests) == 2


def test_ledger_and_call_record_helpers_are_public_and_read_only() -> None:
    reasoner = RecordingReasoner(_script())
    steps = _run(reasoner)

    for step in steps:
        assert ledger_judgment_ids(step.ledger) == step.judgment_ids
        assert ledger_admissions(step.ledger) == step.admissions
    # A reasoner that exposes receipts/drafts yields them; one that does not yields none.
    exposed = recorded_calls(reasoner)
    assert isinstance(exposed, RecordedCalls)
    assert exposed.receipts == reasoner.receipts
    assert exposed.drafts == reasoner.draft_payloads
    assert exposed.since(RecordedCalls()).receipts == reasoner.receipts
    assert exposed.since(exposed).receipts == ()
    assert recorded_calls(ScriptedReasoner([])) == RecordedCalls()

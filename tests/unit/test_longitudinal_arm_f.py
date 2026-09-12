"""Persistent Arm F runner (9P Task 12; spec §26, §28, §31, §32).

One governor, one ledger, one project id for the whole run. T0 records the architect's
authority; T1 assimilates and then attaches the preregistered chains; T2..T4 receive
delta evidence only, assimilate, and offer any pending ``SUPERSEDE`` to the human.
The only reasoner is a scripted fake that records the requests it received; the only
human is a scripted authorizer; the Git reader is a fake keyed by ``(commit, path)``.
ZERO live calls.
"""

from __future__ import annotations

import hashlib
import json
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any

import pytest

import foundry.experiments.longitudinal.arm_f as arm_f_module
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics import xai_reasoner
from foundry.adapters.semantics.xai_reasoner import (
    SemanticDraftPayload,
    SemanticReasoningReceipt,
    render_request,
)
from foundry.application.assimilation_context import (
    ASSIMILATION_JUDGMENT_KINDS,
    CLAIM_ASSIMILATION_JUDGMENT_KINDS,
)
from foundry.application.incremental_assimilation import CALLS_PER_DELTA
from foundry.application.replay import replay
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority
from foundry.domain.events import DerivationPayload, EventType
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.experiments.longitudinal.arm_f import (
    MAX_F_CALLS,
    PROJECT_ID,
    ArmFResult,
    StepRecord,
    run_arm_f,
)
from foundry.experiments.longitudinal.authority import (
    ARCHITECT_ACTOR,
    AuthorizationDecision,
    NotOfferedReason,
)
from foundry.experiments.longitudinal.derivations import (
    CONTROL_CHAIN,
    TRACK_A_CHAIN,
    RootDesignation,
    RootSelection,
)
from foundry.experiments.longitudinal.expectations import TRACKED_LOCI
from foundry.experiments.longitudinal.timeline import (
    VersionedEvidence,
    load_timeline,
    persistent_delta,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 11, tzinfo=UTC)
LOADED_PROJECT = "PROJ-9P"
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="9p-v1")
SCOPE = "intent-engine"

T1 = "097584a39dd76cf86510500acb548778ce00fad9"
T2 = "2539ff81f79f085c1eba42718947050c1b3ac61c"
T3 = "90246a8b986b0dcbcbae6a4f3484204f916afeb5"
T4 = "779a66ac90eceaea7eb7d4af0692ee4f167292fc"

CONSTITUTION = "FOUNDRY_CONSTITUTION.md"
SPEC = "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md"
REDUCER = "src/foundry/application/semantic_reducer.py"
IDENTITY = "src/foundry/domain/semantic_identity.py"

DELTA_IDS_BY_T: dict[int, tuple[str, ...]] = {
    1: ("EV-T1-01", "EV-T1-02"),
    2: ("EV-T2-01",),
    3: ("EV-T3-01", "EV-T3-02"),
    4: ("EV-T4-01", "EV-T4-02"),
}

# Judgment ids the script uses; address/claim ids are the reducer's deterministic mints.
J_CREATE_A = "J-T1-create-A"
J_CREATE_B = "J-T1-create-B"
J_CREATE_U = "J-T1-create-U"
J_CREATE_N = "J-T1-create-N"
J_CLAIM_A = "J-T1-claim-A"
J_CLAIM_B = "J-T1-claim-B"
J_CLAIM_U = "J-T1-claim-U"
J_CLAIM_N = "J-T1-claim-N"
J_BIND_A = "J-T2-bind-A"
J_BIND_B = "J-T2-bind-B"
J_BIND_U = "J-T2-bind-U"
J_CLAIM_A_NEW = "J-T2-claim-A-new"
J_SUPERSEDE_A = "J-T2-supersede-A"
J_SUPERSEDE_B = "J-T2-supersede-B"
J_SUPERSEDE_U = "J-T2-supersede-U"
J_CREATE_C = "J-T3-create-C"
J_CLAIM_C = "J-T3-claim-C"
J_BIND_C_AT_T3 = "J-T3-bind-C"
J_BIND_C = "J-T4-bind-C"
J_CLAIM_C_NEW = "J-T4-claim-C-new"
J_SUPERSEDE_C = "J-T4-supersede-C"

ADDR_A = address_id_for(PROJECT_ID, J_CREATE_A)
ADDR_B = address_id_for(PROJECT_ID, J_CREATE_B)
ADDR_U = address_id_for(PROJECT_ID, J_CREATE_U)
ADDR_N = address_id_for(PROJECT_ID, J_CREATE_N)
ADDR_C = address_id_for(PROJECT_ID, J_CREATE_C)
CLAIM_A = claim_id_for(PROJECT_ID, J_CLAIM_A)
CLAIM_B = claim_id_for(PROJECT_ID, J_CLAIM_B)
T1_JUDGMENTS = (
    J_CREATE_A,
    J_CREATE_B,
    J_CREATE_U,
    J_CREATE_N,
    J_CLAIM_A,
    J_CLAIM_B,
    J_CLAIM_U,
    J_CLAIM_N,
)

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


class ScriptedAuthorizer:
    """Answers scripted decisions in order and records every judgment presented to it."""

    def __init__(self, answers: list[Any]) -> None:
        self._answers = answers
        self.presented: list[SemanticJudgment] = []

    def __call__(self, pending: SemanticJudgment) -> AuthorizationDecision:
        self.presented.append(pending)
        index = len(self.presented) - 1
        if index >= len(self._answers):
            raise AssertionError(f"AUTHORIZATION {index + 1} ATTEMPTED: only {index} scripted")
        answer: AuthorizationDecision = self._answers[index]
        return answer


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


def _candidate(candidate_id: str, request: ReasoningRequest, evidence_id: str) -> SemanticCandidate:
    item = next(item for item in request.evidence if item.evidence_id == evidence_id)
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject=f"subject {candidate_id}",
        facet="retention",
        scope=item.scope,
        evidence_ids=(evidence_id,),
    )


def _create(judgment_id: str, request: ReasoningRequest, evidence_id: str) -> SemanticJudgment:
    candidate = _candidate(f"CAND-{judgment_id}", request, evidence_id)
    return _judgment(judgment_id, request, CreateAddressProposal(candidate=candidate), evidence_id)


def _bind(
    judgment_id: str, request: ReasoningRequest, address_id: str, evidence_id: str
) -> SemanticJudgment:
    candidate = _candidate(f"CAND-{judgment_id}", request, evidence_id)
    proposal = BindToAddressProposal(candidate=candidate, address_id=address_id)
    return _judgment(judgment_id, request, proposal, evidence_id)


def _claim(
    judgment_id: str,
    request: ReasoningRequest,
    address_id: str,
    evidence_id: str,
    quantity: int,
    *,
    authority: Authority = Authority.OBSERVED,
) -> SemanticJudgment:
    proposal = AssertClaimProposal(
        address_id=address_id,
        predicate="retention_period",
        value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="day"),
        evidence_ids=(evidence_id,),
        authority=authority,
    )
    return _judgment(judgment_id, request, proposal, evidence_id)


def _supersede(
    judgment_id: str, request: ReasoningRequest, target: str, evidence_id: str
) -> SemanticJudgment:
    known_targets = {claim.created_by_judgment_id for claim in request.known_claims}
    assert target in known_targets, f"SUPERSEDE target {target} is not a known claim's judgment"
    proposal = SupersedeProposal(target_judgment_id=target, reason="The older claim is corrected.")
    return _judgment(judgment_id, request, proposal, evidence_id)


def _t1_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
    assert request.known_addresses == (), "T1 Call 1 must see no known addresses"
    return [
        _create(J_CREATE_A, request, "EV-T1-02"),
        _create(J_CREATE_B, request, "EV-T1-02"),
        _create(J_CREATE_U, request, "EV-T1-02"),
        _create(J_CREATE_N, request, "EV-T1-01"),
    ]


def _t1_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
    assert request.known_claims == (), "T1 Call 2 must see no known claims"
    return [
        _claim(J_CLAIM_A, request, ADDR_A, "EV-T1-02", 7),
        _claim(J_CLAIM_B, request, ADDR_B, "EV-T1-02", 8),
        _claim(J_CLAIM_U, request, ADDR_U, "EV-T1-02", 9),
        _claim(J_CLAIM_N, request, ADDR_N, "EV-T1-01", 1),
    ]


def _t2_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [_bind(J_BIND_A, request, ADDR_A, "EV-T2-01")]


def _t2_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [
        _claim(J_CLAIM_A_NEW, request, ADDR_A, "EV-T2-01", 14),
        _supersede(J_SUPERSEDE_A, request, J_CLAIM_A, "EV-T2-01"),
    ]


def _t2_binds(*binds: tuple[str, str]) -> Callable[[ReasoningRequest], list[SemanticJudgment]]:
    return lambda request: [_bind(j, request, address, "EV-T2-01") for j, address in binds]


def _t2_supersessions(
    *targets: tuple[str, str],
) -> Callable[[ReasoningRequest], list[SemanticJudgment]]:
    return lambda request: [_supersede(j, request, target, "EV-T2-01") for j, target in targets]


def _t3_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [_create(J_CREATE_C, request, "EV-T3-02")]


def _t3_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [_claim(J_CLAIM_C, request, ADDR_C, "EV-T3-02", 3)]


def _t4_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [_bind(J_BIND_C, request, ADDR_C, "EV-T4-01")]


def _t4_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [_claim(J_CLAIM_C_NEW, request, ADDR_C, "EV-T4-01", 4)]


def _t4_call_2_with_supersession(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [
        _claim(J_CLAIM_C_NEW, request, ADDR_C, "EV-T4-01", 4),
        _supersede(J_SUPERSEDE_C, request, J_CLAIM_C, "EV-T4-01"),
    ]


def _script(overrides: dict[int, Batch] | None = None) -> list[Batch]:
    """Eight batches (two per T); ``overrides`` replaces call index → batch."""
    batches: list[Batch] = [
        _t1_call_1,
        _t1_call_2,
        _t2_call_1,
        _t2_call_2,
        _t3_call_1,
        _t3_call_2,
        _t4_call_1,
        _t4_call_2,
    ]
    for index, batch in (overrides or {}).items():
        batches[index] = batch
    return batches


type Selector = Callable[[IntentState], RootSelection]


def _select(address_id: str, judgment_id: str) -> Selector:
    return lambda _state: RootSelection(address_id=address_id, judgment_id=judgment_id)


def _last_ingested(state: IntentState) -> str:
    """The most recently ingested evidence id (evidence mappings keep ledger order)."""
    return next(reversed(state.semantic.evidence))


SELECT_A = _select(ADDR_A, J_CLAIM_A)
SELECT_B = _select(ADDR_B, J_CLAIM_B)
SELECT_C = _select(ADDR_C, J_CLAIM_C)
SELECT_N = _select(ADDR_N, J_CLAIM_N)


def _run(
    reasoner: ScriptedReasoner,
    authorizer: ScriptedAuthorizer | None = None,
    *,
    timeline: tuple[VersionedEvidence, ...] | None = None,
    designate_track_a: Selector = SELECT_A,
    designate_track_b: Selector = SELECT_B,
    designate_track_c: Selector = SELECT_C,
    designate_control: Selector = SELECT_N,
    on_t1_designations: Callable[[tuple[RootDesignation, ...]], None] | None = None,
) -> ArmFResult:
    return run_arm_f(
        reasoner=reasoner,
        timeline=timeline if timeline is not None else _timeline(),
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
        authorizer=authorizer or ScriptedAuthorizer([AuthorizationDecision.AGREE]),
        designate_track_a=designate_track_a,
        designate_track_b=designate_track_b,
        designate_track_c=designate_track_c,
        designate_control=designate_control,
        scope=SCOPE,
        on_t1_designations=on_t1_designations,
    )


def _sequence_of(result: ArmFResult, event_type: EventType, predicate: Any) -> list[int]:
    return [
        stored.sequence
        for stored in result.ledger
        if stored.event.event_type is event_type and predicate(stored.event.payload)
    ]


def _event_types(result: ArmFResult) -> list[EventType]:
    return [stored.event.event_type for stored in result.ledger]


def _step(result: ArmFResult, t: int) -> StepRecord:
    return result.steps[t - 1]


# --- tests --------------------------------------------------------------------------


def test_arm_f_makes_two_calls_per_t_and_eight_total() -> None:
    reasoner = ScriptedReasoner(_script())

    result = _run(reasoner)

    assert MAX_F_CALLS == 8 == CALLS_PER_DELTA * 4
    assert [step.t for step in result.steps] == [1, 2, 3, 4]
    assert [step.status for step in result.steps] == ["COMPLETED"] * 4
    assert [step.error for step in result.steps] == [None] * 4
    assert result.calls_made == len(reasoner.requests) == MAX_F_CALLS
    for index, request in enumerate(reasoner.requests):
        assert request.project_id == PROJECT_ID
        expected = (
            ASSIMILATION_JUDGMENT_KINDS if index % 2 == 0 else CLAIM_ASSIMILATION_JUDGMENT_KINDS
        )
        assert request.allowed_judgment_kinds == expected
    # One ledger, one project, monotone sequence; the architect authority is its T0 event.
    assert {stored.event.project_id for stored in result.ledger} == {PROJECT_ID}
    assert [stored.sequence for stored in result.ledger] == list(range(1, len(result.ledger) + 1))
    assert _event_types(result)[0] is EventType.SEMANTIC_OBJECT_RECORDED
    first_payload: Any = result.ledger[0].event.payload
    assert first_payload.object.authorized_by == ARCHITECT_ACTOR
    assert result.final_state_revision == len(result.ledger)
    # Per-step ledger accounting is cumulative and monotone.
    revisions = [step.state_snapshot_revision for step in result.steps]
    assert revisions == sorted(revisions)
    assert revisions[-1] == result.final_state_revision
    assert _step(result, 1).judgment_ids == T1_JUDGMENTS
    assert [d.route for d in _step(result, 1).admissions] == [AdmissionRoute.APPLY] * 8
    assert _step(result, 3).judgment_ids == (J_CREATE_C, J_CLAIM_C)
    assert _step(result, 4).judgment_ids == (J_BIND_C, J_CLAIM_C_NEW)
    # The scripted reasoner exposes neither receipts nor drafts: nothing is invented.
    for step in result.steps:
        assert step.receipts == ()
        assert step.draft_outputs == ()
        assert set(step.readiness_by_scope) == {"intent-engine", "constitution"}

    # A timeline with a fifth step would need a ninth call: it is never made.
    extra = _timeline()
    fifth = extra[-1].model_copy(
        update={
            "t": 5,
            "content_sha256": hashlib.sha256(b"spec v4\n").hexdigest(),
            "item": extra[-1].item.model_copy(
                update={
                    "evidence_id": "EV-T5-01",
                    "content": "spec v4\n",
                    "content_sha256": hashlib.sha256(b"spec v4\n").hexdigest(),
                    "supersedes_evidence_id": "EV-T4-02",
                }
            ),
        }
    )
    over = ScriptedReasoner([*_script(), _t4_call_1])
    result = _run(over, timeline=(*extra, fifth))
    assert len(over.requests) == MAX_F_CALLS == result.calls_made
    assert [step.status for step in result.steps] == ["COMPLETED"] * 4 + ["NOT_RUN"]
    assert result.steps[4].error is not None
    assert "MAX_F_CALLS" in result.steps[4].error
    assert result.steps[4].evidence_shown == ()
    assert result.steps[4].judgment_ids == ()
    assert "EV-T5-01" not in {stored.event.event_id for stored in result.ledger}


def test_t_greater_than_one_receives_delta_only(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = _timeline()
    reasoner = ScriptedReasoner(_script())

    result = _run(reasoner, timeline=timeline)

    seen: set[tuple[str, str]] = set()
    for step in result.steps:
        delta = persistent_delta(timeline, step.t)
        call_1, call_2 = reasoner.requests[2 * (step.t - 1) : 2 * step.t]
        # Call 1 carries exactly the delta; Call 2 carries the delta first.
        assert tuple(item.evidence_id for item in call_1.evidence) == DELTA_IDS_BY_T[step.t]
        assert (
            tuple(item.evidence_id for item in call_2.evidence[: len(delta)])
            == (DELTA_IDS_BY_T[step.t])
        )
        # Nothing unchanged is ever re-sent in a delta position.
        for item in call_1.evidence:
            assert (item.artifact_ref, item.content_sha256) not in seen
            seen.add((item.artifact_ref, item.content_sha256))
        # The record proves what was shown: delta first, then anything Call 2 added.
        assert step.evidence_shown[: len(delta)] == DELTA_IDS_BY_T[step.t]
        shown_in_requests = {item.evidence_id for item in (*call_1.evidence, *call_2.evidence)}
        assert set(step.evidence_shown) == shown_in_requests
        assert set(step.addresses_shown) == {
            a.address_id for a in (*call_1.known_addresses, *call_2.known_addresses)
        }
        # 9P2: Call 1 shows live claim profiles too; citable evidence stays delta-only.
        assert set(step.claims_shown) == {
            c.claim_id for c in (*call_1.known_claims, *call_2.known_claims)
        }
    # The constitution (T1 only, never changed) is never sent again after T1.
    for step in result.steps[1:]:
        assert "EV-T1-01" not in step.evidence_shown
    # Call 1 at T>1 shows only addresses in the assimilation scope: the constitution
    # locus is out of scope for the intent-engine delta and is not shown.
    assert ADDR_A in _step(result, 2).addresses_shown
    assert ADDR_N not in _step(result, 2).addresses_shown
    assert [a.address_id for a in reasoner.requests[2].known_addresses] == sorted(
        [ADDR_A, ADDR_B, ADDR_U]
    )
    # Call 2 at T2 carries the delta only; the live claim's cited evidence is referenced
    # by id on the claim and is never resent as citable evidence (9P2: structurally
    # selected predecessor material may appear only in non-citable comparison context).
    assert _step(result, 2).evidence_shown == ("EV-T2-01",)
    # 9P2: Call 1 shows the live claim profiles of the three in-scope addresses.
    assert set(_step(result, 2).claims_shown) == {
        CLAIM_A,
        CLAIM_B,
        claim_id_for(PROJECT_ID, J_CLAIM_U),
    }

    # The structural guard: an unchanged item slipped into the delta aborts before the
    # call; an empty delta aborts too. Neither path makes a frontier call.
    unchanged = next(v.item for v in timeline if v.item.evidence_id == "EV-T1-01")

    def _stale_delta(items: tuple[VersionedEvidence, ...], t: int) -> tuple[Any, ...]:
        if t == 2:
            return (unchanged.model_copy(update={"evidence_id": "EV-T2-99"}),)
        return persistent_delta(items, t)

    monkeypatch.setattr(arm_f_module, "persistent_delta", _stale_delta)
    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, timeline=timeline)
    assert [step.status for step in result.steps] == ["COMPLETED", "FAILED", "NOT_RUN", "NOT_RUN"]
    assert len(reasoner.requests) == 2
    assert _step(result, 2).error is not None
    assert "unchanged" in _step(result, 2).error
    assert "EV-T2-99" not in {
        stored.event.payload.evidence.evidence_id
        for stored in result.ledger
        if stored.event.event_type is EventType.EVIDENCE_INGESTED
    }

    monkeypatch.setattr(
        arm_f_module,
        "persistent_delta",
        lambda items, t: () if t == 3 else persistent_delta(items, t),
    )
    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, timeline=timeline)
    assert [step.status for step in result.steps] == ["COMPLETED", "COMPLETED", "FAILED", "NOT_RUN"]
    assert len(reasoner.requests) == 4
    assert _step(result, 3).error is not None
    assert "empty" in _step(result, 3).error


def test_chains_attached_after_t1_before_t2() -> None:
    reasoner = ScriptedReasoner(_script())

    result = _run(reasoner)

    derivations = [
        stored
        for stored in result.ledger
        if stored.event.event_type is EventType.DERIVATION_RECORDED
    ]
    assert len(derivations) == 5
    edges = []
    for stored in derivations:
        payload = stored.event.payload
        assert isinstance(payload, DerivationPayload)
        edges.append((payload.child_id, payload.parent_id))
    assert edges == [
        (TRACK_A_CHAIN[0], J_CLAIM_A),
        (TRACK_A_CHAIN[1], TRACK_A_CHAIN[0]),
        (TRACK_A_CHAIN[2], TRACK_A_CHAIN[1]),
        (CONTROL_CHAIN[0], J_CLAIM_N),
        (CONTROL_CHAIN[1], CONTROL_CHAIN[0]),
    ]
    # Ordering: every derivation sits after T1's last admission and before T2's first ingest.
    sequences = [stored.sequence for stored in derivations]
    t1_last_admission = max(
        stored.sequence
        for stored in result.ledger
        if stored.event.event_type is EventType.SEMANTIC_ADMISSION_DECIDED
        and stored.event.payload.judgment_id in _step(result, 1).judgment_ids  # type: ignore[union-attr]
    )
    first_t2_ingest = min(
        stored.sequence
        for stored in result.ledger
        if stored.event.event_type is EventType.EVIDENCE_INGESTED
        and stored.event.payload.evidence.evidence_id.startswith("EV-T2-")  # type: ignore[union-attr]
    )
    assert t1_last_admission < min(sequences) and max(sequences) < first_t2_ingest
    assert sequences == sorted(sequences)
    # The T1 record already holds the chains; nothing was stale before T2.
    assert len(_step(result, 1).view.loci) == 4
    assert max(sequences) <= _step(result, 1).state_snapshot_revision
    assert replay(
        PROJECT_ID, result.ledger[: _step(result, 1).state_snapshot_revision]
    ).semantic.derivations
    assert (
        derive_view(
            replay(PROJECT_ID, result.ledger[: _step(result, 1).state_snapshot_revision]).semantic
        ).stale_ids
        == ()
    )

    # A designation that names an unknown address fails T1 and stops the run.
    reasoner = ScriptedReasoner(_script())
    result = _run(
        reasoner, ScriptedAuthorizer([]), designate_track_a=_select("ADDR-nowhere", J_CLAIM_A)
    )
    assert [step.status for step in result.steps] == ["FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    assert "ADDR-nowhere" in (_step(result, 1).error or "")
    assert len(reasoner.requests) == 2
    assert EventType.DERIVATION_RECORDED not in _event_types(result)

    # A designation whose judgment does not assert at the named address fails the same
    # way: the runner validates the architect's two ids and never substitutes a claim.
    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, ScriptedAuthorizer([]), designate_track_a=_select(ADDR_A, J_CLAIM_B))
    assert [step.status for step in result.steps] == ["FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    assert J_CLAIM_B in (_step(result, 1).error or "")
    assert ADDR_A in (_step(result, 1).error or "")
    assert EventType.DERIVATION_RECORDED not in _event_types(result)


def test_pending_supersession_is_offered_only_after_ai_proposal() -> None:
    authorizer = ScriptedAuthorizer([AuthorizationDecision.AGREE])
    reasoner = ScriptedReasoner(_script())

    result = _run(reasoner, authorizer)

    # Exactly one proposal was ever presented: the AI's own T2 SUPERSEDE, verbatim.
    assert [j.judgment_id for j in authorizer.presented] == [J_SUPERSEDE_A]
    presented = authorizer.presented[0]
    assert isinstance(presented.proposal, SupersedeProposal)
    assert presented.proposal.target_judgment_id == J_CLAIM_A
    assert presented.reasoner == MODEL
    # T1 offers nothing (nothing can be pending); T3/T4 have nothing pending either.
    assert _step(result, 1).authorizations == ()
    assert _step(result, 3).authorizations == ()
    assert _step(result, 4).authorizations == ()
    (record,) = _step(result, 2).authorizations
    assert record.pending_judgment_id == J_SUPERSEDE_A
    assert record.track == "A"
    assert record.decision is AuthorizationDecision.AGREE
    assert record.submitted_judgment_id is not None
    # The AGREE is a human judgment applied under human authority; the AI proposal is
    # satisfied by it and the Track A chain is stale while the control chain is not.
    t2 = _step(result, 2)
    assert t2.view.satisfied_by[J_SUPERSEDE_A] == record.submitted_judgment_id
    assert t2.view.pending_judgment_ids == ()
    assert set(t2.view.stale_ids) >= set(TRACK_A_CHAIN)
    assert set(t2.view.stale_ids).isdisjoint(CONTROL_CHAIN)
    assert t2.readiness_by_scope["intent-engine"].semantic_blockers_clear is False
    assert set(t2.readiness_by_scope["intent-engine"].stale_object_ids) >= set(TRACK_A_CHAIN)
    assert t2.readiness_by_scope["constitution"].semantic_blockers_clear is True
    human_judgments = [
        stored.event.payload.judgment  # type: ignore[union-attr]
        for stored in result.ledger
        if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
        and stored.event.payload.judgment.reasoner.is_human  # type: ignore[union-attr]
    ]
    assert [j.judgment_id for j in human_judgments] == [record.submitted_judgment_id]
    assert human_judgments[0].proposal == presented.proposal
    # The runner has no human path of its own: it authors no judgment and never submits.
    source = Path(arm_f_module.__file__).read_text(encoding="utf-8")
    assert ".submit(" not in source
    assert "human_actor_id" not in source
    assert "SemanticJudgment(" not in source
    assert "SupersedeProposal(" not in source

    # DECLINE: nothing is written, both claims stay live, the proposal stays pending and
    # qualifies exactly the intent-engine scope; T3 logs it as already declined and the
    # human is never asked again.
    authorizer = ScriptedAuthorizer([AuthorizationDecision.DECLINE])
    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, authorizer)
    assert [j.judgment_id for j in authorizer.presented] == [J_SUPERSEDE_A]
    assert [step.status for step in result.steps] == ["COMPLETED"] * 4
    (declined,) = _step(result, 2).authorizations
    assert declined.decision is AuthorizationDecision.DECLINE
    assert declined.submitted_judgment_id is None
    for t in (2, 3, 4):
        step = _step(result, t)
        assert step.view.pending_judgment_ids == (J_SUPERSEDE_A,)
        assert step.view.stale_ids == ()
        assert step.view.active_conflict_judgment_ids == ()
        assert step.readiness_by_scope["intent-engine"].pending_material_judgment_ids == (
            J_SUPERSEDE_A,
        )
        assert step.readiness_by_scope["intent-engine"].semantic_blockers_clear is False
        assert step.readiness_by_scope["constitution"].pending_material_judgment_ids == ()
        assert step.readiness_by_scope["constitution"].semantic_blockers_clear is True
    for t in (3, 4):
        (withheld,) = _step(result, t).authorizations
        assert withheld.pending_judgment_id == J_SUPERSEDE_A
        assert withheld.decision is None
        assert withheld.not_offered is NotOfferedReason.ALREADY_DECLINED
    assert not any(
        stored.event.payload.judgment.reasoner.is_human  # type: ignore[union-attr]
        for stored in result.ledger
        if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
    )


def test_authorization_halt_keeps_completed_records_and_fails_the_step() -> None:
    authorizer = ScriptedAuthorizer([AuthorizationDecision.AGREE, "MAYBE"])
    reasoner = ScriptedReasoner(
        _script(
            {
                2: _t2_binds((J_BIND_A, ADDR_A), (J_BIND_B, ADDR_B)),
                3: _t2_supersessions((J_SUPERSEDE_A, J_CLAIM_A), (J_SUPERSEDE_B, J_CLAIM_B)),
            }
        )
    )

    result = _run(reasoner, authorizer)

    assert [step.status for step in result.steps] == ["COMPLETED", "FAILED", "NOT_RUN", "NOT_RUN"]
    assert len(reasoner.requests) == 4
    assert [j.judgment_id for j in authorizer.presented] == [J_SUPERSEDE_A, J_SUPERSEDE_B]
    t2 = _step(result, 2)
    assert t2.error is not None
    assert "MAYBE" in t2.error
    # The record of what was presented and answered before the halt survives.
    (agreed,) = t2.authorizations
    assert agreed.pending_judgment_id == J_SUPERSEDE_A
    assert agreed.decision is AuthorizationDecision.AGREE
    assert t2.view.satisfied_by[J_SUPERSEDE_A] == agreed.submitted_judgment_id
    assert t2.view.pending_judgment_ids == (J_SUPERSEDE_B,)
    # The AI judgments of T2 and the human AGREE are all in the ledger; nothing was undone.
    assert t2.judgment_ids[:4] == (J_BIND_A, J_BIND_B, J_SUPERSEDE_A, J_SUPERSEDE_B)
    assert agreed.submitted_judgment_id in t2.judgment_ids


def test_failure_at_t3_call_two_freezes_and_marks_t4_not_run() -> None:
    reasoner = ScriptedReasoner(_script({5: RuntimeError("provider failure")}))

    result = _run(reasoner)

    assert [step.status for step in result.steps] == ["COMPLETED", "COMPLETED", "FAILED", "NOT_RUN"]
    assert len(reasoner.requests) == 6 == result.calls_made
    failed = _step(result, 3)
    assert failed.error is not None
    assert "provider failure" in failed.error
    # Call 1's admission is kept; nothing was rolled back or retried.
    assert failed.judgment_ids == (J_CREATE_C,)
    assert [d.route for d in failed.admissions] == [AdmissionRoute.APPLY]
    assert ADDR_C in {a for locus in failed.view.loci for a in locus.address_ids}
    assert failed.evidence_shown[: len(DELTA_IDS_BY_T[3])] == DELTA_IDS_BY_T[3]
    # T4 never ran, nothing of T4 was ingested, and the frozen state is what T3 left.
    not_run = _step(result, 4)
    assert not_run.error is not None
    assert "T3" in not_run.error
    assert not_run.evidence_shown == ()
    assert not_run.judgment_ids == ()
    assert not_run.authorizations == ()
    assert not_run.state_snapshot_revision == failed.state_snapshot_revision
    assert not_run.view == failed.view
    ingested = {
        stored.event.payload.evidence.evidence_id  # type: ignore[union-attr]
        for stored in result.ledger
        if stored.event.event_type is EventType.EVIDENCE_INGESTED
    }
    assert not any(evidence_id.startswith("EV-T4-") for evidence_id in ingested)
    assert result.final_state_revision == failed.state_snapshot_revision == len(result.ledger)
    # No retry path exists in source.
    source = Path(arm_f_module.__file__).read_text(encoding="utf-8")
    assert "retry" not in source.lower()
    assert "retries" not in source.lower()

    # A failure in Call 1 freezes just the same, with T2's ingest kept.
    reasoner = ScriptedReasoner(_script({2: RuntimeError("provider failure at call 1")}))
    result = _run(reasoner)
    assert [step.status for step in result.steps] == ["COMPLETED", "FAILED", "NOT_RUN", "NOT_RUN"]
    assert len(reasoner.requests) == 3 == result.calls_made
    assert _step(result, 2).judgment_ids == ()
    assert "EV-T2-01" in _step(result, 2).view.current_evidence_ids


def test_t1_call_1_failure_counts_exactly_one_call_and_stops_the_arm() -> None:
    # 9P-C-R2 accounting: a T that fails on Call 1 has made one call, never
    # CALLS_PER_DELTA; T2-T4 are NOT_RUN and cause no further request.
    reasoner = ScriptedReasoner(_script({0: RuntimeError("provider failure at T1 call 1")}))

    result = _run(reasoner, ScriptedAuthorizer([]))

    assert [step.status for step in result.steps] == ["FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    assert result.calls_made == len(reasoner.requests) == 1
    failed = _step(result, 1)
    assert failed.error is not None
    assert "provider failure at T1 call 1" in failed.error
    assert len(failed.allowed_kinds_per_call) == 1
    assert failed.judgment_ids == ()
    assert [step.error for step in result.steps[1:]] == ["stopped: T1 failed"] * 3
    assert all(step.allowed_kinds_per_call == () for step in result.steps[1:])
    # The T1 ingest is kept; no designation and no chain were recorded.
    assert "EV-T1-01" in failed.view.current_evidence_ids
    assert result.designations == ()
    assert EventType.DERIVATION_RECORDED not in _event_types(result)


def test_tracked_locus_names_never_appear_in_any_request() -> None:
    reasoner = ScriptedReasoner(_script())

    _run(reasoner)

    assert len(reasoner.requests) == MAX_F_CALLS
    descriptions = [locus.description.lower() for locus in TRACKED_LOCI]
    keys = [locus.key for locus in TRACKED_LOCI]
    assert descriptions and keys
    for request in reasoner.requests:
        rendered = json.loads(render_request(request))
        # Evidence content is real Foundry history and may legitimately mention anything;
        # everything else in the request is Foundry's own framing and must not.
        for entry in rendered["evidence"]:
            entry["content"] = ""
        framing = json.dumps(rendered, ensure_ascii=False).lower()
        for description in descriptions:
            assert description not in framing
        for key in keys:
            assert f'"track {key.lower()}"' not in framing
    # The runner never imports the sealed manifest, so it cannot leak it.
    source = Path(arm_f_module.__file__).read_text(encoding="utf-8")
    assert "expectations" not in source
    assert "TRACKED_LOCI" not in source


def test_arm_f_ledger_replays_identically() -> None:
    reasoner = ScriptedReasoner(_script())

    result = _run(reasoner)

    replayed = replay(PROJECT_ID, result.ledger)
    assert replayed.revision == result.final_state_revision == len(result.ledger)
    assert replayed.last_sequence == result.ledger[-1].sequence
    assert derive_view(replayed.semantic) == result.steps[-1].view
    # Every step's snapshot is the replay of the ledger prefix up to its revision.
    for step in result.steps:
        prefix = result.ledger[: step.state_snapshot_revision]
        state = replay(PROJECT_ID, prefix)
        assert state.revision == step.state_snapshot_revision
        assert derive_view(state.semantic) == step.view
    # Replaying twice is the same state; the ledger holds T1's claims to the end.
    assert replay(PROJECT_ID, result.ledger) == replayed
    assert {CLAIM_A, CLAIM_B} <= set(replayed.semantic.claims)
    assert J_CLAIM_A in replayed.semantic.judgments


def test_receipts_and_drafts_are_captured_per_t_when_the_reasoner_exposes_them() -> None:
    reasoner = RecordingReasoner(_script({5: RuntimeError("provider failure")}))

    result = _run(reasoner)

    assert [step.status for step in result.steps] == ["COMPLETED", "COMPLETED", "FAILED", "NOT_RUN"]
    for step in result.steps[:3]:
        assert [receipt.invocation_id for receipt in step.receipts] == [
            f"INV-{2 * step.t - 1}",
            f"INV-{2 * step.t}",
        ]
        assert len(step.draft_outputs) == 2
    assert result.steps[3].receipts == ()
    assert result.steps[3].draft_outputs == ()
    assert sum(len(step.receipts) for step in result.steps) == len(reasoner.receipts) == 6


def test_same_system_instruction_hash_as_the_adapter() -> None:
    assert arm_f_module.SYSTEM_INSTRUCTION_SHA256 is xai_reasoner.SYSTEM_INSTRUCTION_SHA256
    source = Path(arm_f_module.__file__).read_text(encoding="utf-8")
    assert xai_reasoner.SYSTEM_INSTRUCTION_SHA256[:8] not in source


def test_allowed_kinds_per_call_are_recorded_from_real_requests_and_never_equivalence() -> None:
    reasoner = ScriptedReasoner(_script({5: RuntimeError("provider failure")}))

    result = _run(reasoner)

    call_1 = tuple(sorted(kind.value for kind in ASSIMILATION_JUDGMENT_KINDS))
    call_2 = tuple(sorted(kind.value for kind in CLAIM_ASSIMILATION_JUDGMENT_KINDS))
    assert [step.status for step in result.steps] == ["COMPLETED", "COMPLETED", "FAILED", "NOT_RUN"]
    for step in result.steps[:3]:
        assert step.allowed_kinds_per_call == (call_1, call_2)
        for kinds in step.allowed_kinds_per_call:
            assert JudgmentKind.EQUIVALENT.value not in kinds
            assert JudgmentKind.DISTINCT.value not in kinds
    assert result.steps[3].allowed_kinds_per_call == ()
    # The log is what the reasoner actually received, call for call.
    recorded = [
        tuple(sorted(kind.value for kind in request.allowed_judgment_kinds))
        for request in reasoner.requests
    ]
    assert recorded == [kinds for step in result.steps for kinds in step.allowed_kinds_per_call]

    # A failure at Call 1 leaves exactly one entry for that T.
    reasoner = ScriptedReasoner(_script({2: RuntimeError("provider failure at call 1")}))
    result = _run(reasoner)
    assert _step(result, 2).status == "FAILED"
    assert _step(result, 2).allowed_kinds_per_call == (call_1,)
    # The recorder is the one shared with Arm R, not a second implementation.
    source = Path(arm_f_module.__file__).read_text(encoding="utf-8")
    assert "RequestRecorder" in source
    assert "class _RequestRecorder" not in source
    assert "class RequestRecorder" not in source


def test_designations_are_recorded_structurally_at_the_right_moments() -> None:
    reasoner = ScriptedReasoner(_script())
    seen: dict[str, str] = {}

    def observing(track: str, selection: RootSelection) -> Selector:
        def select(state: IntentState) -> RootSelection:
            seen[track] = _last_ingested(state)
            return selection

        return select

    result = _run(
        reasoner,
        designate_track_a=observing("A", RootSelection(address_id=ADDR_A, judgment_id=J_CLAIM_A)),
        designate_track_b=observing("B", RootSelection(address_id=ADDR_B, judgment_id=J_CLAIM_B)),
        designate_track_c=observing("C", RootSelection(address_id=ADDR_C, judgment_id=J_CLAIM_C)),
        designate_control=observing(
            "CONTROL", RootSelection(address_id=ADDR_N, judgment_id=J_CLAIM_N)
        ),
    )

    # Visibility: A, B and the control see a state whose last ingested evidence is T1's;
    # C sees one whose last ingested evidence is T3's. No selector ever sees later T.
    assert seen == {
        "A": DELTA_IDS_BY_T[1][-1],
        "B": DELTA_IDS_BY_T[1][-1],
        "CONTROL": DELTA_IDS_BY_T[1][-1],
        "C": DELTA_IDS_BY_T[3][-1],
    }
    assert [d.track for d in result.designations] == ["A", "B", "CONTROL", "C"]
    by_track = {d.track: d for d in result.designations}
    assert by_track["A"].address_id == ADDR_A and by_track["A"].judgment_id == J_CLAIM_A
    assert by_track["B"].address_id == ADDR_B and by_track["B"].judgment_id == J_CLAIM_B
    assert by_track["CONTROL"].address_id == ADDR_N
    assert by_track["CONTROL"].judgment_id == J_CLAIM_N
    assert by_track["C"].address_id == ADDR_C and by_track["C"].judgment_id == J_CLAIM_C
    # A, B and the control are designated after T1's last admission and before the chains
    # are attached (which is before T2's first ingest).
    admissions_t1 = _sequence_of(
        result,
        EventType.SEMANTIC_ADMISSION_DECIDED,
        lambda payload: payload.judgment_id in T1_JUDGMENTS,
    )
    first_derivation = min(_sequence_of(result, EventType.DERIVATION_RECORDED, lambda _p: True))
    first_t2_ingest = min(
        _sequence_of(
            result,
            EventType.EVIDENCE_INGESTED,
            lambda payload: payload.evidence.evidence_id.startswith("EV-T2-"),
        )
    )
    for track in ("A", "B", "CONTROL"):
        at = by_track[track].ledger_sequence_at_designation
        assert max(admissions_t1) <= at < first_derivation < first_t2_ingest
    # C is designated after T3's last admission and strictly before T4's first ingest.
    admissions_t3 = _sequence_of(
        result,
        EventType.SEMANTIC_ADMISSION_DECIDED,
        lambda payload: payload.judgment_id in (J_CREATE_C, J_CLAIM_C),
    )
    first_t4_ingest = min(
        _sequence_of(
            result,
            EventType.EVIDENCE_INGESTED,
            lambda payload: payload.evidence.evidence_id.startswith("EV-T4-"),
        )
    )
    at_c = by_track["C"].ledger_sequence_at_designation
    assert max(admissions_t3) <= at_c < first_t4_ingest
    assert at_c == _step(result, 3).state_snapshot_revision
    # Designation writes nothing: the ledger holds no event for it and only the A and
    # control chains are attached.
    assert len(_sequence_of(result, EventType.DERIVATION_RECORDED, lambda _p: True)) == 5
    assert [step.status for step in result.steps] == ["COMPLETED"] * 4

    # If the Track C selector fails, T3 is FAILED after its calls and T4 is NOT_RUN.
    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, designate_track_c=_select("ADDR-nowhere", J_CLAIM_C))
    assert [step.status for step in result.steps] == ["COMPLETED", "COMPLETED", "FAILED", "NOT_RUN"]
    assert len(reasoner.requests) == 6
    assert _step(result, 3).judgment_ids == (J_CREATE_C, J_CLAIM_C)
    assert "ADDR-nowhere" in (_step(result, 3).error or "")
    assert [d.track for d in result.designations] == ["A", "B", "CONTROL"]

    # If the Track B selector fails, T1 is FAILED and no chain is attached.
    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, designate_track_b=_select("ADDR-nowhere", J_CLAIM_B))
    assert [step.status for step in result.steps] == ["FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    assert EventType.DERIVATION_RECORDED not in _event_types(result)
    assert [d.track for d in result.designations] == ["A"]


def test_track_is_identified_structurally_from_the_superseded_claims_address() -> None:
    # A SUPERSEDE whose target claim sits at the Track B address is offered as track "B".
    authorizer = ScriptedAuthorizer([AuthorizationDecision.AGREE])
    reasoner = ScriptedReasoner(
        _script(
            {
                2: _t2_binds((J_BIND_B, ADDR_B)),
                3: _t2_supersessions((J_SUPERSEDE_B, J_CLAIM_B)),
            }
        )
    )
    result = _run(reasoner, authorizer)
    assert [step.status for step in result.steps] == ["COMPLETED"] * 4
    assert [j.judgment_id for j in authorizer.presented] == [J_SUPERSEDE_B]
    (record,) = _step(result, 2).authorizations
    assert record.track == "B"
    assert record.decision is AuthorizationDecision.AGREE
    assert record.pending_judgment_id == J_SUPERSEDE_B

    # A SUPERSEDE at an undesignated address is UNTRACKED: logged, never presented.
    authorizer = ScriptedAuthorizer([])
    reasoner = ScriptedReasoner(
        _script(
            {
                2: _t2_binds((J_BIND_U, ADDR_U)),
                3: _t2_supersessions((J_SUPERSEDE_U, J_CLAIM_U)),
            }
        )
    )
    result = _run(reasoner, authorizer)
    assert [step.status for step in result.steps] == ["COMPLETED"] * 4
    assert authorizer.presented == []
    (record,) = _step(result, 2).authorizations
    assert record.track is None
    assert record.not_offered is NotOfferedReason.UNTRACKED
    assert record.pending_judgment_id == J_SUPERSEDE_U
    assert _step(result, 2).view.pending_judgment_ids == (J_SUPERSEDE_U,)

    # A SUPERSEDE at the Track C address, after C was designated at T3, is offered as "C".
    authorizer = ScriptedAuthorizer([AuthorizationDecision.AGREE, AuthorizationDecision.DECLINE])
    reasoner = ScriptedReasoner(_script({7: _t4_call_2_with_supersession}))
    result = _run(reasoner, authorizer)
    assert [step.status for step in result.steps] == ["COMPLETED"] * 4
    assert [j.judgment_id for j in authorizer.presented] == [J_SUPERSEDE_A, J_SUPERSEDE_C]
    (record,) = _step(result, 4).authorizations
    assert record.track == "C"
    assert record.decision is AuthorizationDecision.DECLINE
    pending = _step(result, 4).readiness_by_scope["intent-engine"].pending_material_judgment_ids
    assert pending == (J_SUPERSEDE_C,)
    # The runner takes no external track map: track identity is derived from state.
    source = Path(arm_f_module.__file__).read_text(encoding="utf-8")
    signature = source.split("def run_arm_f(")[1].split(") -> ArmFResult")[0]
    assert "track_of" not in signature


def test_designated_addresses_must_be_pairwise_distinct() -> None:
    # Track B selecting Track A's address: T1 FAILED after its calls, no designation for
    # the duplicate, nothing attached, the rest NOT_RUN.
    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, ScriptedAuthorizer([]), designate_track_b=SELECT_A)
    assert [step.status for step in result.steps] == ["FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    assert len(reasoner.requests) == 2
    error = _step(result, 1).error or ""
    assert "ValueError" in error
    assert "track A" in error and "track B" in error
    assert [d.track for d in result.designations] == ["A"]
    assert EventType.DERIVATION_RECORDED not in _event_types(result)

    # The control selecting Track B's address: same shape, both tracks named.
    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, ScriptedAuthorizer([]), designate_control=SELECT_B)
    assert [step.status for step in result.steps] == ["FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    error = _step(result, 1).error or ""
    assert "track B" in error and "track CONTROL" in error
    assert [d.track for d in result.designations] == ["A", "B"]
    assert EventType.DERIVATION_RECORDED not in _event_types(result)

    # Track C selecting Track B's address: T3 FAILED after its calls, T4 NOT_RUN.
    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, designate_track_c=SELECT_B)
    assert [step.status for step in result.steps] == ["COMPLETED", "COMPLETED", "FAILED", "NOT_RUN"]
    assert len(reasoner.requests) == 6
    error = _step(result, 3).error or ""
    assert "track B" in error and "track C" in error
    assert [d.track for d in result.designations] == ["A", "B", "CONTROL"]


def test_track_c_may_designate_an_address_that_existed_before_t3() -> None:
    """Ruling C: E8 requires only that C exist after T3 with an INFERRED claim describing
    the observed defective behaviour. A related locus (here ADDR_U, created at T1) may
    already exist; at T3 the model BINDs the T3 code evidence to it and ASSERTs the
    defect claim there, and the architect designates that address as Track C.
    """

    def t3_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
        return [_bind(J_BIND_C_AT_T3, request, ADDR_U, "EV-T3-02")]

    def t3_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
        return [
            _claim(J_CLAIM_C, request, ADDR_U, "EV-T3-02", 3, authority=Authority.INFERRED),
        ]

    def t4_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
        return [_bind(J_BIND_C, request, ADDR_U, "EV-T4-01")]

    def t4_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
        return [
            _claim(J_CLAIM_C_NEW, request, ADDR_U, "EV-T4-01", 4),
            _supersede(J_SUPERSEDE_C, request, J_CLAIM_C, "EV-T4-01"),
        ]

    authorizer = ScriptedAuthorizer([AuthorizationDecision.AGREE, AuthorizationDecision.AGREE])
    reasoner = ScriptedReasoner(_script({4: t3_call_1, 5: t3_call_2, 6: t4_call_1, 7: t4_call_2}))

    result = _run(reasoner, authorizer, designate_track_c=_select(ADDR_U, J_CLAIM_C))

    assert [step.status for step in result.steps] == ["COMPLETED"] * 4
    assert [step.error for step in result.steps] == [None] * 4
    assert len(reasoner.requests) == MAX_F_CALLS
    # ADDR_U existed at the end of T1 and T2; no address was created at T3.
    for t in (1, 2):
        assert ADDR_U in {a for locus in _step(result, t).view.loci for a in locus.address_ids}
    assert _step(result, 3).judgment_ids == (J_BIND_C_AT_T3, J_CLAIM_C)
    assert ADDR_C not in {a for locus in _step(result, 3).view.loci for a in locus.address_ids}
    # The C designation succeeded, from T3 state, with the architect's two ids verbatim.
    assert [d.track for d in result.designations] == ["A", "B", "CONTROL", "C"]
    c = result.designations[-1]
    assert (c.address_id, c.judgment_id) == (ADDR_U, J_CLAIM_C)
    assert c.ledger_sequence_at_designation == _step(result, 3).state_snapshot_revision
    # The T3 view holds the INFERRED defect claim at ADDR_U.
    t3_claims = {claim_id for locus in _step(result, 3).view.loci for claim_id in locus.claim_ids}
    assert claim_id_for(PROJECT_ID, J_CLAIM_C) in t3_claims
    # The T4 supersession at that address is offered as track "C" and answered.
    assert [j.judgment_id for j in authorizer.presented] == [J_SUPERSEDE_A, J_SUPERSEDE_C]
    (record,) = _step(result, 4).authorizations
    assert record.track == "C"
    assert record.pending_judgment_id == J_SUPERSEDE_C
    assert record.decision is AuthorizationDecision.AGREE
    assert _step(result, 4).view.satisfied_by[J_SUPERSEDE_C] == record.submitted_judgment_id
    # Pairwise distinctness is retained: C may not reuse an already-designated address.
    reasoner = ScriptedReasoner(_script({4: t3_call_1, 5: t3_call_2}))
    result = _run(reasoner, designate_track_c=_select(ADDR_B, J_CLAIM_C))
    assert [step.status for step in result.steps] == ["COMPLETED", "COMPLETED", "FAILED", "NOT_RUN"]
    error = _step(result, 3).error or ""
    assert "track B" in error and "track C" in error
    # The runner keeps no "new at T3" bookkeeping for Track C.
    source = Path(arm_f_module.__file__).read_text(encoding="utf-8")
    assert "addresses_at_end" not in source
    assert "snapshot_addresses" not in source


def test_supersede_at_the_control_address_is_untracked_and_never_offered() -> None:
    # An intent-engine-scoped control address can enter the T2 neighbourhood; a
    # SUPERSEDE of its claim identifies no track and is never presented to the human.
    authorizer = ScriptedAuthorizer([])
    reasoner = ScriptedReasoner(
        _script(
            {
                2: _t2_binds((J_BIND_U, ADDR_U)),
                3: _t2_supersessions((J_SUPERSEDE_U, J_CLAIM_U)),
            }
        )
    )
    result = _run(reasoner, authorizer, designate_control=_select(ADDR_U, J_CLAIM_U))
    assert [step.status for step in result.steps] == ["COMPLETED"] * 4
    assert {d.track: d.address_id for d in result.designations}["CONTROL"] == ADDR_U
    assert authorizer.presented == []
    (record,) = _step(result, 2).authorizations
    assert record.pending_judgment_id == J_SUPERSEDE_U
    assert record.track is None
    assert record.not_offered is NotOfferedReason.UNTRACKED
    assert _step(result, 2).view.pending_judgment_ids == (J_SUPERSEDE_U,)
    assert set(_step(result, 2).view.stale_ids).isdisjoint(CONTROL_CHAIN)


def test_arm_f_reuses_arm_r_helpers_instead_of_redefining_them() -> None:
    source = Path(arm_f_module.__file__).read_text(encoding="utf-8")
    for name in ("ledger_judgment_ids", "ledger_admissions", "RecordedCalls", "recorded_calls"):
        assert name in source
    for forbidden in ("def _judgment_ids", "def _admissions", "class _Recorded", "def _recorded"):
        assert forbidden not in source
    assert "allowed_kinds_since" in source
    assert "T2_ARTIFACT_REFS_T" in source and "TRACK_C_DESIGNATION_T" in source


def test_on_t1_designations_is_called_once_after_attach_and_before_t2_ingest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R16-a: the T1 designation hook fires inside T1, after the chains, before T2's ingest."""
    stores: list[InMemoryEventStore] = []
    real_store = InMemoryEventStore

    def capturing_store() -> InMemoryEventStore:
        store = real_store()
        stores.append(store)
        return store

    monkeypatch.setattr(arm_f_module, "InMemoryEventStore", capturing_store)
    calls: list[tuple[tuple[RootDesignation, ...], int, int]] = []

    def spy(designations: tuple[RootDesignation, ...]) -> None:
        (store,) = stores
        stream = store.load(PROJECT_ID)
        t2_ingests = [
            s.sequence
            for s in stream
            if s.event.event_type is EventType.EVIDENCE_INGESTED
            and s.event.payload.evidence.evidence_id.startswith("EV-T2-")
        ]
        calls.append((designations, store.current_sequence(PROJECT_ID), len(t2_ingests)))

    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, on_t1_designations=spy)

    assert [step.status for step in result.steps] == ["COMPLETED"] * 4
    (call,) = calls
    designations, sequence_at_call, t2_ingests_at_call = call
    assert [d.track for d in designations] == ["A", "B", "CONTROL"]
    assert designations == result.designations[:3]
    assert t2_ingests_at_call == 0
    first_derivation = min(_sequence_of(result, EventType.DERIVATION_RECORDED, lambda _p: True))
    first_t2_ingest = min(
        _sequence_of(
            result,
            EventType.EVIDENCE_INGESTED,
            lambda payload: payload.evidence.evidence_id.startswith("EV-T2-"),
        )
    )
    # Called after every chain edge is recorded (5 derivations) and before T2 ingests.
    assert first_derivation <= sequence_at_call < first_t2_ingest
    assert sequence_at_call == _step(result, 1).state_snapshot_revision
    assert len(reasoner.requests) == MAX_F_CALLS

    # The default is no hook: the run is unchanged.
    assert [s.status for s in _run(ScriptedReasoner(_script())).steps] == ["COMPLETED"] * 4


def test_raising_on_t1_designations_fails_t1_and_marks_later_ts_not_run() -> None:
    def explode(_designations: tuple[RootDesignation, ...]) -> None:
        raise OSError("expectations.json could not be updated")

    reasoner = ScriptedReasoner(_script())
    result = _run(reasoner, on_t1_designations=explode)

    assert [step.status for step in result.steps] == ["FAILED", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    assert "expectations.json could not be updated" in (_step(result, 1).error or "")
    assert len(reasoner.requests) == 2
    # The designations and chains were recorded before the hook raised; nothing after.
    assert [d.track for d in result.designations] == ["A", "B", "CONTROL"]
    assert len(_sequence_of(result, EventType.DERIVATION_RECORDED, lambda _p: True)) == 5
    assert EventType.EVIDENCE_INGESTED not in [
        s.event.event_type for s in result.ledger if s.sequence > result.final_state_revision
    ]


def test_keyboard_interrupt_mid_step_is_recorded_as_failure_and_result_is_returned() -> None:
    reasoner = ScriptedReasoner(_script({3: KeyboardInterrupt()}))

    result = _run(reasoner)

    assert [step.status for step in result.steps] == ["COMPLETED", "FAILED", "NOT_RUN", "NOT_RUN"]
    assert _step(result, 2).error == "INTERRUPTED: KeyboardInterrupt"
    assert result.calls_made == len(reasoner.requests) == 4
    # Everything up to the interrupt is preserved for artifact writing.
    assert _step(result, 2).judgment_ids == (J_BIND_A,)
    assert "EV-T2-01" in _step(result, 2).view.current_evidence_ids
    assert (
        result.final_state_revision
        == len(result.ledger)
        == _step(result, 2).state_snapshot_revision
    )
    assert "T2" in (_step(result, 3).error or "")

    # SystemExit is never swallowed.
    reasoner = ScriptedReasoner(_script({3: SystemExit(3)}))
    with pytest.raises(SystemExit):
        _run(reasoner)

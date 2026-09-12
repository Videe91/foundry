"""9P2 T4: exact per-call request recording (spec §17.3; brief T4).

``RecordingReasoner`` wraps any ``SemanticReasoner``, renders every request through
the frozen ``render_request`` before delegating, hashes the exact UTF-8 bytes, and
records structural ids only. It never changes the request or the returned judgments,
refuses a third call within one step before delegating, and keeps the record when the
inner reasoner raises. Every reasoner here is a scripted fake; ZERO live calls.
"""

from __future__ import annotations

import ast
import hashlib
import json
import socket
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
    render_request,
)
from foundry.application.assimilation_context import (
    assemble_assimilation_request,
    assemble_claim_request,
)
from foundry.application.contrastive_context import (
    comparison_context_character_count,
    historical_evidence_ids,
)
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.experiments.contrastive_unseen import records as records_module
from foundry.experiments.contrastive_unseen.ablation import (
    assemble_ablation_call1,
    assemble_ablation_call2,
)
from foundry.experiments.contrastive_unseen.records import RecordingReasoner, RequestRecord
from foundry.ports.semantic_reasoner import ReasoningRequest

PROJECT = "PROJ-RECORDS-ALPHA"
SCOPE = "SCOPE_ALPHA"
ARTIFACT = "ARTIFACT_ALPHA"
T0 = datetime(2026, 9, 12, tzinfo=UTC)
FINGERPRINT = ReasonerFingerprint(provider="fake", model="fake-model", policy_version="fake-v0")
FR_FINGERPRINT = ReasonerFingerprint(
    provider="fake", model="fake-model", policy_version=CONTRASTIVE_POLICY_VERSION
)
A_FINGERPRINT = ReasonerFingerprint(
    provider="fake", model="fake-model", policy_version=POLICY_VERSION
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- fakes ------------------------------------------------------------------------


class ScriptedReasoner:
    """Records every request; returns the scripted batch or raises the scripted error.

    Its fingerprint carries the policy of the arm it is meant for (F/R by default).
    """

    def __init__(
        self,
        batches: list[tuple[SemanticJudgment, ...] | BaseException],
        *,
        fingerprint: ReasonerFingerprint = FR_FINGERPRINT,
    ) -> None:
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
        return batch


class ReasonerWithEconomics(ScriptedReasoner):
    """A reasoner exposing adapter-style ``receipts`` and ``draft_payloads``."""

    @property
    def receipts(self) -> tuple[str, ...]:
        return ("RECEIPT_ALPHA",)

    @property
    def draft_payloads(self) -> tuple[str, ...]:
        return ("PAYLOAD_ALPHA",)


# --- builders ---------------------------------------------------------------------


def _fingerprint_for(arm: str) -> ReasonerFingerprint:
    return A_FINGERPRINT if arm == "A" else FR_FINGERPRINT


def _inner(
    arm: str, batches: list[tuple[SemanticJudgment, ...] | BaseException]
) -> ScriptedReasoner:
    return ScriptedReasoner(batches, fingerprint=_fingerprint_for(arm))


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0 + timedelta(minutes=next(tick))


def _governor() -> SemanticGovernor:
    clock = _clock()
    return SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
    )


def _evidence(evidence_id: str, *, supersedes: str | None = None) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"ref://{evidence_id}",
        content=f"<EVIDENCE:{evidence_id}>",
        observed_at=T0,
        scope=(SCOPE,),
        artifact_ref=ARTIFACT,
        supersedes_evidence_id=supersedes,
    )


def _judgment(judgment_id: str, proposal: JudgmentProposal, evidence_id: str) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale="RATIONALE_ALPHA",
        reasoner=FINGERPRINT,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _seed_address_and_claim(governor: SemanticGovernor) -> str:
    """One address with one live claim citing EV-1; returns the address id."""
    governor.ingest(_evidence("EV-1"))
    candidate = SemanticCandidate(
        candidate_id="CAND-ALPHA",
        subject="SUBJECT_ALPHA",
        facet="FACET_ALPHA",
        scope=(SCOPE,),
        evidence_ids=("EV-1",),
    )
    create = governor.submit(_judgment("J-c1", CreateAddressProposal(candidate=candidate), "EV-1"))
    assert create.route is AdmissionRoute.APPLY
    (address_id,) = governor.state().semantic.addresses
    claim = AssertClaimProposal(
        address_id=address_id,
        predicate="PREDICATE_ALPHA",
        value=ClaimValue(kind=ClaimValueKind.TEXT, text="CLAIM_VALUE_ALPHA"),
        evidence_ids=("EV-1",),
        authority=Authority.OBSERVED,
    )
    assert governor.submit(_judgment("J-cl1", claim, "EV-1")).route is AdmissionRoute.APPLY
    return address_id


def _correction_delta() -> tuple[EvidenceItem, ...]:
    return (_evidence("EV-2", supersedes="EV-1"),)


def _contrastive_call1() -> ReasoningRequest:
    governor = _governor()
    _seed_address_and_claim(governor)
    delta = _correction_delta()
    governor.ingest(delta[0])
    return assemble_assimilation_request(
        project_id=PROJECT, delta=delta, state=governor.state(), scope=SCOPE
    )


def _contrastive_call2() -> ReasoningRequest:
    governor = _governor()
    address_id = _seed_address_and_claim(governor)
    delta = _correction_delta()
    governor.ingest(delta[0])
    return assemble_claim_request(
        project_id=PROJECT, delta=delta, state=governor.state(), neighborhood=(address_id,)
    )


def _ablation_call1() -> ReasoningRequest:
    governor = _governor()
    _seed_address_and_claim(governor)
    delta = _correction_delta()
    governor.ingest(delta[0])
    return assemble_ablation_call1(
        project_id=PROJECT, delta=delta, state=governor.state(), scope=SCOPE
    )


def _ablation_call2() -> ReasoningRequest:
    governor = _governor()
    address_id = _seed_address_and_claim(governor)
    delta = _correction_delta()
    governor.ingest(delta[0])
    return assemble_ablation_call2(
        project_id=PROJECT, delta=delta, state=governor.state(), neighborhood=(address_id,)
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- record shape -----------------------------------------------------------------


def test_request_record_has_exactly_the_brief_fields() -> None:
    assert tuple(RequestRecord.model_fields) == (
        "arm",
        "t",
        "call_number",
        "policy_version",
        "system_prompt_sha256",
        "rendered_user_request",
        "request_sha256",
        "citable_evidence_ids",
        "historical_comparison_evidence_ids",
        "known_address_ids",
        "known_claim_ids",
        "allowed_judgment_kinds",
        "comparison_context_chars",
    )


def test_request_record_is_frozen() -> None:
    request = _contrastive_call1()
    inner = ScriptedReasoner([()])
    reasoner = RecordingReasoner(inner, arm="F")
    reasoner.begin_step(2)
    reasoner.propose(request)
    (record,) = reasoner.records
    with pytest.raises(Exception, match="frozen"):
        record.t = 3  # type: ignore[misc]


# --- arm identity -----------------------------------------------------------------


def test_arm_f_records_contrastive_identity_and_five_key_rendering() -> None:
    request = _contrastive_call1()
    inner = ScriptedReasoner([()])
    reasoner = RecordingReasoner(inner, arm="F")
    reasoner.begin_step(2)

    reasoner.propose(request)

    (record,) = reasoner.records
    rendered = render_request(request, include_comparison_context=True)
    assert record.arm == "F"
    assert record.t == 2
    assert record.call_number == 1
    assert record.policy_version == CONTRASTIVE_POLICY_VERSION
    assert record.system_prompt_sha256 == CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256
    assert record.rendered_user_request == rendered
    assert "comparison_context" in json.loads(rendered)
    assert record.request_sha256 == _sha256(rendered)
    assert record.citable_evidence_ids == ("EV-2",)
    assert record.historical_comparison_evidence_ids == historical_evidence_ids(
        request.comparison_context
    )
    assert record.historical_comparison_evidence_ids == ("EV-1",)
    assert record.known_address_ids == tuple(a.address_id for a in request.known_addresses)
    assert len(record.known_address_ids) == 1
    assert record.known_claim_ids == tuple(c.claim_id for c in request.known_claims)
    assert len(record.known_claim_ids) == 1
    assert record.allowed_judgment_kinds == ("BIND_TO_ADDRESS", "CREATE_ADDRESS")
    assert record.comparison_context_chars == comparison_context_character_count(
        request.comparison_context
    )
    assert record.comparison_context_chars > 0


def test_arm_r_records_contrastive_identity_like_f() -> None:
    request = _contrastive_call2()
    reasoner = RecordingReasoner(ScriptedReasoner([()]), arm="R")
    reasoner.begin_step(1)

    reasoner.propose(request)

    (record,) = reasoner.records
    assert record.arm == "R"
    assert record.policy_version == CONTRASTIVE_POLICY_VERSION
    assert record.system_prompt_sha256 == CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256
    assert record.rendered_user_request == render_request(request, include_comparison_context=True)
    assert record.allowed_judgment_kinds == (
        "ASSERT_CLAIM",
        "CONFLICTS_WITH",
        "SUPERSEDE",
        "SUPPORTS_CLAIM",
    )
    assert record.comparison_context_chars == comparison_context_character_count(
        request.comparison_context
    )


def test_arm_a_records_historical_identity_four_key_rendering_and_zero_context_chars() -> None:
    request = _ablation_call2()
    reasoner = RecordingReasoner(_inner("A", [()]), arm="A")
    reasoner.begin_step(2)

    reasoner.propose(request)

    (record,) = reasoner.records
    rendered = render_request(request, include_comparison_context=False)
    assert record.arm == "A"
    assert record.policy_version == POLICY_VERSION
    assert record.system_prompt_sha256 == SYSTEM_INSTRUCTION_SHA256
    assert record.rendered_user_request == rendered
    assert "comparison_context" not in json.loads(rendered)
    assert record.request_sha256 == _sha256(rendered)
    assert record.historical_comparison_evidence_ids == ()
    assert record.comparison_context_chars == 0
    assert len(record.known_claim_ids) == 1


def test_arm_a_call_one_records_no_claims() -> None:
    request = _ablation_call1()
    reasoner = RecordingReasoner(_inner("A", [()]), arm="A")
    reasoner.begin_step(2)

    reasoner.propose(request)

    (record,) = reasoner.records
    assert record.known_claim_ids == ()
    assert len(record.known_address_ids) == 1
    assert record.citable_evidence_ids == ("EV-2",)


@pytest.mark.parametrize(
    ("arm", "policy", "prompt_sha", "include"),
    [
        ("F", CONTRASTIVE_POLICY_VERSION, CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256, True),
        ("R", CONTRASTIVE_POLICY_VERSION, CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256, True),
        ("A", POLICY_VERSION, SYSTEM_INSTRUCTION_SHA256, False),
    ],
)
def test_arm_configuration_is_exposed(
    arm: str, policy: str, prompt_sha: str, include: bool
) -> None:
    reasoner = RecordingReasoner(_inner(arm, []), arm=arm)  # type: ignore[arg-type]
    assert reasoner.arm == arm
    assert reasoner.policy_version == policy
    assert reasoner.system_prompt_sha256 == prompt_sha
    assert reasoner.include_comparison_context is include


# --- delegation -------------------------------------------------------------------


def test_propose_delegates_the_same_request_and_returns_the_inner_result_unchanged() -> None:
    request = _contrastive_call1()
    candidate = SemanticCandidate(
        candidate_id="CAND-OUT",
        subject="SUBJECT_BETA",
        facet="FACET_BETA",
        scope=(SCOPE,),
        evidence_ids=("EV-2",),
    )
    batch = (_judgment("J-out", CreateAddressProposal(candidate=candidate), "EV-2"),)
    inner = ScriptedReasoner([batch])
    reasoner = RecordingReasoner(inner, arm="F")
    reasoner.begin_step(2)

    result = reasoner.propose(request)

    assert result is batch
    assert inner.requests == [request]
    assert inner.requests[0] is request


def test_record_is_appended_before_delegation_and_kept_when_inner_raises() -> None:
    request = _contrastive_call1()
    inner = ScriptedReasoner([RuntimeError("PROVIDER_FAILURE_ALPHA")])
    reasoner = RecordingReasoner(inner, arm="F")
    reasoner.begin_step(2)

    with pytest.raises(RuntimeError, match="PROVIDER_FAILURE_ALPHA"):
        reasoner.propose(request)

    assert len(reasoner.records) == 1
    assert reasoner.records[0].call_number == 1
    assert inner.requests == [request]


def test_fingerprint_delegates_to_inner() -> None:
    inner = ScriptedReasoner([])
    reasoner = RecordingReasoner(inner, arm="F")
    assert reasoner.fingerprint == inner.fingerprint == FR_FINGERPRINT


def test_inner_receipts_and_draft_payloads_pass_through_when_present() -> None:
    inner = ReasonerWithEconomics([])
    reasoner = RecordingReasoner(inner, arm="F")
    assert reasoner.inner is inner
    assert reasoner.receipts == ("RECEIPT_ALPHA",)
    assert reasoner.draft_payloads == ("PAYLOAD_ALPHA",)


def test_receipts_and_draft_payloads_are_empty_for_a_reasoner_without_them() -> None:
    inner = _inner("A", [])
    reasoner = RecordingReasoner(inner, arm="A")
    assert reasoner.inner is inner
    assert reasoner.receipts == ()
    assert reasoner.draft_payloads == ()


# --- observed policy identity at construction (whole-branch review Finding 2) -------


class _ClassAttributeReasoner(ScriptedReasoner):
    """A fake shaped like the real adapters: class-level prompt and context flag."""

    policy_version = CONTRASTIVE_POLICY_VERSION
    system_instruction = CONTRASTIVE_SYSTEM_INSTRUCTION
    include_comparison_context = True


class _HistoricalClassAttributeReasoner(ScriptedReasoner):
    policy_version = POLICY_VERSION
    system_instruction = SYSTEM_INSTRUCTION
    include_comparison_context = False


class _TamperedPromptReasoner(_ClassAttributeReasoner):
    system_instruction = "a different system instruction"


class _NoContextReasoner(_ClassAttributeReasoner):
    include_comparison_context = False


@pytest.mark.parametrize(
    ("arm", "wrong"),
    [("F", A_FINGERPRINT), ("R", A_FINGERPRINT), ("A", FR_FINGERPRINT)],
)
def test_wrapping_a_reasoner_whose_fingerprint_policy_is_not_the_arms_is_refused(
    arm: str, wrong: ReasonerFingerprint
) -> None:
    inner = ScriptedReasoner([()], fingerprint=wrong)

    with pytest.raises(RuntimeError, match="REASONER_IDENTITY_MISMATCH") as info:
        RecordingReasoner(inner, arm=arm)  # type: ignore[arg-type]

    assert wrong.policy_version in str(info.value)
    assert inner.requests == []


def test_wrapping_a_9p_v4_fingerprinted_reasoner_as_arm_f_never_records_the_9p2_policy() -> None:
    inner = ScriptedReasoner(
        [()],
        fingerprint=ReasonerFingerprint(
            provider="xai", model="grok-4.6", policy_version="intent-v2-9p-v4"
        ),
    )

    with pytest.raises(RuntimeError, match="REASONER_IDENTITY_MISMATCH"):
        RecordingReasoner(inner, arm="F")


def test_class_level_prompt_and_context_flag_are_observed_when_present() -> None:
    accepted = RecordingReasoner(_ClassAttributeReasoner([()]), arm="F")
    assert accepted.system_prompt_sha256 == CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256
    historical = RecordingReasoner(
        _HistoricalClassAttributeReasoner([()], fingerprint=A_FINGERPRINT), arm="A"
    )
    assert historical.system_prompt_sha256 == SYSTEM_INSTRUCTION_SHA256

    with pytest.raises(RuntimeError, match="REASONER_IDENTITY_MISMATCH") as prompt:
        RecordingReasoner(_TamperedPromptReasoner([()]), arm="F")
    assert "system_instruction" in str(prompt.value)

    with pytest.raises(RuntimeError, match="REASONER_IDENTITY_MISMATCH") as flag:
        RecordingReasoner(_NoContextReasoner([()]), arm="R")
    assert "include_comparison_context" in str(flag.value)

    with pytest.raises(RuntimeError, match="REASONER_IDENTITY_MISMATCH"):
        RecordingReasoner(_ClassAttributeReasoner([()], fingerprint=A_FINGERPRINT), arm="A")


def test_a_fake_without_class_level_prompt_attributes_is_accepted_on_its_fingerprint() -> None:
    reasoner = RecordingReasoner(_inner("F", [()]), arm="F")
    assert not hasattr(type(reasoner.inner), "system_instruction")
    assert reasoner.policy_version == CONTRASTIVE_POLICY_VERSION


# --- call counting ----------------------------------------------------------------


def test_third_call_within_a_step_is_refused_before_delegation() -> None:
    request = _contrastive_call1()
    inner = ScriptedReasoner([(), (), ()])
    reasoner = RecordingReasoner(inner, arm="F")
    reasoner.begin_step(1)
    reasoner.propose(request)
    reasoner.propose(request)

    with pytest.raises(RuntimeError, match="THIRD_CALL_REFUSED"):
        reasoner.propose(request)

    assert len(inner.requests) == 2
    assert len(reasoner.records) == 2
    assert [r.call_number for r in reasoner.records] == [1, 2]


def test_begin_step_resets_the_call_counter_and_stamps_t() -> None:
    request = _contrastive_call1()
    inner = ScriptedReasoner([(), (), (), ()])
    reasoner = RecordingReasoner(inner, arm="R")

    reasoner.begin_step(1)
    reasoner.propose(request)
    reasoner.propose(request)
    reasoner.begin_step(2)
    reasoner.propose(request)
    reasoner.propose(request)

    assert [(r.t, r.call_number) for r in reasoner.records] == [(1, 1), (1, 2), (2, 1), (2, 2)]
    assert isinstance(reasoner.records, tuple)


def test_propose_before_begin_step_is_refused_before_delegation() -> None:
    request = _contrastive_call1()
    inner = ScriptedReasoner([()])
    reasoner = RecordingReasoner(inner, arm="F")

    with pytest.raises(RuntimeError, match="NO_STEP_BEGUN"):
        reasoner.propose(request)

    assert inner.requests == []
    assert reasoner.records == ()


def test_records_property_returns_a_snapshot_tuple() -> None:
    request = _contrastive_call1()
    reasoner = RecordingReasoner(ScriptedReasoner([(), ()]), arm="F")
    reasoner.begin_step(1)
    reasoner.propose(request)
    before = reasoner.records
    reasoner.propose(request)
    assert len(before) == 1
    assert len(reasoner.records) == 2


# --- request-path hygiene ---------------------------------------------------------


def test_records_source_does_not_import_expectations() -> None:
    source = Path(records_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "expectations" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "expectations" not in module
            for alias in node.names:
                assert "expectations" not in alias.name

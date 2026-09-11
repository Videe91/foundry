"""``SUPPORTS_CLAIM`` domain contract (plan Task 2; spec §11, §12).

A ``SUPPORTS_CLAIM`` judgment says: new immutable evidence semantically supports an
already-existing immutable claim. The claim is never mutated; the durable effect is an
append-only ``ClaimSupportRecord`` that is supersedable like any judgment. No new event
type exists for it — it travels in ``SemanticJudgmentPayload`` like every other kind.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.domain.admission import AdmissionPolicy
from foundry.domain.events import EventEnvelope, EventType, SemanticJudgmentPayload, parse_event
from foundry.domain.semantic_judgment import (
    DistinctProposal,
    EquivalentProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
    agrees,
    contradicts,
    proposal_signature,
)
from foundry.domain.semantic_state import ClaimSupportRecord, SemanticState

T0 = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="p1")


def _support(
    claim_id: str = "CLM-1", evidence_ids: tuple[str, ...] = ("EV-2",)
) -> SupportsClaimProposal:
    return SupportsClaimProposal(claim_id=claim_id, evidence_ids=evidence_ids)


def _judgment(proposal: JudgmentProposal, *, judgment_id: str = "JDG-1") -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id="PROJ-1",
        proposal=proposal,
        visible_evidence_ids=("EV-1", "EV-2"),
        compared_object_ids=("CLM-1",),
        rationale="EV-2 restates the retention requirement already claimed by CLM-1.",
        reasoner=MODEL_A,
        invocation_id="INV-1",
        proposed_at=T0,
    )


# --- proposal shape ---------------------------------------------------------


def test_supports_claim_proposal_requires_at_least_one_evidence_id() -> None:
    assert JudgmentKind.SUPPORTS_CLAIM == "SUPPORTS_CLAIM"

    proposal = _support(evidence_ids=("EV-2", "EV-3"))
    assert proposal.kind is JudgmentKind.SUPPORTS_CLAIM
    assert proposal.claim_id == "CLM-1"
    assert proposal.evidence_ids == ("EV-2", "EV-3")

    with pytest.raises(ValidationError):
        SupportsClaimProposal(claim_id="CLM-1", evidence_ids=())
    with pytest.raises(ValidationError):
        SupportsClaimProposal(claim_id="", evidence_ids=("EV-2",))


def test_supports_claim_round_trips_through_the_discriminated_union() -> None:
    judgment = _judgment(_support())

    restored = SemanticJudgment.model_validate(judgment.model_dump(mode="json"))

    assert restored == judgment
    assert isinstance(restored.proposal, SupportsClaimProposal)
    assert restored.kind is JudgmentKind.SUPPORTS_CLAIM
    assert restored.proposal.evidence_ids == ("EV-2",)


# --- signature --------------------------------------------------------------


def test_supports_claim_signature_is_order_insensitive_over_evidence() -> None:
    forward = _support(evidence_ids=("EV-2", "EV-3"))
    backward = _support(evidence_ids=("EV-3", "EV-2"))

    assert proposal_signature(forward) == ("SUPPORT", "CLM-1", "EV-2", "EV-3")
    assert proposal_signature(forward) == proposal_signature(backward)
    assert proposal_signature(forward) != proposal_signature(_support(claim_id="CLM-2"))
    assert proposal_signature(forward) != proposal_signature(_support(evidence_ids=("EV-2",)))


# --- admission policy -------------------------------------------------------


def test_supports_claim_is_not_a_material_kind_by_default() -> None:
    assert JudgmentKind.SUPPORTS_CLAIM not in AdmissionPolicy().material_kinds


# --- durable record ---------------------------------------------------------


def test_claim_support_record_shape_and_state_default() -> None:
    record = ClaimSupportRecord(
        judgment_id="JDG-1",
        claim_id="CLM-1",
        evidence_ids=("EV-2",),
        recorded_by_event_id="EVT-9",
    )

    assert record.judgment_id == "JDG-1"
    assert record.claim_id == "CLM-1"
    assert record.evidence_ids == ("EV-2",)
    assert record.recorded_by_event_id == "EVT-9"
    assert SemanticState().claim_supports == ()

    with pytest.raises(ValidationError):
        ClaimSupportRecord(
            judgment_id="JDG-1", claim_id="CLM-1", evidence_ids=(), recorded_by_event_id="EVT-9"
        )
    with pytest.raises(ValidationError):
        ClaimSupportRecord(
            judgment_id="", claim_id="CLM-1", evidence_ids=("EV-2",), recorded_by_event_id="EVT-9"
        )
    with pytest.raises(ValidationError):
        ClaimSupportRecord(
            judgment_id="JDG-1", claim_id="", evidence_ids=("EV-2",), recorded_by_event_id="EVT-9"
        )
    with pytest.raises(ValidationError):
        ClaimSupportRecord(
            judgment_id="JDG-1", claim_id="CLM-1", evidence_ids=("EV-2",), recorded_by_event_id=""
        )


# --- events -----------------------------------------------------------------


def test_event_with_supports_claim_judgment_parses() -> None:
    event = EventEnvelope(
        event_id="EVT-1",
        project_id="PROJ-1",
        event_type=EventType.SEMANTIC_JUDGMENT_RECORDED,
        occurred_at=T0,
        payload=SemanticJudgmentPayload(judgment=_judgment(_support())),
    )

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert isinstance(restored.payload, SemanticJudgmentPayload)
    assert isinstance(restored.payload.judgment.proposal, SupportsClaimProposal)


# --- agreement / contradiction ----------------------------------------------


def test_agrees_and_contradicts_unaffected() -> None:
    forward = _support(evidence_ids=("EV-2", "EV-3"))
    backward = _support(evidence_ids=("EV-3", "EV-2"))

    assert agrees(forward, backward)
    assert not agrees(forward, _support(evidence_ids=("EV-2",)))
    assert not agrees(forward, _support(claim_id="CLM-2", evidence_ids=("EV-2", "EV-3")))

    others: tuple[JudgmentProposal, ...] = (
        backward,
        SupersedeProposal(target_judgment_id="JDG-0", reason="stale"),
        EquivalentProposal(address_a="ADDR-1", address_b="ADDR-2"),
        DistinctProposal(address_a="ADDR-1", address_b="ADDR-2"),
    )
    for other in others:
        assert not contradicts(forward, other)
        assert not contradicts(other, forward)

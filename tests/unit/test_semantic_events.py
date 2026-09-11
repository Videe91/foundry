from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from foundry.domain.common import Authority, SourceKind
from foundry.domain.events import (
    EVENT_PAYLOAD_TYPES,
    DerivationPayload,
    EventEnvelope,
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    UserStatedIntentPayload,
    parse_event,
)
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

OCCURRED_AT = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")


def _evidence(*, project_id: str = "PROJ-1") -> EvidenceItem:
    return evidence_item(
        evidence_id="EV-1",
        project_id=project_id,
        source_kind=SourceKind.HUMAN,
        source_ref="human://alice",
        content="Audit records must be retained for seven years.",
        observed_at=OCCURRED_AT,
    )


def _judgment(proposal: JudgmentProposal, *, project_id: str = "PROJ-1") -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id="JDG-1",
        project_id=project_id,
        proposal=proposal,
        visible_evidence_ids=("EV-1",),
        rationale="EV-1 states a retention period for audit records.",
        reasoner=MODEL_A,
        invocation_id="INV-1",
        proposed_at=OCCURRED_AT,
    )


def _create_proposal() -> CreateAddressProposal:
    return CreateAddressProposal(
        candidate=SemanticCandidate(
            candidate_id="CAND-1",
            subject="audit records",
            facet="retention period",
            scope=("compliance",),
            evidence_ids=("EV-1",),
        )
    )


def _claim_proposal() -> AssertClaimProposal:
    return AssertClaimProposal(
        address_id="ADDR-1",
        predicate="retention_period",
        value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
        evidence_ids=("EV-1",),
        authority=Authority.OBSERVED,
    )


def _envelope(event_type: EventType, payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id="EVT-1",
        project_id="PROJ-1",
        event_type=event_type,
        occurred_at=OCCURRED_AT,
        payload=payload,  # type: ignore[arg-type]
    )


# --- event types and payload registry -------------------------------------


def test_new_event_types_exist_and_are_registered() -> None:
    assert EVENT_PAYLOAD_TYPES[EventType.EVIDENCE_INGESTED] is EvidencePayload
    assert EVENT_PAYLOAD_TYPES[EventType.SEMANTIC_JUDGMENT_RECORDED] is SemanticJudgmentPayload
    assert EVENT_PAYLOAD_TYPES[EventType.SEMANTIC_ADMISSION_DECIDED] is SemanticAdmissionPayload
    assert EVENT_PAYLOAD_TYPES[EventType.DERIVATION_RECORDED] is DerivationPayload


def test_every_event_type_has_a_payload_type() -> None:
    assert set(EVENT_PAYLOAD_TYPES) == set(EventType)


# --- envelope validation ---------------------------------------------------


def test_evidence_ingested_round_trips_through_parse_event() -> None:
    event = _envelope(EventType.EVIDENCE_INGESTED, EvidencePayload(evidence=_evidence()))

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert isinstance(restored.payload, EvidencePayload)
    assert restored.payload.evidence.source_kind is SourceKind.HUMAN


def test_semantic_judgment_recorded_round_trips_with_decimal_claim_value() -> None:
    judgment = _judgment(_claim_proposal())
    event = _envelope(
        EventType.SEMANTIC_JUDGMENT_RECORDED, SemanticJudgmentPayload(judgment=judgment)
    )

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert isinstance(restored.payload, SemanticJudgmentPayload)
    proposal = restored.payload.judgment.proposal
    assert isinstance(proposal, AssertClaimProposal)
    assert proposal.value.quantity == Decimal("7")


def test_semantic_judgment_recorded_round_trips_create_address_proposal() -> None:
    judgment = _judgment(_create_proposal())
    event = _envelope(
        EventType.SEMANTIC_JUDGMENT_RECORDED, SemanticJudgmentPayload(judgment=judgment)
    )

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert isinstance(restored.payload, SemanticJudgmentPayload)
    assert isinstance(restored.payload.judgment.proposal, CreateAddressProposal)


def test_semantic_admission_decided_round_trips() -> None:
    payload = SemanticAdmissionPayload(
        judgment_id="JDG-1",
        route=AdmissionRoute.APPLY,
        reasons=("LOW_RISK",),
        corroborating_judgment_ids=("JDG-0",),
    )
    event = _envelope(EventType.SEMANTIC_ADMISSION_DECIDED, payload)

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert isinstance(restored.payload, SemanticAdmissionPayload)
    assert restored.payload.route is AdmissionRoute.APPLY


def test_semantic_admission_corroborating_ids_default_empty() -> None:
    payload = SemanticAdmissionPayload(
        judgment_id="JDG-1", route=AdmissionRoute.REJECT, reasons=("STRUCTURAL:missing",)
    )
    assert payload.corroborating_judgment_ids == ()


def test_derivation_recorded_round_trips() -> None:
    event = _envelope(
        EventType.DERIVATION_RECORDED, DerivationPayload(child_id="D-1", parent_id="JDG-1")
    )

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert isinstance(restored.payload, DerivationPayload)


def test_derivation_payload_requires_non_empty_ids() -> None:
    with pytest.raises(ValidationError):
        DerivationPayload(child_id="", parent_id="JDG-1")
    with pytest.raises(ValidationError):
        DerivationPayload(child_id="D-1", parent_id="")


def test_semantic_admission_requires_non_empty_judgment_id() -> None:
    with pytest.raises(ValidationError):
        SemanticAdmissionPayload(judgment_id="", route=AdmissionRoute.APPLY, reasons=())


@pytest.mark.parametrize(
    "event_type",
    [
        EventType.EVIDENCE_INGESTED,
        EventType.SEMANTIC_JUDGMENT_RECORDED,
        EventType.SEMANTIC_ADMISSION_DECIDED,
        EventType.DERIVATION_RECORDED,
    ],
)
def test_new_event_types_reject_wrong_payload(event_type: EventType) -> None:
    with pytest.raises(ValidationError, match="requires"):
        _envelope(event_type, UserStatedIntentPayload(text="hello", actor_id="alice"))


def test_existing_event_type_rejects_new_payload() -> None:
    with pytest.raises(ValidationError, match="requires"):
        _envelope(EventType.USER_STATED_INTENT, EvidencePayload(evidence=_evidence()))


# --- project mismatch ------------------------------------------------------


def test_evidence_ingested_rejects_project_mismatch() -> None:
    with pytest.raises(ValidationError, match="does not match event project"):
        _envelope(
            EventType.EVIDENCE_INGESTED, EvidencePayload(evidence=_evidence(project_id="PROJ-2"))
        )


def test_semantic_judgment_recorded_rejects_project_mismatch() -> None:
    with pytest.raises(ValidationError, match="does not match event project"):
        _envelope(
            EventType.SEMANTIC_JUDGMENT_RECORDED,
            SemanticJudgmentPayload(judgment=_judgment(_create_proposal(), project_id="PROJ-2")),
        )

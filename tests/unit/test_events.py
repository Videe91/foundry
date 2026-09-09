from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.domain.common import Authority, Materiality, Provenance, RiskLevel, SourceKind
from foundry.domain.events import (
    EVENT_PAYLOAD_TYPES,
    GENERIC_SEMANTIC_KINDS,
    SPECIALIZED_SEMANTIC_KIND_BY_EVENT,
    EventEnvelope,
    EventType,
    GapPayload,
    JobPayload,
    SemanticObjectPayload,
    SourceReferencePayload,
    StoredEvent,
    UserStatedIntentPayload,
    parse_event,
)
from foundry.domain.gaps import Gap, GapKind
from foundry.domain.jobs import ExecutorClass, Job, JobType
from foundry.domain.semantic import (
    Amendment,
    AuthorityRecord,
    Claim,
    Intent,
    Metric,
    Requirement,
    SemanticKind,
)

OCCURRED_AT = datetime(2026, 9, 9, tzinfo=UTC)


def _provenance() -> Provenance:
    return Provenance(
        source_kind=SourceKind.CODE,
        source_ref="repo://svc/retry.py#L1-L5",
        source_event_ids=("EVT-1",),
    )


def _claim(*, project_id: str = "PROJ-1") -> Claim:
    return Claim(
        id="CLAIM-1",
        project_id=project_id,
        statement="Retries are three.",
        authority=Authority.INFERRED,
        confidence=0.9,
        provenance=_provenance(),
        created_at=OCCURRED_AT,
    )


def _requirement() -> Requirement:
    return Requirement(
        id="REQ-1",
        project_id="PROJ-1",
        statement="Regional loss must not materially interrupt service.",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(
            source_kind=SourceKind.HUMAN,
            source_ref="human://owner",
            source_event_ids=("EVT-3",),
        ),
        created_at=OCCURRED_AT,
        materiality=Materiality.HIGH,
        requires_metric=True,
        requires_verification=True,
    )


def _gap(*, project_id: str = "PROJ-1", kind: GapKind = GapKind.AMBIGUITY) -> Gap:
    return Gap(
        id="GAP-1",
        project_id=project_id,
        kind=kind,
        description="The term fast has no threshold.",
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=("REQ-1",),
        blocking=True,
    )


def _job(*, project_id: str = "PROJ-1") -> Job:
    return Job(
        id="JOB-1",
        project_id=project_id,
        gap_id="GAP-1",
        job_type=JobType.AMBIGUITY_ANALYSIS,
        target_object_ids=("REQ-1",),
        output_schema_ref="foundry://schemas/ambiguity-result/v1",
        risk=RiskLevel.HIGH,
        max_context_tokens=8_000,
        permitted_executors=(ExecutorClass.CHEAP_MODEL,),
        budget_usd=0.25,
        verification_requirement="Must return a schema-valid ambiguity classification.",
    )


def test_event_round_trip_preserves_typed_semantic_payload() -> None:
    claim = _claim()
    event = EventEnvelope(
        event_id="EVT-2",
        project_id="PROJ-1",
        event_type=EventType.CLAIM_INFERRED,
        occurred_at=OCCURRED_AT,
        payload=SemanticObjectPayload(object=claim),
    )

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert isinstance(restored.payload, SemanticObjectPayload)
    assert isinstance(restored.payload.object, Claim)


def test_every_event_type_has_exactly_one_payload_mapping() -> None:
    assert set(EVENT_PAYLOAD_TYPES) == set(EventType)
    assert len(EVENT_PAYLOAD_TYPES) == len(EventType)


def test_wrong_payload_class_for_event_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_id="EVT-3",
            project_id="PROJ-1",
            event_type=EventType.CLAIM_INFERRED,
            occurred_at=OCCURRED_AT,
            payload=UserStatedIntentPayload(text="Users should log in.", actor_id="OWNER"),
        )


def test_claim_inferred_rejects_non_claim_semantic_object() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_id="EVT-4",
            project_id="PROJ-1",
            event_type=EventType.CLAIM_INFERRED,
            occurred_at=OCCURRED_AT,
            payload=SemanticObjectPayload(object=_requirement()),
        )


def test_ambiguity_detected_rejects_non_ambiguity_gap() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_id="EVT-5",
            project_id="PROJ-1",
            event_type=EventType.AMBIGUITY_DETECTED,
            occurred_at=OCCURRED_AT,
            payload=GapPayload(gap=_gap(kind=GapKind.CONTRADICTION)),
        )


def test_embedded_semantic_object_project_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_id="EVT-6",
            project_id="PROJ-A",
            event_type=EventType.CLAIM_INFERRED,
            occurred_at=OCCURRED_AT,
            payload=SemanticObjectPayload(object=_claim(project_id="PROJ-B")),
        )


def test_embedded_gap_project_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_id="EVT-7",
            project_id="PROJ-A",
            event_type=EventType.GAP_RECORDED,
            occurred_at=OCCURRED_AT,
            payload=GapPayload(gap=_gap(project_id="PROJ-B")),
        )


def test_embedded_job_project_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_id="EVT-8",
            project_id="PROJ-A",
            event_type=EventType.JOB_CREATED,
            occurred_at=OCCURRED_AT,
            payload=JobPayload(job=_job(project_id="PROJ-B")),
        )


def test_arbitrary_raw_payload_dictionary_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_event(
            {
                "event_id": "EVT-9",
                "project_id": "PROJ-1",
                "event_type": EventType.CLAIM_INFERRED.value,
                "occurred_at": OCCURRED_AT.isoformat(),
                "payload": {"not": "a typed payload"},
            }
        )


def test_stored_event_sequence_zero_is_rejected() -> None:
    event = EventEnvelope(
        event_id="EVT-10",
        project_id="PROJ-1",
        event_type=EventType.CLAIM_INFERRED,
        occurred_at=OCCURRED_AT,
        payload=SemanticObjectPayload(object=_claim()),
    )
    with pytest.raises(ValidationError):
        StoredEvent(sequence=0, event=event)


def test_event_models_are_immutable() -> None:
    event = EventEnvelope(
        event_id="EVT-11",
        project_id="PROJ-1",
        event_type=EventType.CLAIM_INFERRED,
        occurred_at=OCCURRED_AT,
        payload=SemanticObjectPayload(object=_claim()),
    )
    with pytest.raises(ValidationError):
        event.event_id = "EVT-OTHER"


def test_source_reference_payload_rejects_empty_reference() -> None:
    with pytest.raises(ValidationError):
        SourceReferencePayload(source_ref="")


def test_event_raw_json_round_trip_remains_equal() -> None:
    event = EventEnvelope(
        event_id="EVT-12",
        project_id="PROJ-1",
        event_type=EventType.CLAIM_INFERRED,
        occurred_at=OCCURRED_AT,
        payload=SemanticObjectPayload(object=_claim()),
    )

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert restored.model_dump(mode="json") == event.model_dump(mode="json")


def test_semantic_object_recorded_exists() -> None:
    assert EventType.SEMANTIC_OBJECT_RECORDED is EventType("SEMANTIC_OBJECT_RECORDED")
    assert EVENT_PAYLOAD_TYPES[EventType.SEMANTIC_OBJECT_RECORDED] is SemanticObjectPayload


def test_every_semantic_kind_has_exactly_one_approved_event_path() -> None:
    specialized_kinds = frozenset(SPECIALIZED_SEMANTIC_KIND_BY_EVENT.values())

    assert GENERIC_SEMANTIC_KINDS.isdisjoint(specialized_kinds)
    assert GENERIC_SEMANTIC_KINDS | specialized_kinds == frozenset(SemanticKind)


def _intent() -> Intent:
    return Intent(
        id="INTENT-1",
        project_id="PROJ-1",
        mission="Keep payments available after regional loss.",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=_provenance(),
        created_at=OCCURRED_AT,
    )


def _authority_record() -> AuthorityRecord:
    return AuthorityRecord(
        id="AUTH-1",
        project_id="PROJ-1",
        subject_id="REQ-1",
        authorized_by="OWNER",
        rationale="Owner authorized the availability requirement.",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=_provenance(),
        created_at=OCCURRED_AT,
    )


def _amendment() -> Amendment:
    return Amendment(
        id="AMD-1",
        project_id="PROJ-1",
        subject_id="REQ-1",
        change_statement="Raise the availability threshold.",
        rationale="New evidence about regional loss.",
        authority=Authority.PROPOSED,
        confidence=0.8,
        provenance=_provenance(),
        created_at=OCCURRED_AT,
    )


def _metric() -> Metric:
    return Metric(
        id="METRIC-1",
        project_id="PROJ-1",
        name="regional-interruption",
        definition="Service interruption after loss of one region.",
        target="below authorized threshold",
        authority=Authority.PROPOSED,
        confidence=0.7,
        provenance=_provenance(),
        created_at=OCCURRED_AT,
    )


def test_semantic_object_recorded_round_trips_generic_kinds() -> None:
    for semantic_object in (_intent(), _authority_record(), _amendment()):
        event = EventEnvelope(
            event_id=f"EVT-{semantic_object.id}",
            project_id="PROJ-1",
            event_type=EventType.SEMANTIC_OBJECT_RECORDED,
            occurred_at=OCCURRED_AT,
            payload=SemanticObjectPayload(object=semantic_object),
        )
        restored = parse_event(event.model_dump(mode="json"))
        assert restored == event
        assert isinstance(restored.payload, SemanticObjectPayload)
        assert restored.payload.object == semantic_object


def test_semantic_object_recorded_rejects_specialized_kinds() -> None:
    for semantic_object in (_requirement(), _claim(), _metric()):
        with pytest.raises(ValidationError):
            EventEnvelope(
                event_id=f"EVT-{semantic_object.id}",
                project_id="PROJ-1",
                event_type=EventType.SEMANTIC_OBJECT_RECORDED,
                occurred_at=OCCURRED_AT,
                payload=SemanticObjectPayload(object=semantic_object),
            )

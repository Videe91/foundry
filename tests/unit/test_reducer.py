from datetime import UTC, datetime

import pytest

from foundry.application.reducer import reduce_event
from foundry.application.replay import replay
from foundry.domain.common import Authority, Materiality, Provenance, RiskLevel, SourceKind
from foundry.domain.events import (
    ClosurePayload,
    EventEnvelope,
    EventType,
    GapPayload,
    GapResolvedPayload,
    JobPayload,
    JobStatusChangedPayload,
    SemanticObjectPayload,
    StoredEvent,
)
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.jobs import ExecutorClass, Job, JobStatus, JobType
from foundry.domain.semantic import Claim
from foundry.domain.state import IntentState

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def claim() -> Claim:
    return Claim(
        id="CLAIM-1",
        project_id="PROJ-1",
        statement="Retries are three.",
        authority=Authority.INFERRED,
        confidence=0.9,
        provenance=Provenance(
            source_kind=SourceKind.CODE,
            source_ref="repo://svc/retry.py#L1-L5",
            source_event_ids=("EVT-1",),
        ),
        created_at=NOW,
    )


def envelope(event_id: str, event_type: EventType, payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        project_id="PROJ-1",
        event_type=event_type,
        occurred_at=NOW,
        payload=payload,
    )


def test_replay_is_deterministic() -> None:
    event = StoredEvent(
        sequence=1,
        event=envelope(
            "EVT-2",
            EventType.CLAIM_INFERRED,
            SemanticObjectPayload(object=claim()),
        ),
    )

    first = replay("PROJ-1", [event])
    second = replay("PROJ-1", [event])

    assert first == second
    assert first.objects["CLAIM-1"] == claim()
    assert first.last_sequence == 1
    assert first.revision == 1
    assert first.source_events == ("EVT-2",)


def test_reducer_rejects_non_contiguous_sequence() -> None:
    state = IntentState(project_id="PROJ-1")
    event = StoredEvent(
        sequence=2,
        event=envelope(
            "EVT-2",
            EventType.CLAIM_INFERRED,
            SemanticObjectPayload(object=claim()),
        ),
    )

    with pytest.raises(ValueError, match="sequence"):
        reduce_event(state, event)


def test_reducer_rejects_event_for_another_project() -> None:
    state = IntentState(project_id="PROJ-2")
    event = StoredEvent(
        sequence=1,
        event=envelope(
            "EVT-2",
            EventType.CLAIM_INFERRED,
            SemanticObjectPayload(object=claim()),
        ),
    )

    with pytest.raises(ValueError, match="project"):
        reduce_event(state, event)


def test_reducer_records_and_resolves_gap() -> None:
    gap = Gap(
        id="GAP-1",
        project_id="PROJ-1",
        kind=GapKind.AMBIGUITY,
        description="Fast is undefined.",
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=("CLAIM-1",),
        blocking=True,
    )
    recorded = StoredEvent(
        sequence=1,
        event=envelope("EVT-G1", EventType.GAP_RECORDED, GapPayload(gap=gap)),
    )
    resolved = StoredEvent(
        sequence=2,
        event=envelope(
            "EVT-G2",
            EventType.GAP_RESOLVED,
            GapResolvedPayload(gap_id="GAP-1", resolution_event_id="EVT-G2"),
        ),
    )

    state = replay("PROJ-1", [recorded, resolved])

    assert state.gaps["GAP-1"].status is GapStatus.RESOLVED
    assert state.gaps["GAP-1"].resolution_event_id == "EVT-G2"


def test_reducer_records_and_updates_job_status() -> None:
    job = Job(
        id="JOB-1",
        project_id="PROJ-1",
        gap_id="GAP-1",
        job_type=JobType.AMBIGUITY_ANALYSIS,
        output_schema_ref="foundry://schemas/ambiguity-result/v1",
        risk=RiskLevel.HIGH,
        max_context_tokens=8000,
        permitted_executors=(ExecutorClass.CHEAP_MODEL,),
        budget_usd=0.25,
        verification_requirement="Schema-valid result.",
    )
    created = StoredEvent(
        sequence=1,
        event=envelope("EVT-J1", EventType.JOB_CREATED, JobPayload(job=job)),
    )
    updated = StoredEvent(
        sequence=2,
        event=envelope(
            "EVT-J2",
            EventType.JOB_STATUS_CHANGED,
            JobStatusChangedPayload(job_id="JOB-1", status=JobStatus.RUNNING, attempt=1),
        ),
    )

    state = replay("PROJ-1", [created, updated])

    assert state.jobs["JOB-1"].status is JobStatus.RUNNING
    assert state.jobs["JOB-1"].attempt == 1


def test_reducer_closes_and_reopens_scope() -> None:
    closed = StoredEvent(
        sequence=1,
        event=envelope(
            "EVT-C1",
            EventType.INTENT_CLOSURE_REACHED,
            ClosurePayload(scope="core", package_revision=1),
        ),
    )
    reopened = StoredEvent(
        sequence=2,
        event=EventEnvelope(
            event_id="EVT-C2",
            project_id="PROJ-1",
            event_type=EventType.INTENT_REOPENED,
            occurred_at=NOW,
            payload={"scope": "core", "reason": "Requirement changed."},
        ),
    )

    state_after_close = replay("PROJ-1", [closed])
    state_after_reopen = replay("PROJ-1", [closed, reopened])

    assert state_after_close.closed_scopes == {"core": 1}
    assert state_after_reopen.closed_scopes == {}

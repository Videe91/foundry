from __future__ import annotations

from foundry.domain.common import LifecycleStatus
from foundry.domain.events import (
    ClosurePayload,
    EventType,
    GapPayload,
    GapResolvedPayload,
    GapWaivedPayload,
    JobPayload,
    JobStatusChangedPayload,
    ReopenPayload,
    SemanticObjectPayload,
    StoredEvent,
    SupersessionPayload,
)
from foundry.domain.gaps import GapStatus
from foundry.domain.semantic import Requirement
from foundry.domain.state import IntentState


def reduce_event(state: IntentState, stored_event: StoredEvent) -> IntentState:
    event = stored_event.event
    if event.project_id != state.project_id:
        raise ValueError(
            f"event project {event.project_id} does not match state project {state.project_id}"
        )
    if stored_event.sequence != state.last_sequence + 1:
        raise ValueError(
            f"expected sequence {state.last_sequence + 1}, got {stored_event.sequence}"
        )

    objects = dict(state.objects)
    gaps = dict(state.gaps)
    jobs = dict(state.jobs)
    closed_scopes = dict(state.closed_scopes)

    match event.event_type:
        case (
            EventType.CLAIM_INFERRED
            | EventType.EVIDENCE_ATTACHED
            | EventType.CONFLICT_DETECTED
            | EventType.UNKNOWN_IDENTIFIED
            | EventType.HUMAN_DECISION_RECORDED
            | EventType.REQUIREMENT_CANONICALIZED
            | EventType.CONSTRAINT_DISCOVERED
            | EventType.ASSUMPTION_IDENTIFIED
            | EventType.RISK_IDENTIFIED
            | EventType.SUCCESS_METRIC_DEFINED
            | EventType.VERIFICATION_OBLIGATION_DEFINED
            | EventType.SEMANTIC_OBJECT_RECORDED
        ):
            payload = event.payload
            if not isinstance(payload, SemanticObjectPayload):
                raise ValueError(f"{event.event_type} requires SemanticObjectPayload")
            objects[payload.object.id] = payload.object
        case (
            EventType.USER_STATED_INTENT
            | EventType.DOCUMENT_ADDED
            | EventType.ARTIFACT_CONNECTED
            | EventType.RESEARCH_RESULT_RECEIVED
            | EventType.AMBIGUITY_DETECTED
        ):
            pass
        case EventType.GAP_RECORDED:
            payload = event.payload
            if not isinstance(payload, GapPayload):
                raise ValueError("GAP_RECORDED requires GapPayload")
            gaps[payload.gap.id] = payload.gap
        case EventType.GAP_RESOLVED:
            payload = event.payload
            if not isinstance(payload, GapResolvedPayload):
                raise ValueError("GAP_RESOLVED requires GapResolvedPayload")
            if payload.gap_id not in gaps:
                raise ValueError(f"unknown gap {payload.gap_id}")
            current_gap = gaps[payload.gap_id]
            gaps[payload.gap_id] = current_gap.model_copy(
                update={
                    "status": GapStatus.RESOLVED,
                    "resolution_event_id": event.event_id,
                }
            )
        case EventType.GAP_WAIVED:
            payload = event.payload
            if not isinstance(payload, GapWaivedPayload):
                raise ValueError("GAP_WAIVED requires GapWaivedPayload")
            if payload.gap_id not in gaps:
                raise ValueError(f"unknown gap {payload.gap_id}")
            current_gap = gaps[payload.gap_id]
            gaps[payload.gap_id] = current_gap.model_copy(
                update={
                    "status": GapStatus.WAIVED,
                    "resolution_event_id": event.event_id,
                }
            )
        case EventType.JOB_CREATED:
            payload = event.payload
            if not isinstance(payload, JobPayload):
                raise ValueError("JOB_CREATED requires JobPayload")
            jobs[payload.job.id] = payload.job
        case EventType.JOB_STATUS_CHANGED:
            payload = event.payload
            if not isinstance(payload, JobStatusChangedPayload):
                raise ValueError("JOB_STATUS_CHANGED requires JobStatusChangedPayload")
            if payload.job_id not in jobs:
                raise ValueError(f"unknown job {payload.job_id}")
            current_job = jobs[payload.job_id]
            jobs[payload.job_id] = current_job.model_copy(
                update={"status": payload.status, "attempt": payload.attempt}
            )
        case EventType.REQUIREMENT_SUPERSEDED:
            payload = event.payload
            if not isinstance(payload, SupersessionPayload):
                raise ValueError("REQUIREMENT_SUPERSEDED requires SupersessionPayload")
            old = objects.get(payload.object_id)
            replacement = objects.get(payload.superseded_by)
            if not isinstance(old, Requirement):
                raise ValueError(f"{payload.object_id} is not a Requirement in current state")
            if not isinstance(replacement, Requirement):
                raise ValueError(f"{payload.superseded_by} is not a Requirement in current state")
            objects[old.id] = old.model_copy(
                update={
                    "lifecycle": LifecycleStatus.SUPERSEDED,
                    "revision": old.revision + 1,
                }
            )
        case EventType.INTENT_CLOSURE_REACHED:
            payload = event.payload
            if not isinstance(payload, ClosurePayload):
                raise ValueError("INTENT_CLOSURE_REACHED requires ClosurePayload")
            closed_scopes[payload.scope] = payload.package_revision
        case EventType.INTENT_REOPENED:
            payload = event.payload
            if not isinstance(payload, ReopenPayload):
                raise ValueError("INTENT_REOPENED requires ReopenPayload")
            closed_scopes.pop(payload.scope, None)

    return IntentState(
        project_id=state.project_id,
        revision=state.revision + 1,
        last_sequence=stored_event.sequence,
        source_events=(*state.source_events, event.event_id),
        objects=objects,
        gaps=gaps,
        jobs=jobs,
        closed_scopes=closed_scopes,
    )

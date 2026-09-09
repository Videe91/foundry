from foundry.domain.common import LifecycleStatus
from foundry.domain.events import (
    ClosurePayload,
    EventType,
    GapPayload,
    GapResolvedPayload,
    JobPayload,
    JobStatusChangedPayload,
    ReopenPayload,
    SemanticObjectPayload,
    StoredEvent,
    SupersessionPayload,
)
from foundry.domain.gaps import GapStatus
from foundry.domain.state import IntentState


_SEMANTIC_OBJECT_EVENTS = {
    EventType.RESEARCH_RESULT_RECEIVED,
    EventType.CLAIM_INFERRED,
    EventType.EVIDENCE_ATTACHED,
    EventType.CONFLICT_DETECTED,
    EventType.UNKNOWN_IDENTIFIED,
    EventType.HUMAN_DECISION_RECORDED,
    EventType.REQUIREMENT_CANONICALIZED,
    EventType.CONSTRAINT_DISCOVERED,
    EventType.ASSUMPTION_IDENTIFIED,
    EventType.RISK_IDENTIFIED,
    EventType.SUCCESS_METRIC_DEFINED,
    EventType.VERIFICATION_OBLIGATION_DEFINED,
}


def reduce_event(state: IntentState, stored_event: StoredEvent) -> IntentState:
    event = stored_event.event
    if event.project_id != state.project_id:
        raise ValueError(
            f"event project {event.project_id} does not match state project {state.project_id}"
        )

    expected_sequence = state.last_sequence + 1
    if stored_event.sequence != expected_sequence:
        raise ValueError(
            f"event sequence {stored_event.sequence} is not contiguous; expected {expected_sequence}"
        )

    objects = dict(state.objects)
    gaps = dict(state.gaps)
    jobs = dict(state.jobs)
    closed_scopes = dict(state.closed_scopes)
    payload = event.payload

    if event.event_type in _SEMANTIC_OBJECT_EVENTS:
        if not isinstance(payload, SemanticObjectPayload):
            raise ValueError("semantic object event has invalid payload")
        objects[payload.object.id] = payload.object

    elif event.event_type in {EventType.GAP_RECORDED, EventType.AMBIGUITY_DETECTED}:
        if not isinstance(payload, GapPayload):
            raise ValueError("gap event has invalid payload")
        gaps[payload.gap.id] = payload.gap

    elif event.event_type is EventType.GAP_RESOLVED:
        if not isinstance(payload, GapResolvedPayload):
            raise ValueError("gap resolution event has invalid payload")
        gap = gaps.get(payload.gap_id)
        if gap is None:
            raise ValueError(f"cannot resolve unknown gap {payload.gap_id}")
        gaps[payload.gap_id] = gap.model_copy(
            update={
                "status": GapStatus.RESOLVED,
                "resolution_event_id": payload.resolution_event_id,
            }
        )

    elif event.event_type is EventType.JOB_CREATED:
        if not isinstance(payload, JobPayload):
            raise ValueError("job event has invalid payload")
        jobs[payload.job.id] = payload.job

    elif event.event_type is EventType.JOB_STATUS_CHANGED:
        if not isinstance(payload, JobStatusChangedPayload):
            raise ValueError("job status event has invalid payload")
        job = jobs.get(payload.job_id)
        if job is None:
            raise ValueError(f"cannot update unknown job {payload.job_id}")
        jobs[payload.job_id] = job.model_copy(
            update={"status": payload.status, "attempt": payload.attempt}
        )

    elif event.event_type is EventType.REQUIREMENT_SUPERSEDED:
        if not isinstance(payload, SupersessionPayload):
            raise ValueError("supersession event has invalid payload")
        semantic_object = objects.get(payload.object_id)
        if semantic_object is None:
            raise ValueError(f"cannot supersede unknown object {payload.object_id}")
        objects[payload.object_id] = semantic_object.model_copy(
            update={"lifecycle": LifecycleStatus.SUPERSEDED}
        )

    elif event.event_type is EventType.INTENT_CLOSURE_REACHED:
        if not isinstance(payload, ClosurePayload):
            raise ValueError("closure event has invalid payload")
        closed_scopes[payload.scope] = payload.package_revision

    elif event.event_type is EventType.INTENT_REOPENED:
        if not isinstance(payload, ReopenPayload):
            raise ValueError("reopen event has invalid payload")
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

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.gaps import Gap
from foundry.domain.jobs import Job, JobStatus
from foundry.domain.semantic import SemanticObject


class EventType(StrEnum):
    USER_STATED_INTENT = "USER_STATED_INTENT"
    DOCUMENT_ADDED = "DOCUMENT_ADDED"
    ARTIFACT_CONNECTED = "ARTIFACT_CONNECTED"
    RESEARCH_RESULT_RECEIVED = "RESEARCH_RESULT_RECEIVED"
    CLAIM_INFERRED = "CLAIM_INFERRED"
    EVIDENCE_ATTACHED = "EVIDENCE_ATTACHED"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    AMBIGUITY_DETECTED = "AMBIGUITY_DETECTED"
    UNKNOWN_IDENTIFIED = "UNKNOWN_IDENTIFIED"
    HUMAN_DECISION_RECORDED = "HUMAN_DECISION_RECORDED"
    REQUIREMENT_CANONICALIZED = "REQUIREMENT_CANONICALIZED"
    REQUIREMENT_SUPERSEDED = "REQUIREMENT_SUPERSEDED"
    CONSTRAINT_DISCOVERED = "CONSTRAINT_DISCOVERED"
    ASSUMPTION_IDENTIFIED = "ASSUMPTION_IDENTIFIED"
    RISK_IDENTIFIED = "RISK_IDENTIFIED"
    SUCCESS_METRIC_DEFINED = "SUCCESS_METRIC_DEFINED"
    VERIFICATION_OBLIGATION_DEFINED = "VERIFICATION_OBLIGATION_DEFINED"
    GAP_RECORDED = "GAP_RECORDED"
    GAP_RESOLVED = "GAP_RESOLVED"
    JOB_CREATED = "JOB_CREATED"
    JOB_STATUS_CHANGED = "JOB_STATUS_CHANGED"
    INTENT_CLOSURE_REACHED = "INTENT_CLOSURE_REACHED"
    INTENT_REOPENED = "INTENT_REOPENED"


class UserStatedIntentPayload(FrozenModel):
    text: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)


class ReferencePayload(FrozenModel):
    reference: str = Field(min_length=1)


class SemanticObjectPayload(FrozenModel):
    object: SemanticObject


class GapPayload(FrozenModel):
    gap: Gap


class GapResolvedPayload(FrozenModel):
    gap_id: str = Field(min_length=1)
    resolution_event_id: str = Field(min_length=1)


class JobPayload(FrozenModel):
    job: Job


class JobStatusChangedPayload(FrozenModel):
    job_id: str = Field(min_length=1)
    status: JobStatus
    attempt: int = Field(ge=0)


class SupersessionPayload(FrozenModel):
    object_id: str = Field(min_length=1)
    superseded_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ClosurePayload(FrozenModel):
    scope: str = Field(min_length=1)
    package_revision: int = Field(ge=1)


class ReopenPayload(FrozenModel):
    scope: str = Field(min_length=1)
    reason: str = Field(min_length=1)


type EventPayload = (
    UserStatedIntentPayload
    | ReferencePayload
    | SemanticObjectPayload
    | GapPayload
    | GapResolvedPayload
    | JobPayload
    | JobStatusChangedPayload
    | SupersessionPayload
    | ClosurePayload
    | ReopenPayload
)


EVENT_PAYLOAD_TYPES: dict[EventType, type[FrozenModel]] = {
    EventType.USER_STATED_INTENT: UserStatedIntentPayload,
    EventType.DOCUMENT_ADDED: ReferencePayload,
    EventType.ARTIFACT_CONNECTED: ReferencePayload,
    EventType.RESEARCH_RESULT_RECEIVED: SemanticObjectPayload,
    EventType.CLAIM_INFERRED: SemanticObjectPayload,
    EventType.EVIDENCE_ATTACHED: SemanticObjectPayload,
    EventType.CONFLICT_DETECTED: SemanticObjectPayload,
    EventType.AMBIGUITY_DETECTED: GapPayload,
    EventType.UNKNOWN_IDENTIFIED: SemanticObjectPayload,
    EventType.HUMAN_DECISION_RECORDED: SemanticObjectPayload,
    EventType.REQUIREMENT_CANONICALIZED: SemanticObjectPayload,
    EventType.REQUIREMENT_SUPERSEDED: SupersessionPayload,
    EventType.CONSTRAINT_DISCOVERED: SemanticObjectPayload,
    EventType.ASSUMPTION_IDENTIFIED: SemanticObjectPayload,
    EventType.RISK_IDENTIFIED: SemanticObjectPayload,
    EventType.SUCCESS_METRIC_DEFINED: SemanticObjectPayload,
    EventType.VERIFICATION_OBLIGATION_DEFINED: SemanticObjectPayload,
    EventType.GAP_RECORDED: GapPayload,
    EventType.GAP_RESOLVED: GapResolvedPayload,
    EventType.JOB_CREATED: JobPayload,
    EventType.JOB_STATUS_CHANGED: JobStatusChangedPayload,
    EventType.INTENT_CLOSURE_REACHED: ClosurePayload,
    EventType.INTENT_REOPENED: ReopenPayload,
}


class EventEnvelope(FrozenModel):
    event_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    event_type: EventType
    occurred_at: datetime
    correlation_id: str | None = None
    causation_id: str | None = None
    payload: EventPayload

    @model_validator(mode="after")
    def validate_payload_type(self) -> EventEnvelope:
        expected_type = EVENT_PAYLOAD_TYPES[self.event_type]
        if not isinstance(self.payload, expected_type):
            raise ValueError(
                f"payload for {self.event_type} must be {expected_type.__name__}, "
                f"got {type(self.payload).__name__}"
            )
        return self


class StoredEvent(FrozenModel):
    sequence: int = Field(ge=1)
    event: EventEnvelope


def parse_event(raw: Mapping[str, object]) -> EventEnvelope:
    try:
        event_type = EventType(str(raw["event_type"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("invalid or missing event_type") from exc

    if "payload" not in raw:
        raise ValueError("missing payload")

    payload_type = EVENT_PAYLOAD_TYPES[event_type]
    try:
        payload = payload_type.model_validate(raw["payload"])
    except Exception as exc:
        raise ValueError(f"invalid payload for {event_type}") from exc

    document = dict(raw)
    document["event_type"] = event_type
    document["payload"] = payload
    return EventEnvelope.model_validate(document)

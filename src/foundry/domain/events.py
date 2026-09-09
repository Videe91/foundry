from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.gaps import Gap, GapKind
from foundry.domain.jobs import Job, JobStatus
from foundry.domain.semantic import SemanticKind, SemanticObject


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
    GAP_WAIVED = "GAP_WAIVED"
    JOB_CREATED = "JOB_CREATED"
    JOB_STATUS_CHANGED = "JOB_STATUS_CHANGED"
    INTENT_CLOSURE_REACHED = "INTENT_CLOSURE_REACHED"
    INTENT_REOPENED = "INTENT_REOPENED"


class UserStatedIntentPayload(FrozenModel):
    text: str
    actor_id: str


class SourceReferencePayload(FrozenModel):
    source_ref: str = Field(min_length=1)


class SemanticObjectPayload(FrozenModel):
    object: SemanticObject


class GapPayload(FrozenModel):
    gap: Gap


class GapResolvedPayload(FrozenModel):
    gap_id: str


class GapWaivedPayload(FrozenModel):
    gap_id: str
    reason: str = Field(min_length=1)
    authorized_by: str = Field(min_length=1)


class JobPayload(FrozenModel):
    job: Job


class JobStatusChangedPayload(FrozenModel):
    job_id: str
    status: JobStatus
    attempt: int = Field(ge=0)


class SupersessionPayload(FrozenModel):
    object_id: str
    superseded_by: str
    reason: str


class ClosurePayload(FrozenModel):
    scope: str
    package_revision: int


class ReopenPayload(FrozenModel):
    scope: str
    reason: str


type EventPayload = (
    UserStatedIntentPayload
    | SourceReferencePayload
    | SemanticObjectPayload
    | GapPayload
    | GapResolvedPayload
    | GapWaivedPayload
    | JobPayload
    | JobStatusChangedPayload
    | SupersessionPayload
    | ClosurePayload
    | ReopenPayload
)

EVENT_PAYLOAD_TYPES: dict[EventType, type[FrozenModel]] = {
    EventType.USER_STATED_INTENT: UserStatedIntentPayload,
    EventType.DOCUMENT_ADDED: SourceReferencePayload,
    EventType.ARTIFACT_CONNECTED: SourceReferencePayload,
    EventType.RESEARCH_RESULT_RECEIVED: SourceReferencePayload,
    EventType.CLAIM_INFERRED: SemanticObjectPayload,
    EventType.EVIDENCE_ATTACHED: SemanticObjectPayload,
    EventType.CONFLICT_DETECTED: SemanticObjectPayload,
    EventType.UNKNOWN_IDENTIFIED: SemanticObjectPayload,
    EventType.HUMAN_DECISION_RECORDED: SemanticObjectPayload,
    EventType.REQUIREMENT_CANONICALIZED: SemanticObjectPayload,
    EventType.CONSTRAINT_DISCOVERED: SemanticObjectPayload,
    EventType.ASSUMPTION_IDENTIFIED: SemanticObjectPayload,
    EventType.RISK_IDENTIFIED: SemanticObjectPayload,
    EventType.SUCCESS_METRIC_DEFINED: SemanticObjectPayload,
    EventType.VERIFICATION_OBLIGATION_DEFINED: SemanticObjectPayload,
    EventType.AMBIGUITY_DETECTED: GapPayload,
    EventType.GAP_RECORDED: GapPayload,
    EventType.REQUIREMENT_SUPERSEDED: SupersessionPayload,
    EventType.GAP_RESOLVED: GapResolvedPayload,
    EventType.GAP_WAIVED: GapWaivedPayload,
    EventType.JOB_CREATED: JobPayload,
    EventType.JOB_STATUS_CHANGED: JobStatusChangedPayload,
    EventType.INTENT_CLOSURE_REACHED: ClosurePayload,
    EventType.INTENT_REOPENED: ReopenPayload,
}

SEMANTIC_KIND_BY_EVENT: dict[EventType, SemanticKind] = {
    EventType.CLAIM_INFERRED: SemanticKind.CLAIM,
    EventType.EVIDENCE_ATTACHED: SemanticKind.EVIDENCE,
    EventType.CONFLICT_DETECTED: SemanticKind.CONFLICT,
    EventType.UNKNOWN_IDENTIFIED: SemanticKind.UNKNOWN,
    EventType.HUMAN_DECISION_RECORDED: SemanticKind.DECISION,
    EventType.REQUIREMENT_CANONICALIZED: SemanticKind.REQUIREMENT,
    EventType.CONSTRAINT_DISCOVERED: SemanticKind.CONSTRAINT,
    EventType.ASSUMPTION_IDENTIFIED: SemanticKind.ASSUMPTION,
    EventType.RISK_IDENTIFIED: SemanticKind.RISK,
    EventType.SUCCESS_METRIC_DEFINED: SemanticKind.METRIC,
    EventType.VERIFICATION_OBLIGATION_DEFINED: SemanticKind.VERIFICATION_OBLIGATION,
}


class EventEnvelope(FrozenModel):
    event_id: str
    project_id: str
    event_type: EventType
    occurred_at: datetime
    correlation_id: str | None = None
    causation_id: str | None = None
    payload: EventPayload

    @model_validator(mode="after")
    def validate_payload_contract(self) -> EventEnvelope:
        expected = EVENT_PAYLOAD_TYPES[self.event_type]
        if type(self.payload) is not expected:
            raise ValueError(
                f"{self.event_type} requires {expected.__name__}, "
                f"got {type(self.payload).__name__}"
            )
        if self.event_type in SEMANTIC_KIND_BY_EVENT:
            payload = self.payload
            if not isinstance(payload, SemanticObjectPayload):
                raise ValueError(f"{self.event_type} requires SemanticObjectPayload")
            expected_kind = SEMANTIC_KIND_BY_EVENT[self.event_type]
            if payload.object.kind is not expected_kind:
                raise ValueError(
                    f"{self.event_type} requires semantic kind {expected_kind}, "
                    f"got {payload.object.kind}"
                )
        if self.event_type is EventType.AMBIGUITY_DETECTED:
            payload = self.payload
            if not isinstance(payload, GapPayload) or payload.gap.kind is not GapKind.AMBIGUITY:
                raise ValueError("AMBIGUITY_DETECTED requires a Gap with kind AMBIGUITY")
        _reject_project_mismatch(self.project_id, self.payload)
        return self


def _reject_project_mismatch(project_id: str, payload: EventPayload) -> None:
    embedded_project_id: str | None
    if isinstance(payload, SemanticObjectPayload):
        embedded_project_id = payload.object.project_id
    elif isinstance(payload, GapPayload):
        embedded_project_id = payload.gap.project_id
    elif isinstance(payload, JobPayload):
        embedded_project_id = payload.job.project_id
    else:
        return
    if embedded_project_id != project_id:
        raise ValueError(
            f"embedded project {embedded_project_id} does not match event project {project_id}"
        )


def parse_event(raw: Mapping[str, object]) -> EventEnvelope:
    event_type = EventType(raw["event_type"])  # type: ignore[arg-type]
    payload_cls = EVENT_PAYLOAD_TYPES[event_type]
    payload = payload_cls.model_validate(raw["payload"])
    fields = dict(raw)
    fields["event_type"] = event_type
    fields["payload"] = payload
    return EventEnvelope.model_validate(fields)


class StoredEvent(FrozenModel):
    sequence: int = Field(ge=1)
    event: EventEnvelope

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.evidence import EvidenceItem
from foundry.domain.gaps import Gap, GapKind
from foundry.domain.jobs import Job, JobStatus
from foundry.domain.semantic import SemanticKind, SemanticObject
from foundry.domain.semantic_judgment import AdmissionRoute, SemanticJudgment


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
    SEMANTIC_OBJECT_RECORDED = "SEMANTIC_OBJECT_RECORDED"
    GAP_RECORDED = "GAP_RECORDED"
    GAP_RESOLVED = "GAP_RESOLVED"
    GAP_WAIVED = "GAP_WAIVED"
    JOB_CREATED = "JOB_CREATED"
    JOB_STATUS_CHANGED = "JOB_STATUS_CHANGED"
    INTENT_CLOSURE_REACHED = "INTENT_CLOSURE_REACHED"
    INTENT_REOPENED = "INTENT_REOPENED"
    EVIDENCE_INGESTED = "EVIDENCE_INGESTED"
    SEMANTIC_JUDGMENT_RECORDED = "SEMANTIC_JUDGMENT_RECORDED"
    SEMANTIC_ADMISSION_DECIDED = "SEMANTIC_ADMISSION_DECIDED"
    DERIVATION_RECORDED = "DERIVATION_RECORDED"


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


class EvidencePayload(FrozenModel):
    """Evidence entering the ledger. Evidence is never intent (spec §1.1)."""

    evidence: EvidenceItem


class SemanticJudgmentPayload(FrozenModel):
    """A recorded semantic proposal. Recording is evidence, never a transition."""

    judgment: SemanticJudgment


class SemanticAdmissionPayload(FrozenModel):
    """The deterministic admission decision for one recorded judgment.

    Only ``route is AdmissionRoute.APPLY`` may change semantic state (spec §22.1, §22.11).
    """

    judgment_id: str = Field(min_length=1)
    route: AdmissionRoute
    reasons: tuple[str, ...]
    corroborating_judgment_ids: tuple[str, ...] = ()


class DerivationPayload(FrozenModel):
    """``child_id`` DERIVED_FROM ``parent_id`` (spec §19.1). Append-only."""

    child_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)


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
    | EvidencePayload
    | SemanticJudgmentPayload
    | SemanticAdmissionPayload
    | DerivationPayload
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
    EventType.SEMANTIC_OBJECT_RECORDED: SemanticObjectPayload,
    EventType.AMBIGUITY_DETECTED: GapPayload,
    EventType.GAP_RECORDED: GapPayload,
    EventType.REQUIREMENT_SUPERSEDED: SupersessionPayload,
    EventType.GAP_RESOLVED: GapResolvedPayload,
    EventType.GAP_WAIVED: GapWaivedPayload,
    EventType.JOB_CREATED: JobPayload,
    EventType.JOB_STATUS_CHANGED: JobStatusChangedPayload,
    EventType.INTENT_CLOSURE_REACHED: ClosurePayload,
    EventType.INTENT_REOPENED: ReopenPayload,
    EventType.EVIDENCE_INGESTED: EvidencePayload,
    EventType.SEMANTIC_JUDGMENT_RECORDED: SemanticJudgmentPayload,
    EventType.SEMANTIC_ADMISSION_DECIDED: SemanticAdmissionPayload,
    EventType.DERIVATION_RECORDED: DerivationPayload,
}

SPECIALIZED_SEMANTIC_KIND_BY_EVENT: dict[EventType, SemanticKind] = {
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

GENERIC_SEMANTIC_KINDS: frozenset[SemanticKind] = frozenset(
    {
        SemanticKind.INTENT,
        SemanticKind.GOAL,
        SemanticKind.ACTOR,
        SemanticKind.OUTCOME,
        SemanticKind.NON_GOAL,
        SemanticKind.PREFERENCE,
        SemanticKind.QUESTION,
        SemanticKind.CONTRACT,
        SemanticKind.AUTHORITY_RECORD,
        SemanticKind.AMENDMENT,
    }
)


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
        if self.event_type in SPECIALIZED_SEMANTIC_KIND_BY_EVENT:
            payload = self.payload
            if not isinstance(payload, SemanticObjectPayload):
                raise ValueError(f"{self.event_type} requires SemanticObjectPayload")
            expected_kind = SPECIALIZED_SEMANTIC_KIND_BY_EVENT[self.event_type]
            if payload.object.kind is not expected_kind:
                raise ValueError(
                    f"{self.event_type} requires semantic kind {expected_kind}, "
                    f"got {payload.object.kind}"
                )
        if self.event_type is EventType.SEMANTIC_OBJECT_RECORDED:
            payload = self.payload
            if not isinstance(payload, SemanticObjectPayload):
                raise ValueError("SEMANTIC_OBJECT_RECORDED requires SemanticObjectPayload")
            if payload.object.kind not in GENERIC_SEMANTIC_KINDS:
                raise ValueError(
                    f"SEMANTIC_OBJECT_RECORDED cannot carry specialized kind {payload.object.kind}"
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
    elif isinstance(payload, EvidencePayload):
        embedded_project_id = payload.evidence.project_id
    elif isinstance(payload, SemanticJudgmentPayload):
        embedded_project_id = payload.judgment.project_id
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

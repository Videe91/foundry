from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from foundry.domain.common import Authority, FrozenModel, RelationType
from foundry.domain.evidence import EvidenceItem
from foundry.domain.gaps import Gap, GapKind
from foundry.domain.intent_graph import (
    GRAPH_CONTRACT_VERSION,
    IntentGraphIdentity,
    IntentGraphSynthesisResult,
)
from foundry.domain.intent_graph_state import (
    CompiledIntentGraph,
    GraphNodeAssignment,
    IntentGraphDecision,
    validate_graph_decision_shape,
)
from foundry.domain.intent_synthesis import (
    INTENT_BEARING_SEMANTIC_KINDS,
    IntentSynthesisDecision,
    IntentSynthesisDecisionRecord,
    InvalidationReason,
    RequirementSynthesisProposal,
    SynthesisIdentity,
    SynthesisOrigin,
)
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.jobs import Job, JobStatus
from foundry.domain.semantic import SemanticKind, SemanticObject
from foundry.domain.semantic_judgment import AdmissionRoute, ReasonerFingerprint, SemanticJudgment


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
    INTENT_SYNTHESIS_DECIDED = "INTENT_SYNTHESIS_DECIDED"
    INTENT_OBJECT_SYNTHESIZED = "INTENT_OBJECT_SYNTHESIZED"
    INTENT_SYNTHESIS_INVALIDATED = "INTENT_SYNTHESIS_INVALIDATED"
    INTENT_OBJECT_ADMITTED = "INTENT_OBJECT_ADMITTED"
    INTENT_GRAPH_SYNTHESIS_DECIDED = "INTENT_GRAPH_SYNTHESIS_DECIDED"


class UserStatedIntentPayload(FrozenModel):
    text: str
    actor_id: str


class SourceReferencePayload(FrozenModel):
    source_ref: str = Field(min_length=1)


class SemanticObjectPayload(FrozenModel):
    object: SemanticObject


class GapPayload(FrozenModel):
    # Base first, empirically. Under the reverse order a legacy ``Gap`` round-trips as
    # ``IntentSynthesisGap`` — every added field is defaulted, so the subtype accepts a
    # legacy dict — which would silently rewrite the replay of streams that already
    # exist. With ``Gap`` first, ``extra="forbid"`` rejects a synthesis dict against the
    # base and each kind reconstructs as itself.
    gap: Gap | IntentSynthesisGap


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


class IntentSynthesisDecidedPayload(FrozenModel):
    """Proposal AND decision in ONE durable event (spec §10.5, C12, C19).

    Separating proposal from admission created a durable decided-with-no-decision
    state whose only completion was to re-route later — and re-routing is unsafe
    because routing reads live governance state that moves. Collapsing them makes the
    decision and the state it was computed from one durable fact.

    It carries everything T4 needs to reconstruct an ``IntentSynthesisDecisionRecord``
    with **no external lookup**, except the two fields the envelope owns:
    ``event_id`` becomes ``decision_event_id`` and ``occurred_at`` becomes
    ``decided_at``. Those are deliberately absent here — ``extra="forbid"`` means a
    synthesizer cannot supply either, so provenance and decision time always come from
    the ledger rather than from the thing being recorded.
    """

    proposal: RequirementSynthesisProposal
    author: ReasonerFingerprint
    identity: SynthesisIdentity
    origin: SynthesisOrigin
    assigned_authority: Authority | None
    decision: IntentSynthesisDecision


def derivation_parents_of(obj: SemanticObject) -> tuple[str, ...]:
    """The canonical derivation-parent tuple for an object: sorted, deduplicated.

    One definition, used by both the admission payload's validator and the governed seam,
    so the two can never disagree about what "the object's basis" means. Ordering and
    duplicate handling are part of the event contract rather than an accident of how the
    relations happened to be listed.
    """
    return tuple(
        sorted(
            {
                relation.target_id
                for relation in obj.relations
                if relation.relation_type is RelationType.DERIVED_FROM
            }
        )
    )


class IntentObjectAdmissionPayload(FrozenModel):
    """One governed admission of an intent-bearing object (IE2.1, spec §3c).

    Everything the admission durably means travels in this one event, because
    ``EventStore`` exposes only ``append(event, expected_sequence)`` and each adapter
    commits per call: a seam that appended the object and then recorded its edges would be
    N+1 independent transitions, and a crash between them would leave an object whose
    ``DERIVED_FROM`` relations have no edges. One event makes that split unrepresentable
    rather than merely unlikely.

    ``author`` is carried because an admission must durably record *who* authored what it
    admitted; reconstructing that from surrounding events would make authorship inferential
    at exactly the point it has to be certain. It is a ``ReasonerFingerprint``, never a
    ``Provenance``: provenance says where a fact came from, authorship says who asserted it,
    and collapsing them is the laundering C9/I22 forbids.

    ``derivation_parent_ids`` is immutable data, equal at write time to the object's
    ``DERIVED_FROM`` targets. The reducer reconstructs exactly these edges and never
    recomputes them from whichever relations currently imply derivation — otherwise a later
    change to that rule would silently alter how existing events replay, and the ledger
    would stop meaning one fixed thing.
    """

    object: SemanticObject
    author: ReasonerFingerprint
    derivation_parent_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_admission_contract(self) -> IntentObjectAdmissionPayload:
        """The event means what its name says, even if malformed data reaches this layer.

        The governed seam checks these too, but a payload constructed directly must not be
        able to assert something the seam would never have written. An event whose internal
        story contradicts itself is worse than a rejected one: it replays forever.
        """
        if self.object.kind not in INTENT_BEARING_SEMANTIC_KINDS:
            raise ValueError(
                f"INTENT_OBJECT_ADMITTED cannot carry {self.object.kind}; only an "
                "intent-bearing kind may be admitted"
            )
        if self.derivation_parent_ids != derivation_parents_of(self.object):
            raise ValueError(
                "derivation_parent_ids must equal the object's DERIVED_FROM targets, "
                "canonically sorted and deduplicated; an event may not claim one basis "
                "locally and another in traversal data"
            )
        return self


class IntentObjectPayload(FrozenModel):
    """The object and its effect inputs, in ONE event (spec §10.5, C1, C7).

    Carries the inputs, never the consequences. Derivation edges, the retirement
    record and the applied marker are computed by the reducer from ``basis_claim_ids``
    and ``replaces_object_id`` when it applies this event (T4), so they cannot
    desynchronise from the claims they describe and cannot be smuggled in
    pre-computed.

    ``replaces_object_id`` is set only for a ``REPLACES_STALE`` reconciliation.
    Retirement rides inside this event rather than following it, so a replacement can
    never be complete while its required retirement is missing.
    """

    object: SemanticObject
    basis_claim_ids: tuple[str, ...] = Field(min_length=1)
    replaces_object_id: str | None = None
    proposal_instance_id: str = Field(min_length=1)


class IntentSynthesisInvalidatedPayload(FrozenModel):
    """A durable ``DECIDED(APPLY)`` reached a terminal non-effect (spec §10.8, C13).

    Minimal by design. It does not repeat the proposal, because the full durable
    decision already exists in ``IntentSynthesisState.decisions``; it establishes no
    object, retires nothing, assigns no authority, and carries no retry instruction.
    The reason is drawn from a bounded enum so the ledger stays analysable — never
    free text.
    """

    proposal_instance_id: str = Field(min_length=1)
    reason: InvalidationReason


class IntentGraphSynthesisDecidedPayload(FrozenModel):
    """One whole Intent Graph decision AND its application, in ONE event (IE3, R103).

    There is no decided-but-unapplied window: ``compiled`` is present exactly when the route is
    ``APPLY``, and the reducer applies every object, derivation edge, gap and retirement it names
    in a single transition, or refuses the event. Every other route records the decision only.

    ``run_scope`` is carried because every compiled node's scope is ``(run_scope,)`` (Q2); the
    reducer cannot bind scope without it. The envelope owns ``event_id``, ``occurred_at`` and
    ``project_id``: ``extra="forbid"`` means nothing proposed can supply them.
    """

    graph_contract_version: Literal["ie3.graph-v1"] = GRAPH_CONTRACT_VERSION
    identity: IntentGraphIdentity
    author: ReasonerFingerprint
    run_scope: str = Field(min_length=1)
    result: IntentGraphSynthesisResult
    node_assignments: tuple[GraphNodeAssignment, ...]
    decision: IntentGraphDecision
    compiled: CompiledIntentGraph | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> IntentGraphSynthesisDecidedPayload:
        validate_graph_decision_shape(
            identity=self.identity,
            result=self.result,
            node_assignments=self.node_assignments,
            decision=self.decision,
            compiled=self.compiled,
        )
        return self


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
    | IntentSynthesisDecidedPayload
    | IntentObjectPayload
    | IntentObjectAdmissionPayload
    | IntentSynthesisInvalidatedPayload
    | IntentGraphSynthesisDecidedPayload
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
    EventType.INTENT_SYNTHESIS_DECIDED: IntentSynthesisDecidedPayload,
    EventType.INTENT_OBJECT_SYNTHESIZED: IntentObjectPayload,
    EventType.INTENT_OBJECT_ADMITTED: IntentObjectAdmissionPayload,
    EventType.INTENT_SYNTHESIS_INVALIDATED: IntentSynthesisInvalidatedPayload,
    EventType.INTENT_GRAPH_SYNTHESIS_DECIDED: IntentGraphSynthesisDecidedPayload,
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
                f"{self.event_type} requires {expected.__name__}, got {type(self.payload).__name__}"
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
        if self.event_type is EventType.INTENT_OBJECT_SYNTHESIZED:
            payload = self.payload
            if not isinstance(payload, IntentObjectPayload):
                raise ValueError("INTENT_OBJECT_SYNTHESIZED requires IntentObjectPayload")
            if payload.object.kind not in INTENT_BEARING_SEMANTIC_KINDS:
                raise ValueError(
                    f"INTENT_OBJECT_SYNTHESIZED cannot carry {payload.object.kind}; "
                    "only an intent-bearing kind may be synthesized"
                )
        if self.event_type is EventType.INTENT_SYNTHESIS_DECIDED:
            payload = self.payload
            if not isinstance(payload, IntentSynthesisDecidedPayload):
                raise ValueError("INTENT_SYNTHESIS_DECIDED requires IntentSynthesisDecidedPayload")
            # Reuse the T2.2 single source of identity coherence rather than restating a
            # weaker parallel law here: constructing the record proves the mapping key,
            # the decision and the proposal BODY all belong to one identity. This is a
            # STRUCTURAL check only - no routing is re-run and no authority is decided.
            IntentSynthesisDecisionRecord(
                identity=payload.identity,
                proposal=payload.proposal,
                author=payload.author,
                origin=payload.origin,
                assigned_authority=payload.assigned_authority,
                decision=payload.decision,
                decision_event_id=self.event_id,
                decided_at=self.occurred_at,
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
    elif isinstance(payload, IntentObjectPayload | IntentObjectAdmissionPayload):
        embedded_project_id = payload.object.project_id
    elif isinstance(payload, IntentSynthesisDecidedPayload | IntentGraphSynthesisDecidedPayload):
        embedded_project_id = payload.identity.project_id
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

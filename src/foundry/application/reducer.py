from __future__ import annotations

from foundry.application.semantic_reducer import reduce_semantic_event
from foundry.domain.common import Authority, LifecycleStatus, RelationType
from foundry.domain.derivation import DerivationEdge
from foundry.domain.events import (
    ClosurePayload,
    EventEnvelope,
    EventType,
    GapPayload,
    GapResolvedPayload,
    GapWaivedPayload,
    IntentObjectPayload,
    IntentSynthesisDecidedPayload,
    IntentSynthesisInvalidatedPayload,
    JobPayload,
    JobStatusChangedPayload,
    ReopenPayload,
    SemanticObjectPayload,
    StoredEvent,
    SupersessionPayload,
)
from foundry.domain.gaps import GapStatus
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisDecisionRecord,
    IntentSynthesisRoute,
    replacement_scope_covers,
)
from foundry.domain.intent_synthesis_state import IntentSynthesisState, RetirementRecord
from foundry.domain.semantic import Requirement, SemanticObject
from foundry.domain.semantic_state import SemanticState
from foundry.domain.state import IntentState

# --- Intent Synthesis reduction (T4) ------------------------------------------------
#
# Structural and replay-deterministic only. The reducer never derives a semantic view,
# never re-runs routing and never re-decides authority: those decisions were already
# taken and are durable in the decision record. What it enforces is that the EFFECT
# belongs to that decision (C20) and that a replacement cannot delete broader intent
# (C21).


def _synthesis_updated(state: IntentSynthesisState, **changes: object) -> IntentSynthesisState:
    """Rebuild through validation, mirroring ``semantic_reducer._updated``.

    Going through ``model_validate`` keeps every mapping a frozen proxy AND re-runs the
    I24 terminal-bookkeeping validator, so no reducer path can write a state the
    projection itself would reject.
    """
    return IntentSynthesisState.model_validate({**dict(state), **changes})


def _require_event_id(event: EventEnvelope, expected: str, step: str) -> None:
    if event.event_id != expected:
        raise ValueError(
            f"{event.event_type} carries event id {event.event_id!r}; the deterministic "
            f"{step} event id for this proposal is {expected!r}"
        )


def _reduce_decided(state: IntentState, event: EventEnvelope) -> IntentSynthesisState:
    payload = event.payload
    if not isinstance(payload, IntentSynthesisDecidedPayload):
        raise ValueError("INTENT_SYNTHESIS_DECIDED requires IntentSynthesisDecidedPayload")
    identity = payload.identity
    _require_event_id(event, identity.event_id("DECIDED"), "DECIDED")
    proposal_instance_id = identity.proposal_instance_id
    if proposal_instance_id in state.intent_synthesis.decisions:
        raise ValueError(f"proposal {proposal_instance_id} already has a durable decision")

    if payload.decision.route is IntentSynthesisRoute.APPLY:
        # Structural feasibility, not routing: an applied object necessarily carries an
        # authority, and an EXISTING_UNCHANGED proposal must never reach a durable APPLY
        # lifecycle that contradicts its own declared meaning.
        if payload.assigned_authority is None:
            raise ValueError("an APPLY decision must carry an assigned authority")
        if payload.proposal.disposition is IntentDisposition.EXISTING_UNCHANGED:
            raise ValueError(
                "disposition EXISTING_UNCHANGED can never carry route APPLY; it produces no effect"
            )

    record = IntentSynthesisDecisionRecord(
        identity=identity,
        proposal=payload.proposal,
        author=payload.author,
        origin=payload.origin,
        assigned_authority=payload.assigned_authority,
        decision=payload.decision,
        decision_event_id=event.event_id,
        decided_at=event.occurred_at,
    )
    return _synthesis_updated(
        state.intent_synthesis,
        decisions={**dict(state.intent_synthesis.decisions), proposal_instance_id: record},
    )


def _applicable_record(
    state: IntentState, proposal_instance_id: str, what: str
) -> IntentSynthesisDecisionRecord:
    """The durable APPLY decision this outcome must belong to (C20)."""
    record = state.intent_synthesis.decisions.get(proposal_instance_id)
    if record is None:
        raise ValueError(f"{what} names {proposal_instance_id!r}, which has no durable decision")
    if record.decision.route is not IntentSynthesisRoute.APPLY:
        raise ValueError(
            f"{what} names {proposal_instance_id!r}, whose route is "
            f"{record.decision.route.value}; only APPLY has an outcome"
        )
    if proposal_instance_id in state.intent_synthesis.applied_proposal_ids:
        raise ValueError(f"proposal {proposal_instance_id} is already applied")
    if proposal_instance_id in state.intent_synthesis.invalidated_proposal_ids:
        raise ValueError(f"proposal {proposal_instance_id} is already invalidated")
    return record


def _expected_scope(semantic: SemanticState, basis_claim_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Runtime-derived scope: the union of the basis claims' address scopes."""
    scopes: set[str] = set()
    for claim_id in basis_claim_ids:
        address = semantic.addresses[semantic.claims[claim_id].address_id]
        scopes.update(address.scope)
    return tuple(sorted(scopes))


def _validate_basis(
    state: IntentState, record: IntentSynthesisDecisionRecord, payload: IntentObjectPayload
) -> None:
    if payload.basis_claim_ids != record.proposal.basis_claim_ids:
        raise ValueError(
            f"basis {payload.basis_claim_ids} does not equal the decided basis "
            f"{record.proposal.basis_claim_ids}; no claim may be added, removed or "
            "substituted after the decision"
        )
    for claim_id in payload.basis_claim_ids:
        claim = state.semantic.claims.get(claim_id)
        if claim is None:
            raise ValueError(f"basis claim {claim_id!r} does not exist in semantic state")
        if claim.address_id not in state.semantic.addresses:
            raise ValueError(
                f"basis claim {claim_id!r} references address {claim.address_id!r}, "
                "which does not exist"
            )


def _validate_object(
    state: IntentState, record: IntentSynthesisDecisionRecord, payload: IntentObjectPayload
) -> None:
    """The object must be the outcome of THIS decision, not merely correlated with it."""
    obj = payload.object
    expected_id = record.identity.object_id("REQ")
    if obj.id != expected_id:
        raise ValueError(f"object id {obj.id!r} is not the deterministic object id {expected_id!r}")
    if obj.id in state.objects:
        raise ValueError(f"object {obj.id!r} already exists")
    if obj.kind is not record.proposal.target_kind:
        raise ValueError(
            f"object kind {obj.kind} does not equal the decided target kind "
            f"{record.proposal.target_kind}"
        )
    if not isinstance(obj, Requirement):
        raise ValueError("Slice 1 synthesizes Requirement only")
    if obj.statement != record.proposal.statement:
        raise ValueError(
            "object statement does not equal the decided statement; a decision for one "
            "meaning must never establish another"
        )
    if obj.authority is not record.assigned_authority:
        raise ValueError(
            f"object authority {obj.authority} does not equal the assigned authority "
            f"{record.assigned_authority}"
        )
    if obj.confidence != record.proposal.confidence:
        # C20 binding, completed once D12 settled. Confidence is metadata no rule reads,
        # but a durable decision must not be rewritten by the event applying it — and
        # ``None`` (no value supplied) is deliberately distinct from ``0.0``.
        raise ValueError(
            f"object confidence {obj.confidence!r} does not equal the decided confidence "
            f"{record.proposal.confidence!r}"
        )
    if obj.created_at != record.decided_at:
        raise ValueError(
            "object created_at does not equal the durable decided_at; recovery must not "
            "mint a different creation time"
        )
    if obj.lifecycle is not LifecycleStatus.ACTIVE or obj.revision != 1:
        raise ValueError(
            "a newly synthesized object must arrive ACTIVE at revision 1, got "
            f"{obj.lifecycle} at revision {obj.revision}"
        )
    expected_scope = _expected_scope(state.semantic, payload.basis_claim_ids)
    if tuple(obj.scope) != expected_scope:
        raise ValueError(
            f"object scope {tuple(obj.scope)} does not equal the runtime-derived scope "
            f"{expected_scope} (union of the basis addresses' scopes)"
        )
    expected_sources = (record.decision_event_id,)
    if obj.provenance.source_event_ids != expected_sources:
        raise ValueError(
            f"object provenance source_event_ids {obj.provenance.source_event_ids} must be "
            f"{expected_sources}, pointing back at the durable decision"
        )
    # I3: exactly one DERIVED_FROM per basis claim, targeting the CLAIM id, and nothing
    # else. The derivation edge written below targets the asserting JUDGMENT instead;
    # the asymmetry is deliberate and load-bearing.
    expected_relations = sorted(
        (RelationType.DERIVED_FROM.value, claim_id) for claim_id in payload.basis_claim_ids
    )
    actual_relations = sorted((r.relation_type.value, r.target_id) for r in obj.relations)
    if actual_relations != expected_relations:
        raise ValueError(
            f"object relations {actual_relations} must be exactly one DERIVED_FROM per basis "
            f"claim {expected_relations}"
        )


def _validate_replacement(
    state: IntentState, record: IntentSynthesisDecisionRecord, payload: IntentObjectPayload
) -> SemanticObject | None:
    disposition = record.proposal.disposition
    if disposition is IntentDisposition.NEW:
        if payload.replaces_object_id is not None:
            raise ValueError("disposition NEW must not name replaces_object_id")
        return None
    if disposition is IntentDisposition.EXISTING_UNCHANGED:
        raise ValueError("disposition EXISTING_UNCHANGED produces no synthesized outcome")
    if payload.replaces_object_id != record.proposal.relates_to_object_id:
        raise ValueError(
            f"replaces_object_id {payload.replaces_object_id!r} does not equal the decided "
            f"target {record.proposal.relates_to_object_id!r}"
        )
    target = state.objects.get(payload.replaces_object_id or "")
    if target is None:
        raise ValueError(f"replacement target {payload.replaces_object_id!r} does not exist")
    if target.id == payload.object.id:
        raise ValueError("an object cannot replace itself")
    if target.kind is not payload.object.kind:
        raise ValueError(
            f"replacement kind {payload.object.kind} does not equal target kind {target.kind}"
        )
    if target.lifecycle is not LifecycleStatus.ACTIVE:
        raise ValueError(f"replacement target {target.id!r} is not ACTIVE")
    if target.authority in (Authority.REJECTED, Authority.SUPERSEDED):
        raise ValueError(f"replacement target {target.id!r} carries authority {target.authority}")
    if any(r.retired_object_id == target.id for r in state.intent_synthesis.retirements):
        raise ValueError(f"replacement target {target.id!r} is already retired")
    # C11: canonical authority is preserved by ONE equality check; no Authority ordering
    # is introduced.
    if (
        target.authority is Authority.CANONICAL
        and payload.object.authority is not Authority.CANONICAL
    ):
        raise ValueError("a CANONICAL target may be retired only by a CANONICAL replacement")
    # C21: a narrower replacement must not delete broader intent.
    if not replacement_scope_covers(tuple(payload.object.scope), tuple(target.scope)):
        raise ValueError(
            f"replacement scope {tuple(payload.object.scope)} does not cover target scope "
            f"{tuple(target.scope)}; a narrower replacement cannot retire broader intent"
        )
    return target


def _reduce_invalidated(state: IntentState, event: EventEnvelope) -> IntentSynthesisState:
    payload = event.payload
    if not isinstance(payload, IntentSynthesisInvalidatedPayload):
        raise ValueError("INTENT_SYNTHESIS_INVALIDATED requires IntentSynthesisInvalidatedPayload")
    record = _applicable_record(state, payload.proposal_instance_id, "INTENT_SYNTHESIS_INVALIDATED")
    _require_event_id(event, record.identity.event_id("INVALIDATED"), "INVALIDATED")
    # The bounded reason is recorded, never re-litigated: whether it still holds is
    # orchestration's business, not the reducer's.
    return _synthesis_updated(
        state.intent_synthesis,
        invalidated_proposal_ids=(
            *state.intent_synthesis.invalidated_proposal_ids,
            payload.proposal_instance_id,
        ),
    )


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
    semantic = state.semantic
    intent_synthesis = state.intent_synthesis

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
        case (
            EventType.EVIDENCE_INGESTED
            | EventType.SEMANTIC_JUDGMENT_RECORDED
            | EventType.SEMANTIC_ADMISSION_DECIDED
            | EventType.DERIVATION_RECORDED
        ):
            semantic = reduce_semantic_event(state.semantic, stored_event)
        case EventType.INTENT_SYNTHESIS_DECIDED:
            # Projection only: no object, no edge, no retirement, no marker.
            intent_synthesis = _reduce_decided(state, event)
        case EventType.INTENT_OBJECT_SYNTHESIZED:
            payload = event.payload
            if not isinstance(payload, IntentObjectPayload):
                raise ValueError("INTENT_OBJECT_SYNTHESIZED requires IntentObjectPayload")
            record = _applicable_record(
                state, payload.proposal_instance_id, "INTENT_OBJECT_SYNTHESIZED"
            )
            _require_event_id(event, record.identity.event_id("SYNTHESIZED"), "SYNTHESIZED")
            _validate_basis(state, record, payload)
            _validate_object(state, record, payload)
            target = _validate_replacement(state, record, payload)

            # One indivisible application: object, every derivation edge, the optional
            # retirement plus its record, and the applied marker. There is no ordering
            # in which a replacement exists while its retirement is missing.
            objects[payload.object.id] = payload.object
            semantic = SemanticState.model_validate(
                {
                    **dict(state.semantic),
                    "derivations": (
                        *state.semantic.derivations,
                        *(
                            DerivationEdge(
                                child_id=payload.object.id,
                                parent_id=state.semantic.claims[claim_id].created_by_judgment_id,
                                recorded_by_event_id=event.event_id,
                            )
                            for claim_id in payload.basis_claim_ids
                        ),
                    ),
                }
            )
            changes: dict[str, object] = {
                "applied_proposal_ids": (
                    *state.intent_synthesis.applied_proposal_ids,
                    payload.proposal_instance_id,
                )
            }
            if target is not None:
                objects[target.id] = target.model_copy(
                    update={
                        "lifecycle": LifecycleStatus.SUPERSEDED,
                        "revision": target.revision + 1,
                    }
                )
                changes["retirements"] = (
                    *state.intent_synthesis.retirements,
                    RetirementRecord(
                        retired_object_id=target.id,
                        replaced_by_object_id=payload.object.id,
                        proposal_instance_id=payload.proposal_instance_id,
                        recorded_by_event_id=event.event_id,
                    ),
                )
            intent_synthesis = _synthesis_updated(state.intent_synthesis, **changes)
        case EventType.INTENT_SYNTHESIS_INVALIDATED:
            intent_synthesis = _reduce_invalidated(state, event)

    return IntentState(
        project_id=state.project_id,
        revision=state.revision + 1,
        last_sequence=stored_event.sequence,
        source_events=(*state.source_events, event.event_id),
        objects=objects,
        gaps=gaps,
        jobs=jobs,
        closed_scopes=closed_scopes,
        semantic=semantic,
        intent_synthesis=intent_synthesis,
    )

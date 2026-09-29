from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from foundry.application.semantic_reducer import reduce_semantic_event
from foundry.domain.authority import object_is_current
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    RiskLevel,
    SourceKind,
)
from foundry.domain.derivation import DerivationEdge
from foundry.domain.events import (
    ClosurePayload,
    EventEnvelope,
    EventType,
    GapPayload,
    GapResolvedPayload,
    GapWaivedPayload,
    IntentGraphSynthesisDecidedPayload,
    IntentObjectAdmissionPayload,
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
from foundry.domain.gaps import Gap, GapStatus
from foundry.domain.intent_graph import (
    MAX_GRAPH_GAPS,
    MAX_GRAPH_NODES,
    MAX_GRAPH_RELATIONS,
    AssumptionNodeProposal,
    BasisClaimRef,
    ConstraintNodeProposal,
    DecisionNodeProposal,
    ExistingObjectRef,
    GraphNodeDisposition,
    GraphNodeProposal,
    GraphRef,
    IntentGraphGap,
    IntentNodeProposal,
    LocalNodeRef,
    RequirementNodeProposal,
)
from foundry.domain.intent_graph_state import (
    IntentGraphDecisionRecord,
    IntentGraphSynthesisState,
    graph_decision_event_id,
    validate_graph_decision_shape,
)
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisDecisionRecord,
    IntentSynthesisRoute,
    SynthesisOrigin,
    replacement_scope_covers,
)
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.intent_synthesis_state import IntentSynthesisState, RetirementRecord
from foundry.domain.intent_view import derive_intent_view
from foundry.domain.semantic import (
    Assumption,
    Constraint,
    Goal,
    Intent,
    NonGoal,
    Outcome,
    Preference,
    ProjectDecision,
    Requirement,
    SemanticKind,
    SemanticObject,
)
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


# --- IE3 atomic graph transition (R103, R108) ---------------------------------------
#
# The independent second body. Every binding is re-derived here from the immutable payload and
# the state prefix the event lands on: identities, every object field, relations, derivation
# parents, gaps and retirements. Nothing calls the compiler, the graph validator or a forward
# IE2 governance law: replay proves the event is internally true and applicable at its own
# sequence, and never re-litigates what governance decided under today's rules.

_GRAPH_ASSIGNABLE: Final = frozenset({Authority.CANONICAL, Authority.PROPOSED})
_GRAPH_NON_HUMAN: Final = frozenset({SynthesisOrigin.AI_INFERRED, SynthesisOrigin.RESEARCH_DERIVED})
_GRAPH_UNREPLACEABLE: Final = frozenset({SemanticKind.INTENT, SemanticKind.ASSUMPTION})
_GRAPH_CLASSES: Final[dict[SemanticKind, type[SemanticObject]]] = {
    SemanticKind.INTENT: Intent,
    SemanticKind.GOAL: Goal,
    SemanticKind.OUTCOME: Outcome,
    SemanticKind.REQUIREMENT: Requirement,
    SemanticKind.CONSTRAINT: Constraint,
    SemanticKind.NON_GOAL: NonGoal,
    SemanticKind.PREFERENCE: Preference,
    SemanticKind.DECISION: ProjectDecision,
    SemanticKind.ASSUMPTION: Assumption,
}
_GRAPH_BOUND_FIELDS: Final = frozenset(
    {
        "id",
        "kind",
        "project_id",
        "mission",
        "statement",
        "facet",
        "rationale",
        "risk_level",
        "confidence",
        "authority",
        "scope",
        "provenance",
        "created_at",
        "lifecycle",
        "revision",
        "relations",
    }
)
"""Fields bound by a named check below. Every other field is bound as ``BINDING_FIELDS``."""


def _graph_fail(code: str, message: str) -> ValueError:
    return ValueError(f"{code}: {message}")


@dataclass(frozen=True)
class _GraphEffect:
    objects: dict[str, SemanticObject]
    gaps: dict[str, Gap | IntentSynthesisGap]
    semantic: SemanticState
    intent_synthesis: IntentSynthesisState
    intent_graph_synthesis: IntentGraphSynthesisState


def _graph_target(
    state: IntentState, payload: IntentGraphSynthesisDecidedPayload, ref: GraphRef
) -> str:
    """The durable id a reference names, which must exist where the event lands."""
    identity = payload.identity
    if isinstance(ref, LocalNodeRef):
        node = next((n for n in payload.result.nodes if n.local_id.local_id == ref.local_id), None)
        if node is None:
            raise _graph_fail("UNRESOLVED_REFERENCE", f"local {ref.local_id!r} names no node")
        return identity.object_id(node.kind, ref.local_id)
    if isinstance(ref, ExistingObjectRef):
        if ref.object_id not in state.objects:
            raise _graph_fail("UNRESOLVED_REFERENCE", f"existing {ref.object_id!r} is not in state")
        return ref.object_id
    if ref.claim_id not in state.semantic.claims:
        raise _graph_fail("UNRESOLVED_REFERENCE", f"basis claim {ref.claim_id!r} is not in state")
    return ref.claim_id


def _graph_expected_object(
    state: IntentState,
    payload: IntentGraphSynthesisDecidedPayload,
    event: EventEnvelope,
    node: GraphNodeProposal,
    authority: Authority,
) -> SemanticObject:
    """What this node must compile to, rebuilt from the payload alone (a second body)."""
    identity = payload.identity
    local_id = node.local_id.local_id
    author = payload.author
    if author.is_human:
        provenance = Provenance(
            source_kind=SourceKind.HUMAN,
            source_ref=author.model,
            source_event_ids=(event.event_id,),
        )
    else:
        provenance = Provenance(
            source_kind=SourceKind.SYSTEM,
            source_ref=identity.synthesis_run_id,
            source_event_ids=(event.event_id,),
        )
    relations = tuple(
        sorted(
            (
                Relation(
                    relation_type=r.relation_type, target_id=_graph_target(state, payload, r.target)
                )
                for r in payload.result.relations
                if r.source.local_id == local_id
            ),
            key=lambda rel: (rel.relation_type.value, rel.target_id),
        )
    )
    fields: dict[str, object] = {
        "id": identity.object_id(node.kind, local_id),
        "project_id": identity.project_id,
        "authority": authority,
        "confidence": node.confidence,
        "provenance": provenance,
        "created_at": event.occurred_at,
        "scope": (payload.run_scope,),
        "relations": relations,
    }
    if isinstance(node, IntentNodeProposal):
        fields["mission"] = node.mission
    else:
        fields["statement"] = node.statement
    if isinstance(node, ConstraintNodeProposal):
        fields["facet"] = node.facet
    if isinstance(node, DecisionNodeProposal):
        fields["rationale"] = node.decision_rationale
    if isinstance(node, RequirementNodeProposal):
        fields.update(
            materiality=Materiality.LOW, requires_metric=False, requires_verification=False
        )
    if isinstance(node, AssumptionNodeProposal):
        stated = node.proposed_risk_level if author.is_human else None
        fields["risk_level"] = stated if stated is not None else RiskLevel.HIGH
    return _GRAPH_CLASSES[node.kind].model_validate(fields)


def _graph_bind_object(obj: SemanticObject, expected: SemanticObject) -> None:
    """Each binding is its own named check, so none can be quietly subsumed by another."""
    if obj.id != expected.id or obj.project_id != expected.project_id:
        raise _graph_fail("BINDING_OBJECT_ID", f"{obj.id!r} is not {expected.id!r}")
    if obj.kind is not expected.kind or type(obj) is not type(expected):
        raise _graph_fail("BINDING_KIND", f"{obj.id!r} is {obj.kind}, the node is {expected.kind}")
    for text_field in ("mission", "statement", "facet", "rationale"):
        if getattr(obj, text_field, None) != getattr(expected, text_field, None):
            raise _graph_fail("BINDING_TEXT", f"{obj.id!r} {text_field} differs from the node")
    if getattr(obj, "risk_level", None) != getattr(expected, "risk_level", None):
        raise _graph_fail("BINDING_RISK", f"{obj.id!r} risk differs from the runtime risk law")
    if obj.confidence != expected.confidence:
        raise _graph_fail("BINDING_CONFIDENCE", f"{obj.id!r} confidence differs from the node")
    if obj.authority is not expected.authority:
        raise _graph_fail("BINDING_AUTHORITY", f"{obj.id!r} authority differs from its assignment")
    if tuple(obj.scope) != tuple(expected.scope):
        raise _graph_fail("BINDING_SCOPE", f"{obj.id!r} scope is not the run scope")
    if obj.provenance != expected.provenance:
        raise _graph_fail("BINDING_PROVENANCE", f"{obj.id!r} provenance does not bind the author")
    if obj.created_at != expected.created_at:
        raise _graph_fail("BINDING_CREATED_AT", f"{obj.id!r} created_at is not the event time")
    if obj.lifecycle is not LifecycleStatus.ACTIVE or obj.revision != 1:
        raise _graph_fail("BINDING_LIFECYCLE", f"{obj.id!r} must arrive ACTIVE at revision 1")
    if list(obj.relations) != list(expected.relations):
        raise _graph_fail("BINDING_RELATIONS", f"{obj.id!r} relations differ from the proposal")
    residual = obj.model_dump(exclude=set(_GRAPH_BOUND_FIELDS))
    if residual != expected.model_dump(exclude=set(_GRAPH_BOUND_FIELDS)):
        raise _graph_fail("BINDING_FIELDS", f"{obj.id!r} carries fields the node does not imply")


def _graph_expected_gaps(
    state: IntentState, payload: IntentGraphSynthesisDecidedPayload
) -> list[IntentGraphGap]:
    identity = payload.identity
    gaps: list[IntentGraphGap] = []
    for proposal in payload.result.gaps:
        object_ids: set[str] = set()
        claim_ids: set[str] = set()
        for anchor in proposal.anchors:
            target = _graph_target(state, payload, anchor)
            (claim_ids if isinstance(anchor, BasisClaimRef) else object_ids).add(target)
        gaps.append(
            IntentGraphGap(
                id=identity.gap_id(proposal.local_gap_id),
                project_id=identity.project_id,
                kind=proposal.kind,
                description=proposal.description,
                materiality=None,
                risk=None,
                affected_object_ids=tuple(sorted(object_ids)),
                blocking=True,
                scope=(payload.run_scope,),
                confidence=proposal.confidence,
                affected_claim_ids=tuple(sorted(claim_ids)),
                model_gap_proposal_id=proposal.local_gap_id,
                missing_need=proposal.missing_need,
            )
        )
    return sorted(gaps, key=lambda g: g.id)


def _graph_check_retirement(
    state: IntentState,
    payload: IntentGraphSynthesisDecidedPayload,
    retired_object_id: str,
    replacement: SemanticObject,
    stale_ids: frozenset[str],
) -> SemanticObject:
    target = state.objects.get(retired_object_id)
    if target is None:
        raise _graph_fail("REPLACEMENT_TARGET_MISSING", f"{retired_object_id!r} is not in state")
    if not object_is_current(target):
        raise _graph_fail("REPLACEMENT_TARGET_NOT_CURRENT", f"{target.id!r} is no longer current")
    if target.kind is not replacement.kind:
        raise _graph_fail("REPLACEMENT_KIND_MISMATCH", f"{target.id!r} is a {target.kind}")
    if target.kind in _GRAPH_UNREPLACEABLE:
        raise _graph_fail("REPLACEMENT_FORBIDDEN_KIND", f"a {target.kind} is never replaced")
    if any(r.retired_object_id == target.id for r in state.intent_synthesis.retirements):
        raise _graph_fail("REPLACEMENT_ALREADY_RETIRED", f"{target.id!r} is already retired")
    if target.id not in stale_ids:
        raise _graph_fail("REPLACEMENT_NOT_STALE", f"{target.id!r} is not stale at this sequence")
    if not replacement_scope_covers((payload.run_scope,), tuple(target.scope)):
        raise _graph_fail(
            "REPLACEMENT_SCOPE_NOT_COVERED", f"run scope does not cover {target.id!r}"
        )
    if target.authority is Authority.CANONICAL and replacement.authority is not Authority.CANONICAL:
        raise _graph_fail("CANONICAL_REPLACEMENT_REQUIRED", f"{target.id!r} is canonical")
    return target


def _reduce_graph_decided(state: IntentState, event: EventEnvelope) -> _GraphEffect:
    payload = event.payload
    if not isinstance(payload, IntentGraphSynthesisDecidedPayload):
        raise ValueError(
            "INTENT_GRAPH_SYNTHESIS_DECIDED requires IntentGraphSynthesisDecidedPayload"
        )
    identity = payload.identity
    if identity.project_id != state.project_id:
        raise _graph_fail("BINDING_IDENTITY", "graph identity names another project")
    expected_event_id = graph_decision_event_id(identity)
    if event.event_id != expected_event_id:
        raise _graph_fail("GRAPH_EVENT_ID", f"{event.event_id!r} is not {expected_event_id!r}")
    graph_id = identity.graph_instance_id
    if graph_id in state.intent_graph_synthesis.decisions:
        raise ValueError(f"graph {graph_id} already has a durable decision")

    result = payload.result
    compiled = payload.compiled
    if (
        len(result.nodes) > MAX_GRAPH_NODES
        or len(result.relations) > MAX_GRAPH_RELATIONS
        or len(result.gaps) > MAX_GRAPH_GAPS
        or (compiled is not None and len(compiled.objects) > MAX_GRAPH_NODES)
        or (compiled is not None and len(compiled.gaps) > MAX_GRAPH_GAPS)
    ):
        raise _graph_fail("MAX_GRAPH", "a graph cap is exceeded; nothing is applied")

    # The shared shape law, checked directly so every binding below runs before the record is
    # built: APPLY iff compiled, the compiled identity, and one assignment per node.
    try:
        validate_graph_decision_shape(
            identity=identity,
            result=result,
            node_assignments=payload.node_assignments,
            decision=payload.decision,
            compiled=compiled,
        )
    except ValueError as exc:
        raise _graph_fail("GRAPH_SHAPE", str(exc)) from exc
    is_apply = payload.decision.route is IntentSynthesisRoute.APPLY
    for assignment in payload.node_assignments:
        if assignment.origin is SynthesisOrigin.DETERMINISTIC_NORMALIZATION:
            raise _graph_fail("UNSUPPORTED_ORIGIN", "DETERMINISTIC_NORMALIZATION is unsupported")
        if (assignment.origin is SynthesisOrigin.HUMAN_STATED) is not payload.author.is_human:
            raise _graph_fail(
                "ORIGIN_AUTHOR_MISMATCH", f"{assignment.local_id!r}: origin follows the author"
            )
        if is_apply and assignment.authority not in _GRAPH_ASSIGNABLE:
            raise _graph_fail("INVALID_ASSIGNED_AUTHORITY", f"{assignment.local_id!r}")
        if (
            is_apply
            and assignment.origin in _GRAPH_NON_HUMAN
            and assignment.authority is Authority.CANONICAL
        ):
            raise _graph_fail("AUTHORITY_INVENTION", f"{assignment.local_id!r} is non-human")

    # R111: NO_CHANGE is exactly "witnesses only". It carries no node, relation, gap or compiled
    # graph, and at least one witness.
    if payload.decision.route is IntentSynthesisRoute.NO_CHANGE and (
        result.nodes or result.relations or result.gaps or not result.unchanged_object_refs
    ):
        raise _graph_fail(
            "NO_CHANGE_SHAPE",
            "a NO_CHANGE graph carries only unchanged_object_refs, and at least one",
        )
    # Witnesses are integrity-checked on every route: each must exist, be current and not be
    # stale where the event lands. Semantic sameness is never re-judged here.
    if result.unchanged_object_refs:
        witness_stale = frozenset(derive_intent_view(state).stale_ids)
        for ref in result.unchanged_object_refs:
            witness = state.objects.get(ref.object_id)
            if witness is None or not object_is_current(witness):
                raise _graph_fail(
                    "UNCHANGED_REF_UNAVAILABLE", f"{ref.object_id!r} is missing or not current"
                )
            if witness.id in witness_stale:
                raise _graph_fail("UNCHANGED_REF_STALE", f"{ref.object_id!r} is stale")

    def decided() -> IntentGraphSynthesisState:
        record = IntentGraphDecisionRecord(
            identity=identity,
            author=payload.author,
            run_scope=payload.run_scope,
            result=result,
            node_assignments=payload.node_assignments,
            decision=payload.decision,
            compiled=compiled,
            decision_event_id=event.event_id,
            decided_at=event.occurred_at,
        )
        return IntentGraphSynthesisState(
            decisions={**dict(state.intent_graph_synthesis.decisions), graph_id: record}
        )

    if not is_apply:
        # The decision is the whole outcome: no object, edge, gap or retirement.
        return _GraphEffect(
            objects=dict(state.objects),
            gaps=dict(state.gaps),
            semantic=state.semantic,
            intent_synthesis=state.intent_synthesis,
            intent_graph_synthesis=decided(),
        )
    assert compiled is not None  # the shape law above guarantees it

    nodes = {n.local_id.local_id: n for n in result.nodes}
    for relation in result.relations:
        _graph_target(state, payload, relation.source)
        _graph_target(state, payload, relation.target)
    expected_mapping = tuple(
        sorted((lid, identity.object_id(node.kind, lid)) for lid, node in nodes.items())
    )
    if compiled.local_to_object_id != expected_mapping:
        raise _graph_fail(
            "BINDING_MAPPING", "local -> object ids do not re-derive from the identity"
        )
    object_by_local = dict(compiled.local_to_object_id)
    compiled_ids = [obj.id for obj in compiled.objects]
    if len(set(compiled_ids)) != len(compiled_ids) or sorted(compiled_ids) != sorted(
        object_by_local.values()
    ):
        raise _graph_fail("BINDING_OBJECT_SET", "compiled objects are not exactly one per node")

    authority_by_local = {a.local_id: a.authority for a in payload.node_assignments}
    by_id = {obj.id: obj for obj in compiled.objects}
    for local_id in sorted(nodes):
        authority = authority_by_local[local_id]
        assert authority is not None  # APPLY assignments were checked above
        expected = _graph_expected_object(state, payload, event, nodes[local_id], authority)
        _graph_bind_object(by_id[object_by_local[local_id]], expected)

    if [p.object_id for p in compiled.derivation_parents] != compiled_ids:
        raise _graph_fail("BINDING_DERIVATION", "derivation parents do not cover every object")
    for parents in compiled.derivation_parents:
        derived = tuple(
            sorted(
                {
                    r.target_id
                    for r in by_id[parents.object_id].relations
                    if r.relation_type is RelationType.DERIVED_FROM
                }
            )
        )
        if parents.parent_ids != derived:
            raise _graph_fail(
                "BINDING_DERIVATION", f"{parents.object_id!r} parents differ from DERIVED_FROM"
            )

    expected_gaps = _graph_expected_gaps(state, payload)
    if list(compiled.gaps) != expected_gaps:
        raise _graph_fail("BINDING_GAP", "compiled gaps differ from the proposed gaps")

    expected_retirements = sorted(
        (replaced.object_id, object_by_local[lid], identity.node_instance_id(lid))
        for lid, node in nodes.items()
        if node.disposition is GraphNodeDisposition.REPLACES_STALE
        and (replaced := node.replaces) is not None
    )
    actual_retirements = sorted(
        (r.retired_object_id, r.replaced_by_object_id, r.node_instance_id)
        for r in compiled.retirements
    )
    if actual_retirements != expected_retirements:
        raise _graph_fail("BINDING_RETIREMENT", "retirements differ from the replacing nodes")
    retired_ids = [r.retired_object_id for r in compiled.retirements]
    if len(set(retired_ids)) != len(retired_ids):
        raise _graph_fail("REPLACEMENT_TWICE", "one target is retired twice")

    objects = dict(state.objects)
    for obj in compiled.objects:
        if obj.id in objects:
            raise _graph_fail("OBJECT_ALREADY_EXISTS", f"{obj.id!r} already exists")
    gaps: dict[str, Gap | IntentSynthesisGap] = dict(state.gaps)
    for new_gap in compiled.gaps:
        if new_gap.id in gaps:
            raise _graph_fail("GAP_ALREADY_EXISTS", f"gap {new_gap.id!r} already exists")

    stale_ids = (
        frozenset(derive_intent_view(state).stale_ids) if compiled.retirements else frozenset()
    )
    retired: list[SemanticObject] = [
        _graph_check_retirement(
            state, payload, r.retired_object_id, by_id[r.replaced_by_object_id], stale_ids
        )
        for r in compiled.retirements
    ]

    # Built last: its structural validators are the final net, never the first check.
    graph_state = decided()

    # One transition: every object, edge, gap, retirement and the decision, or none of them.
    for obj in compiled.objects:
        objects[obj.id] = obj
    for target in retired:
        objects[target.id] = target.model_copy(
            update={"lifecycle": LifecycleStatus.SUPERSEDED, "revision": target.revision + 1}
        )
    for new_gap in compiled.gaps:
        gaps[new_gap.id] = new_gap
    edges = tuple(
        DerivationEdge(
            child_id=parents.object_id, parent_id=parent_id, recorded_by_event_id=event.event_id
        )
        for parents in compiled.derivation_parents
        for parent_id in parents.parent_ids
    )
    semantic = SemanticState.model_validate(
        {**dict(state.semantic), "derivations": (*state.semantic.derivations, *edges)}
    )
    intent_synthesis = _synthesis_updated(
        state.intent_synthesis,
        retirements=(
            *state.intent_synthesis.retirements,
            *(
                RetirementRecord(
                    retired_object_id=r.retired_object_id,
                    replaced_by_object_id=r.replaced_by_object_id,
                    proposal_instance_id=r.node_instance_id,
                    recorded_by_event_id=event.event_id,
                )
                for r in compiled.retirements
            ),
        ),
    )
    return _GraphEffect(
        objects=objects,
        gaps=gaps,
        semantic=semantic,
        intent_synthesis=intent_synthesis,
        intent_graph_synthesis=graph_state,
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
    intent_graph_synthesis = state.intent_graph_synthesis

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
            | EventType.STRUCTURAL_REFUSAL_RECORDED
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
        case EventType.INTENT_OBJECT_ADMITTED:
            payload = event.payload
            if not isinstance(payload, IntentObjectAdmissionPayload):
                raise ValueError("INTENT_OBJECT_ADMITTED requires IntentObjectAdmissionPayload")
            if payload.object.id in state.objects:
                # Admission creates; it never revises. The shared object case below assigns
                # straight into the mapping, which for an admission would be revision by
                # dictionary assignment -- supersession without a supersession record.
                raise ValueError(
                    f"INTENT_OBJECT_ADMITTED may not overwrite existing object "
                    f"{payload.object.id!r}; revision is an explicit operation"
                )
            # One indivisible application: the object and exactly the edges the event names.
            # Parents come from immutable payload data, never recomputed from whichever
            # relations currently imply derivation, so replay cannot drift with the rules.
            objects[payload.object.id] = payload.object
            semantic = SemanticState.model_validate(
                {
                    **dict(state.semantic),
                    "derivations": (
                        *state.semantic.derivations,
                        *(
                            DerivationEdge(
                                child_id=payload.object.id,
                                parent_id=parent_id,
                                recorded_by_event_id=event.event_id,
                            )
                            for parent_id in payload.derivation_parent_ids
                        ),
                    ),
                }
            )
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
        case EventType.INTENT_GRAPH_SYNTHESIS_DECIDED:
            effect = _reduce_graph_decided(state, event)
            objects = effect.objects
            gaps = effect.gaps
            semantic = effect.semantic
            intent_synthesis = effect.intent_synthesis
            intent_graph_synthesis = effect.intent_graph_synthesis

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
        intent_graph_synthesis=intent_graph_synthesis,
    )

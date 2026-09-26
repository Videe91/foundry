"""Deterministic compilation of a validated Intent Graph (IE3 Slice 1).

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§8, §13, §14, §16,
§17, §25; R100-R104; Q1, Q2, Q5).

``compile_intent_graph`` turns one validated graph into the real ``SemanticObject``s, the
retirement plan and the gaps a later durable transition would apply. Its runtime-owned inputs are
explicit parameters: identity, author, decision time, decision event id, the run scope (carried
by the visibility surface) and a per-node origin and assigned authority. Nothing is read from a
clock, a store or a model.

It writes nothing. There is no event, no reducer transition and no state change in Slice 1;
``hypothetical_state`` is a pure projection so the compiled graph can be judged *as a whole*.
``assert_compiled_graph_lawful`` then runs the unchanged IE2 laws over that projection. Checked
one object at a time against current state, a same-batch reference could never resolve (F9).

Runtime law applied here, never by the proposer:

* ids are ``IntentGraphIdentity`` digests of ``(project, run, local id, kind)``; output order is
  canonical, so node input order changes nothing;
* scope is ``(run scope,)`` for every node and gap (Q2). Basis claim addresses and referenced
  objects never widen or narrow it;
* confidence is carried exactly, and ``None`` stays ``None`` (Q1);
* a non-human Assumption is ``HIGH`` whatever was proposed. A human's explicit risk level is kept,
  and a silent human gets ``HIGH`` (Q5);
* Requirement pins inherit Slice-1: ``LOW``, no metric, no verification (D3/D4 stay open);
* authority is exactly the runtime assignment. A non-human origin may never be assigned
  ``CANONICAL`` (R102), defended here as well as in routing.

Pure domain: no I/O, no clock, no randomness, no provider import.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from pydantic import Field

from foundry.domain.basis import assert_lawful_basis
from foundry.domain.common import (
    Authority,
    FrozenModel,
    LifecycleStatus,
    Materiality,
    Provenance,
    Relation,
    RiskLevel,
    SourceKind,
)
from foundry.domain.graph_cycles import assert_no_cycle_introduced
from foundry.domain.intent_graph import (
    AssumptionNodeProposal,
    ConstraintNodeProposal,
    DecisionNodeProposal,
    ExistingObjectRef,
    GoalNodeProposal,
    GraphGapProposal,
    GraphNodeDisposition,
    GraphNodeProposal,
    GraphRef,
    IntentGraphGap,
    IntentGraphIdentity,
    IntentGraphSynthesisResult,
    IntentNodeProposal,
    LocalNodeRef,
    NonGoalNodeProposal,
    OutcomeNodeProposal,
    PreferenceNodeProposal,
    RequirementNodeProposal,
)
from foundry.domain.intent_graph_validation import GraphVisibility, validate_intent_graph
from foundry.domain.intent_synthesis import SynthesisOrigin, replacement_scope_covers
from foundry.domain.relation_legality import validate_relations
from foundry.domain.relevance import assert_relevant
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
    SemanticObject,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint

if TYPE_CHECKING:
    from foundry.domain.state import IntentState

__all__ = [
    "ASSIGNABLE_AUTHORITIES",
    "CompiledIntentGraph",
    "IntentGraphCompilationError",
    "NodeAssignment",
    "RetirementPlanEntry",
    "assert_compiled_graph_lawful",
    "compile_intent_graph",
    "hypothetical_state",
]

ASSIGNABLE_AUTHORITIES: Final[frozenset[Authority]] = frozenset(
    {Authority.CANONICAL, Authority.PROPOSED}
)
"""What routing may assign to a synthesized node, as in Slice-1. Anything else is a bug."""

_NON_HUMAN_ORIGINS: Final = frozenset(
    {SynthesisOrigin.AI_INFERRED, SynthesisOrigin.RESEARCH_DERIVED}
)

_REQUIREMENT_MATERIALITY: Final = Materiality.LOW
_NON_HUMAN_ASSUMPTION_RISK: Final = RiskLevel.HIGH


class IntentGraphCompilationError(ValueError):
    """The graph cannot be compiled or projected. Nothing about it may be applied."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class NodeAssignment(FrozenModel):
    """Runtime's decision for one node: who it came from and what authority it gets."""

    origin: SynthesisOrigin
    authority: Authority


class RetirementPlanEntry(FrozenModel):
    """One planned retirement. Slice 1 plans it; a later durable transition records it."""

    retired_object_id: str = Field(min_length=1)
    replaced_by_object_id: str = Field(min_length=1)
    node_instance_id: str = Field(min_length=1)


class CompiledIntentGraph(FrozenModel):
    """Everything one graph would durably mean, canonically ordered."""

    identity: IntentGraphIdentity
    objects: tuple[SemanticObject, ...]
    local_to_object_id: tuple[tuple[str, str], ...]
    retirements: tuple[RetirementPlanEntry, ...] = ()
    gaps: tuple[IntentGraphGap, ...] = ()


# --------------------------------------------------------------------------- compile


def _check_assignments(
    result: IntentGraphSynthesisResult,
    author: ReasonerFingerprint,
    assignments: Mapping[str, NodeAssignment],
) -> None:
    node_ids = {n.local_id.local_id for n in result.nodes}
    if set(assignments) != node_ids:
        raise IntentGraphCompilationError(
            "ASSIGNMENT_MISMATCH",
            f"assignments name {sorted(assignments)} but the graph has nodes {sorted(node_ids)}",
        )
    for local_id in sorted(assignments):
        assignment = assignments[local_id]
        if assignment.origin is SynthesisOrigin.DETERMINISTIC_NORMALIZATION:
            raise IntentGraphCompilationError(
                "UNSUPPORTED_ORIGIN", "DETERMINISTIC_NORMALIZATION is unsupported (F24)"
            )
        expected_human = assignment.origin is SynthesisOrigin.HUMAN_STATED
        if expected_human is not author.is_human:
            raise IntentGraphCompilationError(
                "ORIGIN_AUTHOR_MISMATCH",
                f"{local_id!r} carries origin {assignment.origin.value} but the author is "
                f"{'human' if author.is_human else 'non-human'}; origin follows the author",
            )
        if assignment.authority not in ASSIGNABLE_AUTHORITIES:
            raise IntentGraphCompilationError(
                "INVALID_ASSIGNED_AUTHORITY",
                f"{local_id!r} was assigned {assignment.authority.value}",
            )
        if assignment.origin in _NON_HUMAN_ORIGINS and assignment.authority is Authority.CANONICAL:
            raise IntentGraphCompilationError(
                "AUTHORITY_INVENTION",
                f"{local_id!r} is {assignment.origin.value} and may not be CANONICAL; model "
                "capability never grants authority",
            )


def _provenance(
    identity: IntentGraphIdentity, author: ReasonerFingerprint, decision_event_id: str
) -> Provenance:
    if author.is_human:
        return Provenance(
            source_kind=SourceKind.HUMAN,
            source_ref=author.model,
            source_event_ids=(decision_event_id,),
        )
    # SYSTEM, never RESEARCH: research-derivedness is a property of the basis, and recording it
    # as the object's own source would let basis provenance elevate the author (Slice-1 rule).
    return Provenance(
        source_kind=SourceKind.SYSTEM,
        source_ref=identity.synthesis_run_id,
        source_event_ids=(decision_event_id,),
    )


def _assumption_risk(node: AssumptionNodeProposal, author: ReasonerFingerprint) -> RiskLevel:
    if author.is_human and node.proposed_risk_level is not None:
        return node.proposed_risk_level
    return _NON_HUMAN_ASSUMPTION_RISK


def _build(
    node: GraphNodeProposal,
    *,
    object_id: str,
    common: dict[str, object],
    relations: tuple[Relation, ...],
    author: ReasonerFingerprint,
) -> SemanticObject:
    fields = {**common, "id": object_id, "relations": relations, "confidence": node.confidence}
    if isinstance(node, IntentNodeProposal):
        return Intent.model_validate({**fields, "mission": node.mission})
    if isinstance(node, GoalNodeProposal):
        return Goal.model_validate({**fields, "statement": node.statement})
    if isinstance(node, OutcomeNodeProposal):
        return Outcome.model_validate({**fields, "statement": node.statement})
    if isinstance(node, RequirementNodeProposal):
        return Requirement.model_validate(
            {
                **fields,
                "statement": node.statement,
                "materiality": _REQUIREMENT_MATERIALITY,
                "requires_metric": False,
                "requires_verification": False,
            }
        )
    if isinstance(node, ConstraintNodeProposal):
        return Constraint.model_validate(
            {**fields, "statement": node.statement, "facet": node.facet}
        )
    if isinstance(node, NonGoalNodeProposal):
        return NonGoal.model_validate({**fields, "statement": node.statement})
    if isinstance(node, PreferenceNodeProposal):
        return Preference.model_validate({**fields, "statement": node.statement})
    if isinstance(node, DecisionNodeProposal):
        return ProjectDecision.model_validate(
            {**fields, "statement": node.statement, "rationale": node.decision_rationale}
        )
    return Assumption.model_validate(
        {**fields, "statement": node.statement, "risk_level": _assumption_risk(node, author)}
    )


def _retirement(
    node: GraphNodeProposal,
    *,
    visibility: GraphVisibility,
    identity: IntentGraphIdentity,
    object_id: str,
    authority: Authority,
) -> RetirementPlanEntry | None:
    if node.disposition is not GraphNodeDisposition.REPLACES_STALE:
        return None
    assert node.replaces is not None  # the node validator guarantees it
    target = visibility.get(node.replaces.object_id)
    assert target is not None  # validation resolved it
    local_id = node.local_id.local_id
    # C11: one equality check; no Authority ordering is introduced.
    if target.authority is Authority.CANONICAL and authority is not Authority.CANONICAL:
        raise IntentGraphCompilationError(
            "CANONICAL_REPLACEMENT_REQUIRED",
            f"{local_id!r} would retire canonical {target.object_id!r} with {authority.value}",
        )
    # C21: a narrower replacement must not delete broader intent.
    if not replacement_scope_covers((visibility.run_scope,), tuple(target.scope)):
        raise IntentGraphCompilationError(
            "REPLACEMENT_SCOPE_NOT_COVERED",
            f"run scope {visibility.run_scope!r} does not cover {target.object_id!r} scope "
            f"{tuple(target.scope)}",
        )
    return RetirementPlanEntry(
        retired_object_id=target.object_id,
        replaced_by_object_id=object_id,
        node_instance_id=identity.node_instance_id(local_id),
    )


def _gap(
    proposal: GraphGapProposal,
    *,
    identity: IntentGraphIdentity,
    run_scope: str,
    resolve: dict[str, str],
) -> IntentGraphGap:
    object_ids: set[str] = set()
    claim_ids: set[str] = set()
    for anchor in proposal.anchors:
        if isinstance(anchor, LocalNodeRef):
            object_ids.add(resolve[anchor.local_id])
        elif isinstance(anchor, ExistingObjectRef):
            object_ids.add(anchor.object_id)
        else:
            claim_ids.add(anchor.claim_id)
    return IntentGraphGap(
        id=identity.gap_id(proposal.local_gap_id),
        project_id=identity.project_id,
        kind=proposal.kind,
        description=proposal.description,
        materiality=None,
        risk=None,
        affected_object_ids=tuple(sorted(object_ids)),
        blocking=True,
        scope=(run_scope,),
        confidence=proposal.confidence,
        affected_claim_ids=tuple(sorted(claim_ids)),
        model_gap_proposal_id=proposal.local_gap_id,
        missing_need=proposal.missing_need,
    )


def compile_intent_graph(
    result: IntentGraphSynthesisResult,
    visibility: GraphVisibility,
    *,
    identity: IntentGraphIdentity,
    author: ReasonerFingerprint,
    decided_at: datetime,
    decision_event_id: str,
    assignments: Mapping[str, NodeAssignment],
) -> CompiledIntentGraph:
    """Validate, then compile ``result`` into canonically ordered domain objects."""
    if not decision_event_id:
        raise ValueError("decision_event_id must be non-empty")
    validate_intent_graph(result, visibility, author_is_human=author.is_human)
    _check_assignments(result, author, assignments)

    nodes = sorted(result.nodes, key=lambda n: n.local_id.local_id)
    resolve = {n.local_id.local_id: identity.object_id(n.kind, n.local_id.local_id) for n in nodes}

    def target_id(ref: GraphRef) -> str:
        if isinstance(ref, LocalNodeRef):
            return resolve[ref.local_id]
        if isinstance(ref, ExistingObjectRef):
            return ref.object_id
        return ref.claim_id

    provenance = _provenance(identity, author, decision_event_id)
    objects: list[SemanticObject] = []
    retirements: list[RetirementPlanEntry] = []
    for node in nodes:
        local_id = node.local_id.local_id
        assignment = assignments[local_id]
        relations = tuple(
            sorted(
                (
                    Relation(relation_type=r.relation_type, target_id=target_id(r.target))
                    for r in result.relations
                    if r.source.local_id == local_id
                ),
                key=lambda rel: (rel.relation_type.value, rel.target_id),
            )
        )
        common: dict[str, object] = {
            "project_id": identity.project_id,
            "authority": assignment.authority,
            "provenance": provenance,
            "created_at": decided_at,
            "scope": (visibility.run_scope,),
            "revision": 1,
            "lifecycle": LifecycleStatus.ACTIVE,
        }
        objects.append(
            _build(
                node, object_id=resolve[local_id], common=common, relations=relations, author=author
            )
        )
        planned = _retirement(
            node,
            visibility=visibility,
            identity=identity,
            object_id=resolve[local_id],
            authority=assignment.authority,
        )
        if planned is not None:
            retirements.append(planned)

    gaps = [
        _gap(g, identity=identity, run_scope=visibility.run_scope, resolve=resolve)
        for g in result.gaps
    ]
    return CompiledIntentGraph(
        identity=identity,
        objects=tuple(sorted(objects, key=lambda o: o.id)),
        local_to_object_id=tuple(sorted(resolve.items())),
        retirements=tuple(sorted(retirements, key=lambda r: r.retired_object_id)),
        gaps=tuple(sorted(gaps, key=lambda g: g.id)),
    )


# --------------------------------------------------------------------------- hypothetical state


def hypothetical_state(state: IntentState, compiled: CompiledIntentGraph) -> IntentState:
    """``state`` as it would read if ``compiled`` were applied. Pure: ``state`` is untouched.

    No event, sequence or source is recorded: this is a judgement surface, never a ledger.
    """
    if compiled.identity.project_id != state.project_id:
        raise IntentGraphCompilationError(
            "PROJECT_MISMATCH",
            f"graph project {compiled.identity.project_id!r} is not state project "
            f"{state.project_id!r}",
        )
    objects = dict(state.objects)
    for obj in compiled.objects:
        if obj.id in objects:
            raise IntentGraphCompilationError(
                "OBJECT_ALREADY_EXISTS", f"{obj.id!r} already exists; a graph only creates"
            )
        objects[obj.id] = obj
    for entry in compiled.retirements:
        target = objects.get(entry.retired_object_id)
        if target is None:
            raise IntentGraphCompilationError(
                "RETIREMENT_TARGET_MISSING", f"{entry.retired_object_id!r} is not in state"
            )
        objects[target.id] = target.model_copy(
            update={"lifecycle": LifecycleStatus.SUPERSEDED, "revision": target.revision + 1}
        )
    gaps = dict(state.gaps)
    for compiled_gap in compiled.gaps:
        if compiled_gap.id in gaps:
            raise IntentGraphCompilationError(
                "OBJECT_ALREADY_EXISTS", f"gap {compiled_gap.id!r} already exists"
            )
        gaps[compiled_gap.id] = compiled_gap
    return state.model_copy(
        update={"objects": MappingProxyType(objects), "gaps": MappingProxyType(gaps)}
    )


def assert_compiled_graph_lawful(state: IntentState, compiled: CompiledIntentGraph) -> None:
    """The unchanged IE2 laws, over the whole graph at once. Never restated here.

    Legality and acyclicity hold for every node. Basis and relevance are canonical-only, exactly
    as at the IE2 seam, so a proposed node is not held to a law its authority does not reach.
    """
    projected = hypothetical_state(state, compiled)
    for obj in compiled.objects:
        validate_relations(projected, obj)
        assert_no_cycle_introduced(projected, obj)
        if obj.authority is Authority.CANONICAL:
            assert_lawful_basis(projected, obj)
            assert_relevant(projected, obj)

"""Shared builders for the IE3 Slice-1 graph tests.

Thin on purpose, as in the IE2 fixtures: the tests are about the rules, so every builder
produces the real typed proposal and nothing more. Runtime-owned inputs (identity, author,
decision time, assignments) are spelled out here once so each test states only what it varies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from foundry.domain.common import Authority, Relation, RelationType
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import (
    AssumptionNodeProposal,
    BasisClaimRef,
    ConstraintNodeProposal,
    DecisionNodeProposal,
    ExistingObjectRef,
    GoalNodeProposal,
    GraphGapProposal,
    GraphNodeProposal,
    GraphRef,
    GraphRelationProposal,
    IntentGraphIdentity,
    IntentGraphSynthesisResult,
    IntentNodeProposal,
    LocalNodeRef,
    MissingNeed,
    NonGoalNodeProposal,
    OutcomeNodeProposal,
    PreferenceNodeProposal,
    RequirementNodeProposal,
)
from foundry.domain.intent_graph_compiler import NodeAssignment
from foundry.domain.intent_graph_validation import GraphVisibility, VisibleObject
from foundry.domain.intent_synthesis import SynthesisOrigin
from foundry.domain.semantic import ConstraintFacet, SemanticKind
from tests.unit._ie21_fixtures import ALICE, HUMAN, MODEL, PROJECT, SCOPE

__all__ = [
    "ALICE",
    "DECIDED_AT",
    "DECISION_EVENT_ID",
    "HUMAN",
    "IDENTITY",
    "MODEL",
    "PROJECT",
    "RUN",
    "SCOPE",
    "assign",
    "b",
    "e",
    "edge",
    "gap",
    "local",
    "node",
    "result",
    "visible",
    "visibility",
]

RUN = "RUN-ie3-1"
IDENTITY = IntentGraphIdentity(project_id=PROJECT, synthesis_run_id=RUN)
DECIDED_AT = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
DECISION_EVENT_ID = "EVT-graph-decided"


def local(local_id: str) -> LocalNodeRef:
    return LocalNodeRef(local_id=local_id)


def e(object_id: str) -> ExistingObjectRef:
    return ExistingObjectRef(object_id=object_id)


def b(claim_id: str) -> BasisClaimRef:
    return BasisClaimRef(claim_id=claim_id)


_TEXT = {
    SemanticKind.GOAL: "Refunds settle quickly.",
    SemanticKind.OUTCOME: "Refunds settle within a month.",
    SemanticKind.REQUIREMENT: "Refunds complete within thirty days.",
    SemanticKind.CONSTRAINT: "Refund data stays in the EU.",
    SemanticKind.NON_GOAL: "We will not store card numbers.",
    SemanticKind.PREFERENCE: "Prefer boring technology.",
    SemanticKind.DECISION: "We chose PostgreSQL.",
    SemanticKind.ASSUMPTION: "Customers have an email address.",
}


def node(kind: SemanticKind, local_id: str, **overrides: Any) -> GraphNodeProposal:
    """The real typed variant for ``kind``; required meaning fields get plausible defaults."""
    fields: dict[str, Any] = {
        "local_id": local(local_id),
        "proposal_rationale": "stated in the discovery session",
    }
    if kind is SemanticKind.INTENT:
        fields["mission"] = "Refunds are predictable."
    else:
        fields["statement"] = _TEXT[kind]
    if kind is SemanticKind.CONSTRAINT:
        fields["facet"] = ConstraintFacet.PROJECT_BOUNDARY
    if kind is SemanticKind.DECISION:
        fields["decision_rationale"] = "Operational familiarity."
    fields.update(overrides)
    variant = {
        SemanticKind.INTENT: IntentNodeProposal,
        SemanticKind.GOAL: GoalNodeProposal,
        SemanticKind.OUTCOME: OutcomeNodeProposal,
        SemanticKind.REQUIREMENT: RequirementNodeProposal,
        SemanticKind.CONSTRAINT: ConstraintNodeProposal,
        SemanticKind.NON_GOAL: NonGoalNodeProposal,
        SemanticKind.PREFERENCE: PreferenceNodeProposal,
        SemanticKind.DECISION: DecisionNodeProposal,
        SemanticKind.ASSUMPTION: AssumptionNodeProposal,
    }[kind]
    return variant(**fields)


def edge(source: str, relation_type: RelationType, target: GraphRef | str) -> GraphRelationProposal:
    """A relation from local ``source``; a bare string target means another local node."""
    resolved = local(target) if isinstance(target, str) else target
    return GraphRelationProposal(source=local(source), relation_type=relation_type, target=resolved)


def gap(
    local_gap_id: str = "g1",
    *,
    kind: GapKind = GapKind.AMBIGUITY,
    anchors: tuple[GraphRef, ...] = (),
    missing_need: MissingNeed = MissingNeed.UNDETERMINED,
    **overrides: Any,
) -> GraphGapProposal:
    fields: dict[str, Any] = {
        "local_gap_id": local_gap_id,
        "kind": kind,
        "description": "Which refund window applies to marketplace sellers is unclear.",
        "missing_need": missing_need,
        "blocking": True,
        "anchors": anchors,
    }
    fields.update(overrides)
    return GraphGapProposal(**fields)


def result(
    *nodes: GraphNodeProposal,
    relations: tuple[GraphRelationProposal, ...] = (),
    gaps: tuple[GraphGapProposal, ...] = (),
) -> IntentGraphSynthesisResult:
    return IntentGraphSynthesisResult(nodes=nodes, relations=relations, gaps=gaps)


def visible(
    object_id: str,
    kind: SemanticKind,
    *,
    authority: Authority = Authority.CANONICAL,
    is_current: bool = True,
    is_stale: bool = False,
    scope: tuple[str, ...] = (SCOPE,),
    relations: tuple[tuple[RelationType, str], ...] = (),
) -> VisibleObject:
    return VisibleObject(
        object_id=object_id,
        kind=kind,
        authority=authority,
        is_current=is_current,
        is_stale=is_stale,
        scope=scope,
        relations=tuple(Relation(relation_type=t, target_id=target) for t, target in relations),
    )


def visibility(
    *objects: VisibleObject,
    basis: tuple[str, ...] = ("CLAIM-1",),
    roots: tuple[str, ...] | None = None,
    run_scope: str = SCOPE,
) -> GraphVisibility:
    """Roots default to every visible current canonical Intent, as ``canonical_roots`` would."""
    if roots is None:
        roots = tuple(
            sorted(
                o.object_id
                for o in objects
                if o.kind is SemanticKind.INTENT
                and o.is_current
                and o.authority is Authority.CANONICAL
            )
        )
    return GraphVisibility(
        run_scope=run_scope,
        objects=objects,
        basis_claim_ids=frozenset(basis),
        root_intent_ids=roots,
    )


def assign(
    graph: IntentGraphSynthesisResult,
    *,
    origin: SynthesisOrigin = SynthesisOrigin.HUMAN_STATED,
    authority: Authority = Authority.CANONICAL,
) -> dict[str, NodeAssignment]:
    """The same runtime assignment for every node of ``graph``."""
    return {
        n.local_id.local_id: NodeAssignment(origin=origin, authority=authority) for n in graph.nodes
    }

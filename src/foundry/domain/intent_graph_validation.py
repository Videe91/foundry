"""Structural validation of a proposed Intent Graph (IE3 Slice 1).

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§9-§12, §17, §19;
R100, R101, R104).

A graph is validated against a ``GraphVisibility``: the bounded, runtime-owned surface that says
what the proposer was shown. It is temporary validation context, never durable state. The
model cannot cite invisible state, so an ``ExistingObjectRef`` resolves only to a shown object
and a ``BasisClaimRef`` only to a shown claim.

What this module decides, structurally and regardless of authority:

* every reference resolves, and no relation, basis path or relevance path passes through a node
  the result does not contain. A gap never stands in for a missing node (R104);
* relation legality is the IE2 matrix (``LEGAL_RELATION_TARGETS``), narrowed where IE3 is
  stricter (``AFFECTS`` only from an Assumption). It is read, never restated;
* no parallel node: a ``NEW`` node never sits beside a ``REPLACES_STALE`` node of the same
  kind when both derive directly from the same shown claim (``PARALLEL_NODE``). The
  replacement already carries that claim's meaning for that kind; the ``NEW`` node duplicates
  it. Decided on disposition, kind and ``DERIVED_FROM`` edges alone, never on wording;
* ``SERVES`` and ``DERIVED_FROM`` are acyclic among the new nodes;
* every relevance-bearing node reaches an Intent by explicit ``SERVES`` (never by sharing a
  batch, scope, claim or subject), and a graph adds at most one root;
* every Assumption ``AFFECTS`` something;
* grounding follows ``(origin class, kind, facet)`` (§11). A non-human node must reach a shown
  claim or a shown existing Decision through ``DERIVED_FROM``. A Decision proposed in the same
  batch is never a terminal for it (R101), because a model would otherwise ground its own
  proposal on its own invented choice.

What it does not decide: authority-dependent lawfulness. For canonical nodes the unchanged IE2
laws run over the hypothetical post-graph state (``intent_graph_compiler``). This module never
duplicates or weakens them.

Refusals raise ``IntentGraphValidationError`` on the first defect, in a fixed order, with a code.
Nodes are judged in sorted local-id order, so the reported defect is deterministic.

Pure domain: no I/O, no clock, no randomness, no provider import.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Final

from pydantic import Field, model_validator

from foundry.domain.authority import object_is_current
from foundry.domain.common import Authority, FrozenModel, Relation, RelationType
from foundry.domain.intent_graph import (
    IE3_GRAPH_NODE_KINDS,
    BasisClaimRef,
    ExistingObjectRef,
    GraphNodeDisposition,
    GraphNodeProposal,
    GraphRef,
    IntentGraphSynthesisResult,
    LocalNodeRef,
)
from foundry.domain.relation_legality import LEGAL_RELATION_TARGETS
from foundry.domain.relevance import RELEVANCE_BEARING_KINDS, canonical_roots
from foundry.domain.scope import scope_applies
from foundry.domain.semantic import ConstraintFacet, SemanticKind
from foundry.domain.semantic_view import derive_view

if TYPE_CHECKING:
    from foundry.domain.state import IntentState

__all__ = [
    "EVIDENCE_REQUIRED_FACETS",
    "GraphVisibility",
    "IntentGraphValidationError",
    "VisibleObject",
    "graph_visibility",
    "validate_intent_graph",
]

EVIDENCE_REQUIRED_FACETS: Final[frozenset[ConstraintFacet]] = frozenset(
    {ConstraintFacet.EVIDENCE_BOUND, ConstraintFacet.EXTERNAL_MANDATE}
)
"""§11: these Constraints must reach evidence whoever authors them."""

_CYCLE_AXES: Final = (RelationType.SERVES, RelationType.DERIVED_FROM)


class IntentGraphValidationError(ValueError):
    """A proposed graph is structurally invalid. Nothing about it may be applied."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# --------------------------------------------------------------------------- visibility


class VisibleObject(FrozenModel):
    """One existing object as runtime showed it. Temporary validation context."""

    object_id: str = Field(min_length=1)
    kind: SemanticKind
    authority: Authority
    is_current: bool
    is_stale: bool
    scope: tuple[str, ...]
    relations: tuple[Relation, ...] = ()


class GraphVisibility(FrozenModel):
    """What the proposer was shown, and the run scope every new node will receive (Q2)."""

    run_scope: str = Field(min_length=1)
    objects: tuple[VisibleObject, ...] = ()
    basis_claim_ids: frozenset[str] = frozenset()
    root_intent_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_surface(self) -> GraphVisibility:
        ids = [o.object_id for o in self.objects]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate visible object id")
        for obj in self.objects:
            if obj.kind not in IE3_GRAPH_NODE_KINDS:
                raise ValueError(f"{obj.object_id!r} is a {obj.kind.value}, not an IE3 kind")
        both = set(ids) & self.basis_claim_ids
        if both:
            raise ValueError(f"ids visible as both object and basis claim: {sorted(both)}")
        by_id = {o.object_id: o for o in self.objects}
        for root_id in self.root_intent_ids:
            root = by_id.get(root_id)
            if root is None or root.kind is not SemanticKind.INTENT or not root.is_current:
                raise ValueError(f"root {root_id!r} is not a visible current Intent")
        return self

    def get(self, object_id: str) -> VisibleObject | None:
        for obj in self.objects:
            if obj.object_id == object_id:
                return obj
        return None


def graph_visibility(
    state: IntentState, run_scope: str, *, basis_claim_ids: Iterable[str]
) -> GraphVisibility:
    """The visibility surface for ``run_scope``, derived from state by one fixed rule.

    Current IE3-kind objects applicable to the scope are shown, with staleness flagged rather
    than filtered, because a stale object is exactly what a replacement needs to see. The basis
    claims are the ones the caller chose to show, and each must exist.
    """
    claims = tuple(sorted(set(basis_claim_ids)))
    for claim_id in claims:
        if claim_id not in state.semantic.claims:
            raise ValueError(f"basis claim {claim_id!r} does not exist in semantic state")
    stale = frozenset(derive_view(state.semantic).stale_ids)
    shown = sorted(
        (
            obj
            for obj in state.objects.values()
            if obj.kind in IE3_GRAPH_NODE_KINDS
            and object_is_current(obj)
            and scope_applies(tuple(obj.scope), run_scope)
        ),
        key=lambda o: o.id,
    )
    return GraphVisibility(
        run_scope=run_scope,
        objects=tuple(
            VisibleObject(
                object_id=obj.id,
                kind=obj.kind,
                authority=obj.authority,
                is_current=True,
                is_stale=obj.id in stale,
                scope=tuple(obj.scope),
                relations=tuple(obj.relations),
            )
            for obj in shown
        ),
        basis_claim_ids=frozenset(claims),
        root_intent_ids=canonical_roots(state, run_scope),
    )


# --------------------------------------------------------------------------- validation


class _Graph:
    """The result indexed once: nodes by local id and outgoing edges by (source, axis)."""

    def __init__(self, result: IntentGraphSynthesisResult, visibility: GraphVisibility) -> None:
        self.result = result
        self.visibility = visibility
        self.nodes: dict[str, GraphNodeProposal] = {n.local_id.local_id: n for n in result.nodes}
        self.order = sorted(self.nodes)

    def edges(self, source: str, relation_type: RelationType) -> list[GraphRef]:
        return [
            r.target
            for r in self.result.relations
            if r.source.local_id == source and r.relation_type is relation_type
        ]

    def existing_targets(self, obj_id: str, relation_type: RelationType) -> list[str]:
        obj = self.visibility.get(obj_id)
        if obj is None:
            return []
        return sorted(r.target_id for r in obj.relations if r.relation_type is relation_type)

    def target_kind(self, ref: GraphRef) -> SemanticKind:
        """The kind a reference resolves to. Raises when it resolves nowhere lawful."""
        if isinstance(ref, LocalNodeRef):
            node = self.nodes.get(ref.local_id)
            if node is None:
                raise IntentGraphValidationError(
                    "UNRESOLVED_LOCAL_REF",
                    f"local {ref.local_id!r} names no node of this result; a gap never stands "
                    "in for a missing node",
                )
            return node.kind
        if isinstance(ref, ExistingObjectRef):
            obj = self.visibility.get(ref.object_id)
            if obj is None:
                raise IntentGraphValidationError(
                    "INVISIBLE_EXISTING_REF",
                    f"existing {ref.object_id!r} was not shown; the model cannot cite "
                    "invisible state",
                )
            if not obj.is_current:
                raise IntentGraphValidationError(
                    "EXISTING_NOT_CURRENT", f"existing {ref.object_id!r} is not current"
                )
            return obj.kind
        if ref.claim_id not in self.visibility.basis_claim_ids:
            raise IntentGraphValidationError(
                "INVISIBLE_BASIS_REF",
                f"basis claim {ref.claim_id!r} was not shown; the model cannot cite "
                "invisible state",
            )
        return SemanticKind.CLAIM


def _resolve_references(graph: _Graph) -> None:
    for relation in graph.result.relations:
        graph.target_kind(relation.source)
        graph.target_kind(relation.target)
    for local_id in graph.order:
        node = graph.nodes[local_id]
        if node.replaces is not None:
            graph.target_kind(node.replaces)
    for gap in graph.result.gaps:
        for anchor in gap.anchors:
            graph.target_kind(anchor)
    for ref in graph.result.unchanged_object_refs:
        # R111: a witness must have been shown and be current (target_kind proves both) and must
        # not be stale; a stale object needs reconciliation, never "no change".
        graph.target_kind(ref)
        shown = graph.visibility.get(ref.object_id)
        if shown is not None and shown.is_stale:
            raise IntentGraphValidationError(
                "UNCHANGED_REF_STALE",
                f"{ref.object_id!r} is stale and cannot be declared unchanged; replace it or "
                "raise a gap",
            )


def _check_legality(graph: _Graph) -> None:
    for relation in graph.result.relations:
        source_kind = graph.nodes[relation.source.local_id].kind
        target_kind = graph.target_kind(relation.target)
        legal_sources, legal_targets = LEGAL_RELATION_TARGETS[relation.relation_type]
        narrowed = (
            relation.relation_type is RelationType.AFFECTS
            and source_kind is not SemanticKind.ASSUMPTION
        )
        if source_kind not in legal_sources or target_kind not in legal_targets or narrowed:
            raise IntentGraphValidationError(
                "ILLEGAL_RELATION",
                f"{source_kind.value} may not {relation.relation_type.value} a "
                f"{target_kind.value} (from {relation.source.local_id!r})",
            )


def _ref_key(ref: GraphRef) -> tuple[str, str]:
    if isinstance(ref, LocalNodeRef):
        return ("local", ref.local_id)
    if isinstance(ref, ExistingObjectRef):
        return ("existing", ref.object_id)
    return ("basis", ref.claim_id)


def _check_edges(graph: _Graph) -> None:
    seen: set[tuple[str, RelationType, tuple[str, str]]] = set()
    for relation in graph.result.relations:
        key = (relation.source.local_id, relation.relation_type, _ref_key(relation.target))
        if key in seen:
            raise IntentGraphValidationError(
                "DUPLICATE_RELATION",
                f"{relation.source.local_id!r} {relation.relation_type.value} "
                f"{key[2][1]!r} is proposed twice",
            )
        seen.add(key)
        if key[2] == ("local", relation.source.local_id):
            raise IntentGraphValidationError(
                "SELF_RELATION",
                f"{relation.source.local_id!r} may not {relation.relation_type.value} itself",
            )


def _check_replacements(graph: _Graph) -> None:
    retiring: dict[str, str] = {}
    for local_id in graph.order:
        node = graph.nodes[local_id]
        if node.disposition is not GraphNodeDisposition.REPLACES_STALE:
            continue
        assert node.replaces is not None  # the node validator guarantees it
        target = graph.visibility.get(node.replaces.object_id)
        assert target is not None  # resolved above
        if target.kind is not node.kind:
            raise IntentGraphValidationError(
                "REPLACEMENT_KIND_MISMATCH",
                f"{local_id!r} is a {node.kind.value} but {target.object_id!r} is a "
                f"{target.kind.value}; replacement is like for like",
            )
        if not target.is_stale:
            raise IntentGraphValidationError(
                "REPLACEMENT_TARGET_NOT_STALE",
                f"{target.object_id!r} is not stale; reconciling sound intent would retire it",
            )
        if target.object_id in retiring:
            raise IntentGraphValidationError(
                "DOUBLE_REPLACEMENT",
                f"{retiring[target.object_id]!r} and {local_id!r} both replace "
                f"{target.object_id!r}",
            )
        retiring[target.object_id] = local_id
    referenced = [r.target for r in graph.result.relations] + [
        anchor for gap in graph.result.gaps for anchor in gap.anchors
    ]
    for ref in referenced:
        if isinstance(ref, ExistingObjectRef) and ref.object_id in retiring:
            raise IntentGraphValidationError(
                "RETIRING_TARGET_REFERENCED",
                f"{ref.object_id!r} is retired by this graph; an edge to it would be dead",
            )


def _direct_basis_claims(graph: _Graph, local_id: str) -> frozenset[str]:
    """Claims a node derives from DIRECTLY (one ``DERIVED_FROM`` edge to a basis claim)."""
    return frozenset(
        target.claim_id
        for target in graph.edges(local_id, RelationType.DERIVED_FROM)
        if isinstance(target, BasisClaimRef)
    )


def _check_parallel_nodes(graph: _Graph) -> None:
    """A ``NEW`` node of the same kind as a ``REPLACES_STALE`` node, derived directly from a
    claim the replacement also derives from, is a parallel duplicate (``PARALLEL_NODE``).

    The key is exactly: this answer, the same kind, the same directly-derived claim, one
    ``NEW`` and one ``REPLACES_STALE`` node. Different kinds from one claim, the same kind from
    different claims, two ``NEW`` nodes and two replacements are left to the other laws.
    """
    replacing = [
        local_id
        for local_id in graph.order
        if graph.nodes[local_id].disposition is GraphNodeDisposition.REPLACES_STALE
    ]
    for replacement in replacing:
        kind = graph.nodes[replacement].kind
        claims = _direct_basis_claims(graph, replacement)
        for local_id in graph.order:
            node = graph.nodes[local_id]
            if node.disposition is not GraphNodeDisposition.NEW or node.kind is not kind:
                continue
            shared = claims & _direct_basis_claims(graph, local_id)
            if shared:
                raise IntentGraphValidationError(
                    "PARALLEL_NODE",
                    f"{local_id!r} (NEW) and {replacement!r} (REPLACES_STALE) are both "
                    f"{kind.value} derived from claim {sorted(shared)[0]!r}; the replacement "
                    "already carries it",
                )


def _check_acyclic(graph: _Graph) -> None:
    """Existing objects can never point at a new node, so any new cycle lies among new nodes."""
    for axis in _CYCLE_AXES:
        state: dict[str, int] = {}  # 1 = on the current path, 2 = finished
        for start in graph.order:
            if start in state:
                continue
            stack: list[tuple[str, list[str]]] = [(start, _local_targets(graph, start, axis))]
            state[start] = 1
            while stack:
                current, pending = stack[-1]
                if not pending:
                    state[current] = 2
                    stack.pop()
                    continue
                nxt = pending.pop()
                if state.get(nxt) == 1:
                    raise IntentGraphValidationError(
                        "RELATION_CYCLE",
                        f"{axis.value} closes a cycle through {current!r} and {nxt!r}",
                    )
                if nxt not in state:
                    state[nxt] = 1
                    stack.append((nxt, _local_targets(graph, nxt, axis)))


def _local_targets(graph: _Graph, source: str, axis: RelationType) -> list[str]:
    return sorted(
        ref.local_id for ref in graph.edges(source, axis) if isinstance(ref, LocalNodeRef)
    )


def _check_roots(graph: _Graph) -> None:
    new_roots = [lid for lid in graph.order if graph.nodes[lid].kind is SemanticKind.INTENT]
    existing = sorted(
        o.object_id
        for o in graph.visibility.objects
        if o.kind is SemanticKind.INTENT and o.is_current
    )
    if len(new_roots) > 1 or (new_roots and existing):
        raise IntentGraphValidationError(
            "MULTIPLE_ROOTS",
            f"new root(s) {new_roots} beside existing {existing}; a graph adds at most one root "
            "and never a second one",
        )


def _reaches_intent(graph: _Graph, start: str) -> bool:
    """An explicit SERVES path from ``start`` to a new or shown current Intent."""
    seen: set[tuple[str, str]] = set()
    frontier: list[tuple[str, str]] = [("local", start)]
    while frontier:
        namespace, ident = frontier.pop()
        if (namespace, ident) in seen:
            continue
        seen.add((namespace, ident))
        if namespace == "local":
            node = graph.nodes[ident]
            if node.kind is SemanticKind.INTENT:
                return True
            frontier.extend(_ref_key(t) for t in graph.edges(ident, RelationType.SERVES))
            continue
        obj = graph.visibility.get(ident)
        if obj is None or not obj.is_current:
            continue
        if obj.kind is SemanticKind.INTENT:
            return True
        frontier.extend(("existing", t) for t in graph.existing_targets(ident, RelationType.SERVES))
    return False


def _check_relevance(graph: _Graph) -> None:
    for local_id in graph.order:
        node = graph.nodes[local_id]
        if node.kind in RELEVANCE_BEARING_KINDS and not _reaches_intent(graph, local_id):
            raise IntentGraphValidationError(
                "NO_RELEVANCE",
                f"{local_id!r} proves no explicit SERVES path to an Intent; relevance is never "
                "inferred",
            )


def _check_assumptions(graph: _Graph) -> None:
    for local_id in graph.order:
        node = graph.nodes[local_id]
        if node.kind is SemanticKind.ASSUMPTION and not graph.edges(local_id, RelationType.AFFECTS):
            raise IntentGraphValidationError(
                "ASSUMPTION_WITHOUT_AFFECTS",
                f"{local_id!r} affects nothing; a premise with no dependant is noise",
            )


def _grounding(graph: _Graph, start: str) -> tuple[bool, bool]:
    """``(reaches a shown claim, reaches a shown existing Decision)`` by DERIVED_FROM.

    New nodes are never terminals, a new Decision included (R101): the walk continues through
    their own basis instead.
    """
    claim = decision = False
    seen: set[tuple[str, str]] = set()
    frontier: list[tuple[str, str]] = [("local", start)]
    while frontier:
        namespace, ident = frontier.pop()
        if (namespace, ident) in seen:
            continue
        seen.add((namespace, ident))
        if namespace == "basis":
            claim = True
            continue
        if namespace == "local":
            frontier.extend(_ref_key(t) for t in graph.edges(ident, RelationType.DERIVED_FROM))
            continue
        obj = graph.visibility.get(ident)
        if obj is None or not obj.is_current:
            continue
        if obj.kind is SemanticKind.DECISION:
            decision = True
        for target in graph.existing_targets(ident, RelationType.DERIVED_FROM):
            if target in graph.visibility.basis_claim_ids:
                frontier.append(("basis", target))
            else:
                frontier.append(("existing", target))
    return claim, decision


def _check_grounding(graph: _Graph, *, author_is_human: bool) -> None:
    for local_id in graph.order:
        node = graph.nodes[local_id]
        if node.kind is SemanticKind.ASSUMPTION:
            continue  # basis is forbidden by legality; its dependency is AFFECTS
        evidential_facet = (
            node.kind is SemanticKind.CONSTRAINT
            and getattr(node, "facet", None) in EVIDENCE_REQUIRED_FACETS
        )
        if author_is_human and not evidential_facet:
            continue  # a direct authoritative choice needs no fabricated basis
        claim, decision = _grounding(graph, local_id)
        grounded = claim if evidential_facet else claim or decision
        if not grounded:
            required = "a shown claim" if evidential_facet else "a shown claim or existing Decision"
            raise IntentGraphValidationError(
                "UNGROUNDED_NODE",
                f"{local_id!r} ({node.kind.value}) must reach {required} through DERIVED_FROM",
            )


def validate_intent_graph(
    result: IntentGraphSynthesisResult,
    visibility: GraphVisibility,
    *,
    author_is_human: bool,
) -> None:
    """Refuse the first structural defect of ``result`` against ``visibility``.

    Order is fixed and load-bearing only for reporting: references, legality, edges,
    replacement, parallel nodes, cycles, roots, relevance, assumptions, grounding.
    """
    graph = _Graph(result, visibility)
    _resolve_references(graph)
    _check_legality(graph)
    _check_edges(graph)
    _check_replacements(graph)
    _check_parallel_nodes(graph)
    _check_acyclic(graph)
    _check_roots(graph)
    _check_relevance(graph)
    _check_assumptions(graph)
    _check_grounding(graph, author_is_human=author_is_human)

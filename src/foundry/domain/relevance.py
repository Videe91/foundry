"""Relevance and root completeness (IE2.2c, spec §3, §4a, §6-§8, §10).

``DERIVED_FROM`` says why an object is grounded; ``SERVES`` says why it matters. This module
decides the second, for one evaluated delivery scope at a time, and is shared by the IE2 seam
(refuse before append) and v2 delivery readiness (diagnose history) -- one law, two timings.

**Relevance is explicit.** Only object-local ``SERVES`` relations count. Shared scope, the
existence of a single Intent, a basis claim, statement text and synthesis origin are never
read as relevance, and ``DerivationEdge`` is never consulted.

For evaluated scope ``S``:

* the **roots** are current ``CANONICAL`` Intents applicable to ``S``. Exactly one is
  required for delivery; several is ``MULTIPLE_CANONICAL_ROOTS``; none is left to closure's
  existing ``MISSING_CANONICAL_INTENT`` rather than invented again here;
* an object is **relevant** when some ``SERVES`` path reaches the root through nodes that are
  each current, ``CANONICAL``, of a relevance-bearing kind and applicable to ``S``. One lawful
  path is enough; a bad branch beside it does not matter;
* a ``SERVES`` cycle among current canonical applicable objects is reported on its own, even
  when its members also reach the root.

Relevant sets are found by a reverse walk from the roots, so shared structure is visited once,
reconvergence (a diamond) is ordinary, and a historical cycle terminates. Cycles are found by
an iterative strongly-connected-components pass. Nothing recurses.

An evaluated scope of ``None`` means *every* scope: only project-wide objects apply. It is the
proof the seam demands of a project-wide candidate, because no single named scope can stand
in for all the scopes it will later be delivered in.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Final

from foundry.domain.authority import object_is_current
from foundry.domain.basis import (
    UNGROUNDED_CANONICAL_OBJECT,
    UnlawfulBasisError,
    basis_decision_terminals,
)
from foundry.domain.common import Authority, FrozenModel, RelationType
from foundry.domain.scope import scope_applies
from foundry.domain.semantic import SemanticBase, SemanticKind

if TYPE_CHECKING:
    from foundry.domain.semantic import SemanticObject
    from foundry.domain.state import IntentState

__all__ = [
    "MULTIPLE_CANONICAL_ROOTS",
    "ORPHANED_CANONICAL_OBJECT",
    "RELEVANCE_BEARING_KINDS",
    "RELEVANCE_BLOCKER_CODES",
    "RELEVANCE_CYCLE",
    "IrrelevantObjectError",
    "RelevanceBlocker",
    "assert_relevant",
    "canonical_roots",
    "irrelevant_decision_terminals",
    "relevance_blockers",
    "relevant_ids",
]

MULTIPLE_CANONICAL_ROOTS: Final = "MULTIPLE_CANONICAL_ROOTS"
ORPHANED_CANONICAL_OBJECT: Final = "ORPHANED_CANONICAL_OBJECT"
RELEVANCE_CYCLE: Final = "RELEVANCE_CYCLE"

RELEVANCE_BLOCKER_CODES: Final[tuple[str, ...]] = (
    MULTIPLE_CANONICAL_ROOTS,
    ORPHANED_CANONICAL_OBJECT,
    RELEVANCE_CYCLE,
)
"""The three IE2.2c codes, in v2's deterministic refusal order."""

RELEVANCE_BEARING_KINDS: Final[frozenset[SemanticKind]] = frozenset(
    {
        SemanticKind.GOAL,
        SemanticKind.OUTCOME,
        SemanticKind.REQUIREMENT,
        SemanticKind.CONSTRAINT,
        SemanticKind.NON_GOAL,
        SemanticKind.PREFERENCE,
        SemanticKind.DECISION,
    }
)
"""§4a, written out and never derived from ``INTENT_BEARING_SEMANTIC_KINDS``.

Excluded on purpose: ``INTENT`` is the root; ``ASSUMPTION`` depends on intent through
``AFFECTS``; ``ACTOR`` is context; the epistemic, measurement and governance kinds are not
intended state; ``CONTRACT`` is legacy and gains no new semantics here.
"""


class RelevanceBlocker(FrozenModel):
    """An ids-only v2 readiness diagnosis. Never a closure blocker (P4, R52)."""

    code: str
    object_ids: tuple[str, ...]


class IrrelevantObjectError(ValueError):
    """A new canonical object proves no ``SERVES`` path to a root; nothing was appended."""


def _applies(obj: SemanticBase, scope: str | None) -> bool:
    if scope is None:
        return obj.scope == ()
    return scope_applies(tuple(obj.scope), scope)


def _serves_targets(obj: SemanticBase) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                relation.target_id
                for relation in obj.relations
                if relation.relation_type is RelationType.SERVES
            }
        )
    )


def _live_canonical(obj: SemanticBase, scope: str | None) -> bool:
    return object_is_current(obj) and obj.authority is Authority.CANONICAL and _applies(obj, scope)


def canonical_roots(state: IntentState, scope: str | None) -> tuple[str, ...]:
    """Current ``CANONICAL`` Intents applicable to ``scope``, sorted."""
    return tuple(
        sorted(
            obj.id
            for obj in state.objects.values()
            if obj.kind is SemanticKind.INTENT and _live_canonical(obj, scope)
        )
    )


def relevant_ids(state: IntentState, scope: str | None, roots: Iterable[str]) -> frozenset[str]:
    """Every id with a lawful ``SERVES`` path to one of ``roots``, the roots included.

    A reverse walk: start at the roots and admit any lawful node that serves something
    already relevant. The relevant set doubles as the visited set, so a historical cycle
    is entered once and the walk ends.
    """
    reverse: dict[str, list[str]] = {}
    for obj in state.objects.values():
        if obj.kind in RELEVANCE_BEARING_KINDS and _live_canonical(obj, scope):
            for target_id in _serves_targets(obj):
                reverse.setdefault(target_id, []).append(obj.id)

    relevant = set(roots)
    frontier = list(relevant)
    while frontier:
        target_id = frontier.pop()
        for source_id in reverse.get(target_id, ()):
            if source_id not in relevant:
                relevant.add(source_id)
                frontier.append(source_id)
    return frozenset(relevant)


def _serves_cycles(state: IntentState, scope: str) -> tuple[tuple[str, ...], ...]:
    """Strongly connected ``SERVES`` components among current canonical applicable objects.

    Iterative Tarjan. A component is a cycle when it has more than one member, or one member
    that serves itself. Participants are sorted and components ordered, so the diagnosis is
    deterministic.
    """
    nodes = {obj.id: obj for obj in state.objects.values() if _live_canonical(obj, scope)}
    edges = {
        node_id: tuple(t for t in _serves_targets(obj) if t in nodes)
        for node_id, obj in nodes.items()
    }

    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    cycles: list[tuple[str, ...]] = []
    counter = 0

    for start in sorted(nodes):
        if start in index:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node_id, position = work.pop()
            if position == 0:
                index[node_id] = low[node_id] = counter
                counter += 1
                stack.append(node_id)
                on_stack.add(node_id)
            targets = edges[node_id]
            if position < len(targets):
                work.append((node_id, position + 1))
                target_id = targets[position]
                if target_id not in index:
                    work.append((target_id, 0))
                elif target_id in on_stack:
                    low[node_id] = min(low[node_id], index[target_id])
                continue
            if low[node_id] == index[node_id]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node_id:
                        break
                if len(component) > 1 or node_id in edges[node_id]:
                    cycles.append(tuple(sorted(component)))
            if work:
                parent_id = work[-1][0]
                low[parent_id] = min(low[parent_id], low[node_id])
    return tuple(sorted(cycles))


def relevance_blockers(state: IntentState, scope: str) -> tuple[RelevanceBlocker, ...]:
    """Every relevance/root defect for delivery scope ``scope``, deterministically ordered."""
    blockers: list[RelevanceBlocker] = []
    roots = canonical_roots(state, scope)
    if len(roots) > 1:
        # No orphan is judged against an arbitrarily chosen root.
        blockers.append(RelevanceBlocker(code=MULTIPLE_CANONICAL_ROOTS, object_ids=roots))
    elif len(roots) == 1:
        relevant = relevant_ids(state, scope, roots)
        blockers.extend(
            RelevanceBlocker(code=ORPHANED_CANONICAL_OBJECT, object_ids=(obj.id,))
            for obj in state.objects.values()
            if obj.kind in RELEVANCE_BEARING_KINDS
            and _live_canonical(obj, scope)
            and obj.id not in relevant
        )
    blockers.extend(
        RelevanceBlocker(code=RELEVANCE_CYCLE, object_ids=cycle)
        for cycle in _serves_cycles(state, scope)
    )
    return tuple(sorted(blockers, key=lambda b: (b.code, b.object_ids)))


def irrelevant_decision_terminals(state: IntentState, scope: str) -> tuple[tuple[str, str], ...]:
    """R59 at readiness: ``(object_id, decision_id)`` pairs whose Decision terminal fails.

    A current canonical object applicable to ``scope`` may rest on a ``ProjectDecision`` only
    if that Decision applies to ``scope`` and, when the scope has its one root, is relevant
    to it. With no root or several, relevance is not judged against an arbitrary root; the
    applicability requirement still holds.
    """
    roots = canonical_roots(state, scope)
    relevant = relevant_ids(state, scope, roots) if len(roots) == 1 else None
    failures: list[tuple[str, str]] = []
    for obj in state.objects.values():
        if not _live_canonical(obj, scope):
            continue
        for decision_id in basis_decision_terminals(state, obj):
            decision = state.objects[decision_id]
            if not _applies(decision, scope) or (
                relevant is not None and decision_id not in relevant
            ):
                failures.append((obj.id, decision_id))
    return tuple(sorted(failures))


def assert_relevant(state: IntentState, obj: SemanticObject) -> None:
    """Refuse a new ``CANONICAL`` candidate whose relevance cannot be proved. Seam only.

    Proved independently for every declared scope; a project-wide candidate must prove a
    path of project-wide objects to a project-wide root. Root *uniqueness* is not demanded
    here -- history may hold several roots, and that remains a readiness diagnosis.
    """
    if obj.authority is not Authority.CANONICAL:
        return
    scopes: tuple[str | None, ...] = tuple(obj.scope) or (None,)
    decisions = basis_decision_terminals(state, obj)
    targets = _serves_targets(obj)
    for scope in scopes:
        relevant = relevant_ids(state, scope, canonical_roots(state, scope))
        label = "every scope" if scope is None else repr(scope)
        if obj.kind in RELEVANCE_BEARING_KINDS and not any(t in relevant for t in targets):
            raise IrrelevantObjectError(
                f"{ORPHANED_CANONICAL_OBJECT}: {obj.id!r} proves no SERVES path to a canonical "
                f"root Intent for {label}; relevance is never inferred"
            )
        for decision_id in decisions:
            # Only applicable nodes are ever relevant, so this also demands applicability.
            if decision_id not in relevant:
                raise UnlawfulBasisError(
                    f"{UNGROUNDED_CANONICAL_OBJECT}: {obj.id!r} rests on Decision "
                    f"{decision_id!r}, which is not applicable and relevant for {label}"
                )

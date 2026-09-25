"""Assumption dependency and blast radius (IE2.3, R63-R69).

An Assumption is an epistemic premise, never factual basis: IE2.1 forbids ``DERIVED_FROM``
into one and IE2.2b refuses one anywhere in a basis chain. Its dependency on intended state is
expressed by ``AFFECTS``. This module answers one question deterministically:

    if this assumption needs reconsideration, which intended-state objects are exposed?

The law (R63), and nothing else:

    blast radius = direct explicit AFFECTS targets
                 + every object that transitively DERIVED_FROM one of them

Three relations, three meanings, kept apart: ``DERIVED_FROM`` is why something is justified,
``SERVES`` why it matters, ``AFFECTS`` what premise may change it. Only justification carries
premise dependency, so only ``DERIVED_FROM`` propagates. ``SERVES`` does not (R64): an object
may serve several goals, so impact on one does not mean it lost relevance, and deciding that
needs a scope and a root this universal projection deliberately does not take. ``EXCLUDES``
affects closure, not dependency (R69). No other relation propagates.

Choices that each rule out a real failure:

* **object-local relations, never ``DerivationEdge``** (R65) -- historical edges use two
  different parent-id conventions, so reading them would make the radius depend on which
  writer recorded an object;
* **seeds are only ``AFFECTS``** (R67) -- not text, scope, a shared goal, a shared basis claim,
  a synthesis run or a gap's ``affected_object_ids``;
* **historical and actionable are separate results** (R66) -- the walk passes through dead
  intermediates, and only the result is filtered by ``object_is_current``, so a superseded
  link never hides a live descendant;
* **iterative, visited-set, sorted** -- long chains cannot exhaust the stack, a historical
  cycle terminates, a diamond yields each id once, and output is reproducible;
* **dangling ids are ignored** -- history may point at nothing; replay is never validated.

A projection only: it appends nothing, supersedes nothing, creates no gap and changes no
authority. What should *happen* to an exposed object is reconciliation's decision. There is
also no durable "this assumption is false" state yet (R68); deciding when an Assumption needs
action is a later trigger that will consume this radius.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from foundry.domain.authority import object_is_current
from foundry.domain.common import RelationType
from foundry.domain.events import derivation_parents_of
from foundry.domain.semantic import Assumption

if TYPE_CHECKING:
    from foundry.domain.state import IntentState

__all__ = [
    "NotAnAssumptionError",
    "UnknownAssumptionError",
    "actionable_assumption_blast_radius",
    "assumption_blast_radius",
    "direct_assumption_impacts",
]


class UnknownAssumptionError(LookupError):
    """The id names nothing in this project. Never read as "no impact"."""


class NotAnAssumptionError(ValueError):
    """The id names an object that is not an Assumption; only premises have a radius."""


def _assumption(state: IntentState, assumption_id: str) -> Assumption:
    obj = state.objects.get(assumption_id)
    if obj is None or obj.project_id != state.project_id:
        raise UnknownAssumptionError(f"no assumption {assumption_id!r} in {state.project_id!r}")
    if not isinstance(obj, Assumption):
        raise NotAnAssumptionError(
            f"{assumption_id!r} is a {obj.kind.value}, not an Assumption; only an explicit "
            "premise has a blast radius"
        )
    return obj


def _local(state: IntentState, object_id: str) -> bool:
    obj = state.objects.get(object_id)
    return obj is not None and obj.project_id == state.project_id


def direct_assumption_impacts(state: IntentState, assumption_id: str) -> tuple[str, ...]:
    """The objects this Assumption explicitly ``AFFECTS``, sorted. Dangling targets ignored."""
    assumption = _assumption(state, assumption_id)
    return tuple(
        sorted(
            {
                relation.target_id
                for relation in assumption.relations
                if relation.relation_type is RelationType.AFFECTS
                and relation.target_id != assumption_id
                and _local(state, relation.target_id)
            }
        )
    )


def assumption_blast_radius(state: IntentState, assumption_id: str) -> tuple[str, ...]:
    """Historical radius: every object the ledger's dependency structure exposes, sorted.

    Walks reverse object-local ``DERIVED_FROM`` from the direct targets, through dead
    intermediates as well as live ones, because the question is what depends on the premise
    -- not what is still current. ``actionable_assumption_blast_radius`` filters that.
    """
    seeds = direct_assumption_impacts(state, assumption_id)

    children: dict[str, list[str]] = {}
    for obj in state.objects.values():
        if obj.project_id != state.project_id:
            continue
        for parent_id in derivation_parents_of(obj):
            children.setdefault(parent_id, []).append(obj.id)

    reached = set(seeds)
    frontier = list(seeds)
    while frontier:
        parent_id = frontier.pop()
        for child_id in children.get(parent_id, ()):
            if child_id not in reached:
                reached.add(child_id)
                frontier.append(child_id)
    reached.discard(assumption_id)
    return tuple(sorted(reached))


def actionable_assumption_blast_radius(state: IntentState, assumption_id: str) -> tuple[str, ...]:
    """Current radius: the historical radius restricted to ``object_is_current`` objects."""
    return tuple(
        object_id
        for object_id in assumption_blast_radius(state, assumption_id)
        if object_is_current(state.objects[object_id])
    )

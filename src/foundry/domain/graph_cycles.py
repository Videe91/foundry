"""Cycle refusal for the Intent Graph's two transitive relations (IE2.2a).

`SERVES` and `DERIVED_FROM` are both transitive, and a cycle in either is a set of objects
that justify each other and nothing else: relevance that never reaches a root, or a basis
where every node has a parent and none has a ground.

**The hazard is narrower than it first appears, and worth stating honestly.** IE2.1 already
requires every relation target to resolve at admission, so the naive shape -- admit `A → B`,
then admit `B → A` -- cannot happen through the seam: either `B` exists and the second
admission is refused as a duplicate, or it does not and the first is refused outright. What
this module protects against is a *legacy or dangling* graph being completed by a new write:

    historical:     A --SERVES--> B        (B was never created; the edge dangles)
    new admission:  B --SERVES--> A        (A resolves, so IE2.1 permits it)
    result:         A -> B -> A

That is why reaching the candidate's **id** counts even when nothing is stored under it yet.
Admitting the candidate is exactly what would make the dangling edge real.

Three properties the traversal must have, each for a reason:

* **an explicit visited set**, so a cycle that already exists in history makes the walk
  terminate and report rather than recurse forever;
* **one relation type per walk**, because a `SERVES` path and a `DERIVED_FROM` path are
  different graphs and combining them would invent a cycle that exists in neither;
* **unresolved ids are leaves**, not errors -- history contains dangling edges, and this
  module refuses new cycles rather than auditing old shapes.

Forward-write only. Nothing here runs during parsing, reduction or replay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from foundry.domain.common import RelationType

if TYPE_CHECKING:
    from foundry.domain.semantic import SemanticObject
    from foundry.domain.state import IntentState

__all__ = ["CYCLE_CHECKED_RELATIONS", "RelationCycleError", "assert_no_cycle_introduced"]

CYCLE_CHECKED_RELATIONS: Final[frozenset[RelationType]] = frozenset(
    {RelationType.SERVES, RelationType.DERIVED_FROM}
)
"""The transitive relations. `EXCLUDES`, `CONSTRAINS` and the rest are not walked: a cycle
only matters where reachability is what the relation means."""


class RelationCycleError(ValueError):
    """Admitting this object would close a cycle in `SERVES` or `DERIVED_FROM`."""


def _reaches(
    state: IntentState,
    *,
    start_id: str,
    target_id: str,
    relation_type: RelationType,
) -> bool:
    """Can `target_id` be reached from `start_id` by following `relation_type` alone?

    Iterative rather than recursive so a long historical chain cannot exhaust the stack,
    and `visited` is checked before expansion so a pre-existing cycle is traversed once.
    """
    visited: set[str] = set()
    frontier: list[str] = [start_id]

    while frontier:
        current = frontier.pop()
        if current == target_id:
            return True
        if current in visited:
            continue
        visited.add(current)

        obj = state.objects.get(current)
        if obj is None:
            # A dangling id, or a claim/evidence terminal. Either way it is a leaf: this
            # module refuses new cycles, it does not audit historical shapes.
            continue
        for relation in obj.relations:
            if relation.relation_type is relation_type:
                frontier.append(relation.target_id)
    return False


def assert_no_cycle_introduced(state: IntentState, obj: SemanticObject) -> None:
    """Refuse `obj` if any of its transitive edges would close a cycle back to it.

    Checked per relation type, so a `SERVES` edge and a `DERIVED_FROM` edge can never
    combine into a cycle that exists in neither graph.
    """
    for relation in obj.relations:
        if relation.relation_type not in CYCLE_CHECKED_RELATIONS:
            continue
        # A self-edge needs no special case: `_reaches` starts at the target and returns
        # immediately when that is the candidate itself. A second check here would be a
        # second definition of the same law, free to drift from the first.
        if _reaches(
            state,
            start_id=relation.target_id,
            target_id=obj.id,
            relation_type=relation.relation_type,
        ):
            raise RelationCycleError(
                f"admitting {obj.id!r} with "
                f"{relation.relation_type.value} -> {relation.target_id!r} would close a "
                f"{relation.relation_type.value} cycle back to {obj.id!r}; relevance must "
                "reach a root and a basis must reach a ground"
            )

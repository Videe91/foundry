"""Generic derivation primitive (Intent Intelligence v2, spec §19.1).

``DerivationEdge`` records that ``child_id`` DERIVED_FROM ``parent_id``. It is the
generic, directional, append-only hook that future engines (gap projection, decisions,
contracts, tasks, artifacts) attach to so that superseding a semantic basis can expose
its transitive blast radius. Edges are never edited or removed; only the *current view*
changes when a parent is superseded.

Traversal lives here too (plan §7.1): ``descendants`` is the pure transitive closure
over recorded edges and ``stale_object_ids`` is the current-view blast radius of every
superseded (inactive) judgment. Both are pure functions over domain models: no I/O and
no mutation of the historical edge list.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel

if TYPE_CHECKING:
    from foundry.domain.semantic_state import SemanticState


class DerivationEdge(FrozenModel):
    """``child_id`` derives from ``parent_id``; recorded by one immutable event."""

    child_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)
    recorded_by_event_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_not_self_referential(self) -> DerivationEdge:
        if self.child_id == self.parent_id:
            raise ValueError("child_id and parent_id must differ")
        return self


def descendants(edges: Iterable[DerivationEdge], roots: Iterable[str]) -> frozenset[str]:
    """Every id reachable from ``roots`` by following child <- parent edges.

    Transitive, cycle-safe and deterministic: each node is expanded at most once and
    the result is a set, so edge order and root order do not matter. Roots are never
    part of the result, even when a cycle leads back to one. Inputs are not mutated.
    """
    children_by_parent: dict[str, list[str]] = {}
    for edge in edges:
        children_by_parent.setdefault(edge.parent_id, []).append(edge.child_id)
    root_set = frozenset(roots)
    seen: set[str] = set(root_set)
    frontier = sorted(root_set)
    while frontier:
        node = frontier.pop()
        for child in children_by_parent.get(node, ()):
            if child not in seen:
                seen.add(child)
                frontier.append(child)
    return frozenset(seen - root_set)


def stale_object_ids(state: SemanticState, active_judgment_ids: frozenset[str]) -> frozenset[str]:
    """Current-view blast radius of supersession (spec §19.1).

    Roots are

    * every judgment id that was applied but is not in ``active_judgment_ids`` —
      i.e. whose effect on the current interpretation was ended by an active
      supersession; and
    * every issue version whose ``created_by_judgment_id`` is such an inactive
      judgment — the versions that judgment's admission minted.

    The result is ``descendants(state.derivations, roots)`` — every object recorded as
    (transitively) DERIVED_FROM a superseded basis — UNION the version roots. Versions
    minted by a superseded judgment are stale objects in their own right (they encode
    an interpretation that is no longer current), so they are returned; judgment ids
    are not, because a superseded judgment is the *cause* of staleness, not a stale
    derivative. Downstream engines may hang derivations off either a judgment id or a
    version id and both propagate.

    ``active_judgment_ids`` is passed in (computed once by ``semantic_view.derive_view``)
    so this module never imports the view and no import cycle exists. Pure: nothing is
    mutated; historical edges and versions are read only.
    """
    inactive = frozenset(state.applied_judgment_ids) - active_judgment_ids
    stale_versions = frozenset(
        version_id
        for version_id, version in state.issue_versions.items()
        if version.created_by_judgment_id in inactive
    )
    return descendants(state.derivations, inactive | stale_versions) | stale_versions

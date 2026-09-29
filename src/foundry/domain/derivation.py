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


def stale_object_ids(
    state: SemanticState,
    active_judgment_ids: frozenset[str],
    *,
    staleness_boundary_ids: frozenset[str] = frozenset(),
) -> frozenset[str]:
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

    **Claim-basis roots (R105-R107).** Two historical writers record ``object DERIVED_FROM
    SemanticClaim`` with different edge parents: frozen Slice-1 synthesis uses the claim's
    ``created_by_judgment_id``, IE2.1 generic admission uses the ``claim_id`` itself. Writer
    choice must not change what supersession means, so every claim asserted by an inactive
    judgment is also a traversal root, and both conventions propagate identically. Those
    claim ids are *causes*, like judgment ids: they are never returned for being superseded
    (R106). They are walked as a separate root set and unioned in, so the repair only ever
    ADDS descendants and can never drop an id the version/judgment walk already returns.
    History is untouched: no edge is rewritten; only this current-view projection widens.

    **Staleness boundaries (IE3 §17.2).** An id in ``staleness_boundary_ids`` is never
    returned and staleness never passes through it: every edge into it is left out of the
    traversal, never out of history. The boundary ids are root Intents
    (``intent_view.root_intent_ids``); ``SemanticState`` cannot tell object kinds, so a caller
    holding ``IntentState`` passes them through ``intent_view.derive_intent_view``. Their
    DERIVED_FROM edges stay recorded as provenance; they are only not a freshness dependency.

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
    stale_claim_roots = frozenset(
        claim_id
        for claim_id, claim in state.claims.items()
        if claim.created_by_judgment_id in inactive
    )
    edges = tuple(e for e in state.derivations if e.child_id not in staleness_boundary_ids)
    return (
        descendants(edges, inactive | stale_versions)
        | descendants(edges, stale_claim_roots)
        | stale_versions
    ) - staleness_boundary_ids

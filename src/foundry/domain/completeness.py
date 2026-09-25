"""Readiness diagnostics that complete the IE2 surface (IE2.5, R87-R94).

Pure projections, composed into ``IntentDeliveryReadiness``; none is a delivery blocker. Each
reuses an existing law rather than restating it:

* **open gap plans** -- every ``OPEN`` gap applicable to the scope (``gap_applies``, the one
  gap-scope law closure also uses), planned by IE2.4's ``gap_resolution_plan``. Blocking and
  non-blocking gaps alike: a plan says how a gap *may* be closed, and a blocking gap already
  blocks through closure. Unsupported-assumption impact arrives inside the plan (IE2.3 via
  IE2.4); nothing here recomputes it.
* **inert Decisions** (I-DEC-1) -- a current ``CANONICAL`` ProjectDecision applicable to the
  scope that no current applicable object names as a ``DERIVED_FROM`` target. The direction
  matters: a consequence object points *at* the Decision; the Decision's own basis and
  relevance edges are not its consequence. A consequence counts whatever its authority -- the
  question is whether anything uses the Decision, not whether that use is canonical yet.
  Report-only: no fork-dependency model exists that could prove a consequence is *required*.
* **Preferences** -- current Preferences applicable to the scope, any authority, matching the
  package's own reading. A Preference is never an obligation and never gates delivery.

Object-local relations only; ``DerivationEdge`` is never read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from foundry.domain.authority import object_is_current
from foundry.domain.common import Authority
from foundry.domain.events import derivation_parents_of
from foundry.domain.gap_resolution import GapResolutionPlan, gap_resolution_plan
from foundry.domain.gap_scope import gap_applies
from foundry.domain.gaps import GapStatus
from foundry.domain.scope import scope_applies
from foundry.domain.semantic import Preference, ProjectDecision, SemanticBase

if TYPE_CHECKING:
    from foundry.domain.state import IntentState

__all__ = [
    "scoped_inert_decision_ids",
    "scoped_open_gap_resolution_plans",
    "scoped_preference_ids",
]


def _live_in(obj: SemanticBase, scope: str) -> bool:
    return object_is_current(obj) and scope_applies(tuple(obj.scope), scope)


def scoped_open_gap_resolution_plans(
    state: IntentState, scope: str
) -> tuple[GapResolutionPlan, ...]:
    """IE2.4 plans for every open gap applicable to ``scope``, ordered by gap id."""
    return tuple(
        gap_resolution_plan(state, gap_id)
        for gap_id in sorted(state.gaps)
        if state.gaps[gap_id].status is GapStatus.OPEN
        and gap_applies(state, state.gaps[gap_id], scope)
    )


def scoped_inert_decision_ids(state: IntentState, scope: str) -> tuple[str, ...]:
    """Current canonical Decisions in ``scope`` that nothing current in ``scope`` derives from."""
    used: set[str] = set()
    for obj in state.objects.values():
        if _live_in(obj, scope):
            # A self-edge is history's malformation, not a consequence.
            used.update(p for p in derivation_parents_of(obj) if p != obj.id)
    return tuple(
        sorted(
            obj.id
            for obj in state.objects.values()
            if isinstance(obj, ProjectDecision)
            and obj.authority is Authority.CANONICAL
            and _live_in(obj, scope)
            and obj.id not in used
        )
    )


def scoped_preference_ids(state: IntentState, scope: str) -> tuple[str, ...]:
    """Current Preferences applicable to ``scope``, any authority. Never a blocker."""
    return tuple(
        sorted(
            obj.id
            for obj in state.objects.values()
            if isinstance(obj, Preference) and _live_in(obj, scope)
        )
    )

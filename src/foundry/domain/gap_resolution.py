"""Gap resolution routing (IE2.4, R70-R82).

``GapKind`` says **what** is wrong. ``GapResolutionRoute`` says **how** closure may proceed.
They are separate axes (R70, IE2 spec §10): the same ``UNSUPPORTED_ASSUMPTION`` may be closed
by research, by asking a human, or by honestly preserving the uncertainty, and none of that is
part of the diagnosis. So no route is stored on ``Gap`` or ``IntentSynthesisGap`` -- a route is
a pure projection over an open gap.

**Candidate is not selected (R71).** The durable gap schema does not carry enough to pick one
route for most kinds: ``MISSING_INFORMATION`` might be derivable, researchable, a human's to
answer, or unknowable today. A plan therefore lists the *lawful candidate routes*, and
``deterministic_route`` is set only when exactly one is lawful. Taking the first of several and
calling it a decision would fabricate a choice nobody made.

The five routes (R73):

* ``DERIVE`` -- close from trusted current Foundry state; no external fetch, no human decision.
  A certified reasoner may later do it; it does not mean "plain Python only".
* ``RESEARCH`` -- obtain new externally sourced evidence and claims, with provenance. Never
  creates canonical intent directly.
* ``ASK_HUMAN`` -- a preference, decision, authority act, clarification or project fact that
  Foundry must not invent.
* ``RECONCILE`` -- competing, stale or divergent material already in state must be reconciled,
  never silently picked between.
* ``PRESERVE_WAIT`` -- keep the uncertainty explicit because it cannot honestly be resolved now.
  It is **not** resolution, waiver, true or false: the gap stays ``OPEN`` and, if blocking,
  keeps blocking under the existing closure law (R81).

``UNSUPPORTED_ASSUMPTION`` plans carry the IE2.3 actionable blast radius of every Assumption the
gap names (R76), so a router can see what current intended state acting on it may touch. That
does not mean the assumption is false; nothing here records such a thing.

Routing is not authority and not execution (R78, R80). Nothing here appends an event, creates a
job, calls a model, resolves or waives a gap, or changes any object. ``route_is_allowed`` /
``assert_route_allowed`` are the single source of lawful selection for whatever executes a route
later (clarification, research, reconciliation, reasoning orchestration).
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from pydantic import model_validator

from foundry.domain.assumption_impact import actionable_assumption_blast_radius
from foundry.domain.common import FrozenModel
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.semantic import Assumption

if TYPE_CHECKING:
    from collections.abc import Mapping

    from foundry.domain.state import IntentState

__all__ = [
    "LAWFUL_ROUTES",
    "ROUTE_ORDER",
    "GapNotOpenError",
    "GapResolutionPlan",
    "GapResolutionRoute",
    "IllegalGapRouteError",
    "UnknownGapError",
    "assert_route_allowed",
    "gap_resolution_plan",
    "open_gap_resolution_plans",
    "route_is_allowed",
]


class GapResolutionRoute(StrEnum):
    DERIVE = "DERIVE"
    RESEARCH = "RESEARCH"
    ASK_HUMAN = "ASK_HUMAN"
    RECONCILE = "RECONCILE"
    PRESERVE_WAIT = "PRESERVE_WAIT"


ROUTE_ORDER: Final[tuple[GapResolutionRoute, ...]] = (
    GapResolutionRoute.DERIVE,
    GapResolutionRoute.RESEARCH,
    GapResolutionRoute.ASK_HUMAN,
    GapResolutionRoute.RECONCILE,
    GapResolutionRoute.PRESERVE_WAIT,
)
"""The canonical candidate order, written out rather than borrowed from enum iteration."""

_D = GapResolutionRoute.DERIVE
_R = GapResolutionRoute.RESEARCH
_H = GapResolutionRoute.ASK_HUMAN
_C = GapResolutionRoute.RECONCILE
_W = GapResolutionRoute.PRESERVE_WAIT

LAWFUL_ROUTES: Final[Mapping[GapKind, frozenset[GapResolutionRoute]]] = MappingProxyType(
    {
        GapKind.MISSING_INFORMATION: frozenset({_D, _R, _H, _W}),
        GapKind.AMBIGUITY: frozenset({_D, _H, _W}),
        GapKind.CONTRADICTION: frozenset({_R, _H, _C}),
        GapKind.UNSUPPORTED_ASSUMPTION: frozenset({_R, _H, _W}),
        GapKind.MISSING_AUTHORITY: frozenset({_H}),
        GapKind.MISSING_SUCCESS_METRIC: frozenset({_D, _H}),
        GapKind.MISSING_VERIFICATION_OBLIGATION: frozenset({_D, _H}),
        GapKind.UNRESOLVED_RISK: frozenset({_R, _H, _W}),
        GapKind.STALE_EVIDENCE: frozenset({_R}),
        GapKind.INSUFFICIENT_EVIDENCE: frozenset({_R, _W}),
        GapKind.UNDERSPECIFIED_SCOPE: frozenset({_H}),
        GapKind.UNRESOLVED_DEPENDENCY: frozenset({_D, _R, _H, _C, _W}),
        GapKind.WORKER_DIVERGENCE: frozenset({_C}),
        GapKind.CONTEXT_FAILURE: frozenset({_D}),
    }
)
"""R72: the lawful envelope per kind. What *may* close a gap -- never which one *will*."""


class GapResolutionPlan(FrozenModel):
    """How one open gap may be closed. Ids and routes only.

    A validated projection of ``LAWFUL_ROUTES``, never an independent authority (R83): a plan
    whose candidates or deterministic route disagree with the policy for its ``gap_kind``
    cannot be constructed, so a forged plan cannot smuggle a route past the policy.
    """

    gap_id: str
    gap_kind: GapKind
    candidate_routes: tuple[GapResolutionRoute, ...]
    affected_object_ids: tuple[str, ...]
    """The gap's own diagnosis, exactly as recorded -- never rewritten or filtered (R77)."""
    assumption_impact_ids: tuple[str, ...] = ()
    """For ``UNSUPPORTED_ASSUMPTION`` only: the IE2.3 actionable radius of named Assumptions."""
    deterministic_route: GapResolutionRoute | None = None
    """Set only when exactly one route is lawful. Workflow routing, never authority (R80)."""

    @model_validator(mode="after")
    def _consistent_with_policy(self) -> GapResolutionPlan:
        expected = _candidates(self.gap_kind)
        if self.candidate_routes != expected:
            raise ValueError(
                f"candidate_routes {[r.value for r in self.candidate_routes]} disagree with "
                f"LAWFUL_ROUTES for {self.gap_kind.value} {[r.value for r in expected]}"
            )
        decided = expected[0] if len(expected) == 1 else None
        if self.deterministic_route is not decided:
            raise ValueError(
                f"deterministic_route must be {decided} for {self.gap_kind.value} under "
                "LAWFUL_ROUTES: set exactly when one route is lawful, never chosen otherwise"
            )
        return self


class UnknownGapError(LookupError):
    """No gap with this id exists."""


class GapNotOpenError(ValueError):
    """A resolved or waived gap is not active work and has no route (R74)."""


class IllegalGapRouteError(ValueError):
    """The route is outside the lawful envelope for this gap's kind (R79)."""


def _candidates(kind: GapKind) -> tuple[GapResolutionRoute, ...]:
    lawful = LAWFUL_ROUTES[kind]
    return tuple(route for route in ROUTE_ORDER if route in lawful)


def _assumption_impact(state: IntentState, gap: Gap) -> tuple[str, ...]:
    if gap.kind is not GapKind.UNSUPPORTED_ASSUMPTION:
        return ()
    impacted: set[str] = set()
    for object_id in gap.affected_object_ids:
        obj = state.objects.get(object_id)
        # Dangling or non-Assumption ids stay in the diagnosis; they just expand to nothing.
        if isinstance(obj, Assumption) and obj.project_id == state.project_id:
            impacted.update(actionable_assumption_blast_radius(state, object_id))
    return tuple(sorted(impacted))


def _plan(state: IntentState, gap: Gap) -> GapResolutionPlan:
    candidates = _candidates(gap.kind)
    return GapResolutionPlan(
        gap_id=gap.id,
        gap_kind=gap.kind,
        candidate_routes=candidates,
        affected_object_ids=tuple(gap.affected_object_ids),
        assumption_impact_ids=_assumption_impact(state, gap),
        deterministic_route=candidates[0] if len(candidates) == 1 else None,
    )


def gap_resolution_plan(state: IntentState, gap_id: str) -> GapResolutionPlan:
    """The plan for one gap. Unknown or not-open gaps fail rather than get a fake route."""
    gap = state.gaps.get(gap_id)
    if gap is None:
        raise UnknownGapError(f"no gap {gap_id!r} in {state.project_id!r}")
    if gap.status is not GapStatus.OPEN:
        raise GapNotOpenError(
            f"gap {gap_id!r} is {gap.status.value}; a closed gap is not active work"
        )
    return _plan(state, gap)


def open_gap_resolution_plans(state: IntentState) -> tuple[GapResolutionPlan, ...]:
    """A plan for every open gap, ordered by gap id."""
    return tuple(
        _plan(state, state.gaps[gap_id])
        for gap_id in sorted(state.gaps)
        if state.gaps[gap_id].status is GapStatus.OPEN
    )


def route_is_allowed(plan: GapResolutionPlan, route: GapResolutionRoute) -> bool:
    """Is ``route`` lawful for this plan's gap? Read from the policy, never from the plan (R84).

    ``candidate_routes`` is projection data for consumers; the truth is ``LAWFUL_ROUTES``.
    """
    return route in LAWFUL_ROUTES[plan.gap_kind]


def assert_route_allowed(plan: GapResolutionPlan, route: GapResolutionRoute) -> None:
    """Refuse a route outside the lawful envelope; the policy must change first."""
    if not route_is_allowed(plan, route):
        lawful = ", ".join(r.value for r in _candidates(plan.gap_kind))
        raise IllegalGapRouteError(
            f"{route.value} is not a lawful route for gap {plan.gap_id!r} (lawful: {lawful})"
        )

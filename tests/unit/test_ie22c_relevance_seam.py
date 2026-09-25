"""IE2.2c — relevance and root completeness, at the IE2 seam and at v2 readiness.

One law, two timings, exactly like IE2.2b:

* the seam refuses a new ``CANONICAL`` relevance-bearing object that cannot prove an explicit
  ``SERVES`` path to a canonical root, before anything is appended;
* history replays unchanged, and v2 delivery readiness evaluates the same law per evaluated
  scope. Closure and the package never change.

Relevance is proved by explicit ``SERVES`` edges only -- never by shared scope, the existence
of a single Intent, a basis claim, statement text or synthesis origin.

Blocker codes are matched as strings so the seam's refusals are proven behaviourally and not
merely by the absence of a module.
"""

from __future__ import annotations

import pytest

from foundry.application.handoff_v2 import (
    IntentDeliveryNotReadyError,
    build_intent_decision_handoff_v2,
)
from foundry.application.package import build_intent_package
from foundry.application.replay import replay
from foundry.domain.closure import evaluate_closure
from foundry.domain.common import Authority, LifecycleStatus, RelationType, RiskLevel
from foundry.domain.semantic import Assumption, ConstraintFacet, SemanticObject
from foundry.domain.state import IntentState
from tests.unit._ie21_fixtures import (
    MODEL,
    PROJECT,
    SCOPE,
    SYSTEM_PROV,
    constraint,
    goal,
    intent,
    non_goal,
    outcome,
    preference,
    project_decision,
    rel,
    requirement,
)
from tests.unit._ie22b_fixtures import ROOT_ID, World

C = Authority.CANONICAL


def serves(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.SERVES, t) for t in targets)


def derived(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.DERIVED_FROM, t) for t in targets)


def refused(world: World, obj: SemanticObject, code: str) -> None:
    before = world.event_count()
    with pytest.raises(ValueError, match=code):
        world.admit_canonical(obj)
    assert world.event_count() == before, "a refusal appends nothing"


def admitted(world: World, obj: SemanticObject) -> None:
    world.admit_canonical(obj)
    assert world.governor.state().objects[obj.id].authority is obj.authority


def delivery_codes(state: IntentState, scope: str = SCOPE) -> tuple[str, ...]:
    try:
        build_intent_decision_handoff_v2(state, scope)
    except IntentDeliveryNotReadyError as error:
        return error.blocker_codes
    return ()


# --- admission: the positive controls -------------------------------------------------------


def test_a_requirement_serving_the_root_directly_is_admitted() -> None:
    world = World()
    world.admit_root()
    admitted(world, requirement("REQ-1", authority=C, relations=serves(ROOT_ID)))


def test_a_requirement_serving_a_goal_that_serves_the_root_is_admitted() -> None:
    world = World()
    world.admit_root()
    admitted(world, goal("GOAL-1", authority=C, relations=serves(ROOT_ID)))
    admitted(world, requirement("REQ-1", authority=C, relations=serves("GOAL-1")))


def test_a_scoped_requirement_may_serve_a_global_goal_and_a_global_root() -> None:
    """Scope is applicability, not containment."""
    world = World()
    world.admit_root(scope=())
    admitted(world, goal("GOAL-g", authority=C, scope=(), relations=serves(ROOT_ID)))
    admitted(
        world, requirement("REQ-1", authority=C, scope=("billing",), relations=serves("GOAL-g"))
    )


def test_one_bad_branch_does_not_matter_when_another_reaches_the_root() -> None:
    world = World()
    world.admit_root()
    world.governor.record_intent_object(goal("GOAL-p", relations=serves(ROOT_ID)), author=MODEL)
    admitted(world, goal("GOAL-ok", authority=C, relations=serves(ROOT_ID)))
    admitted(world, requirement("REQ-1", authority=C, relations=serves("GOAL-p", "GOAL-ok")))


@pytest.mark.parametrize(
    "build",
    [goal, outcome, requirement, non_goal, preference, project_decision],
    ids=["goal", "outcome", "requirement", "non_goal", "preference", "decision"],
)
def test_every_relevance_bearing_kind_needs_a_root_path(build) -> None:  # type: ignore[no-untyped-def]
    world = World()
    world.admit_root()
    refused(world, build("X-1", authority=C), "ORPHANED_CANONICAL_OBJECT")
    admitted(world, build("X-2", authority=C, relations=serves(ROOT_ID)))


def test_a_constraint_needs_a_root_path() -> None:
    world = World()
    world.admit_root()
    boundary = ConstraintFacet.PROJECT_BOUNDARY
    refused(world, constraint("CON-1", authority=C, facet=boundary), "ORPHANED_CANONICAL_OBJECT")
    admitted(world, constraint("CON-2", authority=C, facet=boundary, relations=serves(ROOT_ID)))


def test_the_root_intent_needs_no_serves() -> None:
    world = World()
    world.admit_root()
    assert world.governor.state().objects[ROOT_ID].authority is C


def test_non_canonical_objects_need_no_serves() -> None:
    world = World()
    world.governor.record_intent_object(requirement("REQ-p"), author=MODEL)
    assert world.governor.state().objects["REQ-p"].authority is Authority.PROPOSED


# --- admission: the refusals ----------------------------------------------------------------


def test_a_canonical_requirement_with_no_serves_is_refused() -> None:
    world = World()
    world.admit_root()
    refused(world, requirement("REQ-1", authority=C), "ORPHANED_CANONICAL_OBJECT")


def test_a_serves_chain_that_stops_before_the_root_is_refused() -> None:
    world = World()
    world.admit_root()
    world.legacy(goal("GOAL-stop", authority=C))  # canonical, but serves nothing
    refused(
        world,
        requirement("REQ-1", authority=C, relations=serves("GOAL-stop")),
        "ORPHANED_CANONICAL_OBJECT",
    )


def test_a_proposed_intermediate_does_not_prove_relevance() -> None:
    world = World()
    world.admit_root()
    world.governor.record_intent_object(goal("GOAL-p", relations=serves(ROOT_ID)), author=MODEL)
    refused(
        world,
        requirement("REQ-1", authority=C, relations=serves("GOAL-p")),
        "ORPHANED_CANONICAL_OBJECT",
    )


@pytest.mark.parametrize(
    ("lifecycle", "authority"),
    [
        (LifecycleStatus.SUPERSEDED, C),
        (LifecycleStatus.ACTIVE, Authority.SUPERSEDED),
        (LifecycleStatus.ACTIVE, Authority.REJECTED),
    ],
    ids=["superseded-lifecycle", "superseded-authority", "rejected-authority"],
)
def test_a_dead_intermediate_does_not_prove_relevance(
    lifecycle: LifecycleStatus, authority: Authority
) -> None:
    world = World()
    world.admit_root()
    world.legacy(
        goal("GOAL-d", authority=authority, lifecycle=lifecycle, relations=serves(ROOT_ID))
    )
    refused(
        world,
        requirement("REQ-1", authority=C, relations=serves("GOAL-d")),
        "ORPHANED_CANONICAL_OBJECT",
    )


def test_an_out_of_scope_intermediate_does_not_prove_relevance() -> None:
    world = World()
    world.admit_root(scope=())
    world.legacy(goal("GOAL-billing", authority=C, scope=("billing",), relations=serves(ROOT_ID)))
    refused(
        world,
        requirement("REQ-1", authority=C, relations=serves("GOAL-billing")),  # scope=payments
        "ORPHANED_CANONICAL_OBJECT",
    )


def test_a_non_canonical_root_does_not_terminate_a_path() -> None:
    world = World()
    world.governor.record_intent_object(intent(ROOT_ID), author=MODEL)
    refused(
        world,
        requirement("REQ-1", authority=C, relations=serves(ROOT_ID)),
        "ORPHANED_CANONICAL_OBJECT",
    )


def test_an_out_of_scope_root_does_not_terminate_a_path() -> None:
    world = World()
    world.admit_root(scope=("billing",))
    refused(
        world,
        requirement("REQ-1", authority=C, relations=serves(ROOT_ID)),  # scope=payments
        "ORPHANED_CANONICAL_OBJECT",
    )


def test_derived_from_is_not_relevance() -> None:
    world = World()
    world.admit_root()
    world.legacy(goal("GOAL-d", authority=C, relations=derived(ROOT_ID)))
    refused(
        world,
        requirement("REQ-1", authority=C, relations=serves("GOAL-d")),
        "ORPHANED_CANONICAL_OBJECT",
    )


def test_a_multi_scope_candidate_needs_a_path_in_every_declared_scope() -> None:
    world = World()
    world.admit_root("INTENT-billing", scope=("billing",))
    world.admit_root("INTENT-security", scope=("security",))
    # A path in billing only is not enough.
    refused(
        world,
        requirement(
            "REQ-1", authority=C, scope=("billing", "security"), relations=serves("INTENT-billing")
        ),
        "ORPHANED_CANONICAL_OBJECT",
    )
    admitted(
        world,
        requirement(
            "REQ-2",
            authority=C,
            scope=("billing", "security"),
            relations=serves("INTENT-billing", "INTENT-security"),
        ),
    )


def test_a_global_candidate_needs_a_global_path_to_a_global_root() -> None:
    """The only admission-time proof strong enough for every future scope."""
    world = World()
    world.admit_root("INTENT-billing", scope=("billing",))
    refused(
        world,
        requirement("REQ-g", authority=C, scope=(), relations=serves("INTENT-billing")),
        "ORPHANED_CANONICAL_OBJECT",
    )
    world.admit_root("INTENT-global", scope=())
    world.legacy(
        goal("GOAL-billing", authority=C, scope=("billing",), relations=serves("INTENT-global"))
    )
    refused(
        world,
        requirement("REQ-g2", authority=C, scope=(), relations=serves("GOAL-billing")),
        "ORPHANED_CANONICAL_OBJECT",
    )
    admitted(world, requirement("REQ-g3", authority=C, scope=(), relations=serves("INTENT-global")))


def test_a_historical_serves_cycle_terminates_and_does_not_prove_relevance() -> None:
    world = World()
    world.admit_root()
    world.legacy(
        goal("GOAL-a", authority=C, relations=serves("GOAL-b")),
        goal("GOAL-b", authority=C, relations=serves("GOAL-a")),
    )
    refused(
        world,
        requirement("REQ-1", authority=C, relations=serves("GOAL-a")),
        "ORPHANED_CANONICAL_OBJECT",
    )


# --- R59: a Decision used as a basis terminal must itself be relevant -----------------------


def test_a_decision_terminal_that_serves_the_root_is_accepted() -> None:
    world = World()
    world.admit_root()
    admitted(world, project_decision("DEC-1", authority=C, relations=serves(ROOT_ID)))
    admitted(
        world,
        requirement("REQ-1", authority=C, relations=derived("DEC-1") + serves(ROOT_ID)),
    )


def test_an_out_of_scope_decision_terminal_is_refused() -> None:
    world = World()
    world.admit_root(scope=())
    world.legacy(
        project_decision("DEC-b", authority=C, scope=("billing",), relations=serves(ROOT_ID))
    )
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("DEC-b") + serves(ROOT_ID)),
        "UNGROUNDED_CANONICAL_OBJECT",
    )


def test_an_orphaned_decision_terminal_is_refused() -> None:
    world = World()
    world.admit_root()
    world.legacy(project_decision("DEC-o", authority=C))  # applicable, but serves nothing
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("DEC-o") + serves(ROOT_ID)),
        "UNGROUNDED_CANONICAL_OBJECT",
    )


# --- readiness: history replays; closure and package unchanged; delivery refuses -------------


def _world_with_deliverable_root() -> World:
    world = World()
    world.admit_root()
    admitted(world, requirement("REQ-ok", authority=C, relations=serves(ROOT_ID)))
    return world


def test_a_rooted_scope_is_deliverable() -> None:
    world = _world_with_deliverable_root()
    handoff = build_intent_decision_handoff_v2(world.governor.state(), SCOPE)
    assert handoff.readiness.deliverable is True


def test_a_historical_orphan_closes_and_packages_but_does_not_deliver() -> None:
    world = _world_with_deliverable_root()
    orphan = requirement("REQ-orphan", authority=C)
    world.legacy(orphan)

    state = replay(PROJECT, world.store.load(PROJECT))
    assert state == world.governor.state()
    assert state.objects["REQ-orphan"] == orphan
    assert evaluate_closure(state, SCOPE).closed is True
    assert "REQ-orphan" in build_intent_package(state, SCOPE).obligation_ids
    assert delivery_codes(state) == ("ORPHANED_CANONICAL_OBJECT",)


def test_a_historical_object_reaching_a_dead_root_path_is_orphaned() -> None:
    world = _world_with_deliverable_root()
    world.legacy(
        goal("GOAL-p", relations=serves(ROOT_ID)),  # PROPOSED
        requirement("REQ-via-proposed", authority=C, relations=serves("GOAL-p")),
    )
    assert delivery_codes(world.governor.state()) == ("ORPHANED_CANONICAL_OBJECT",)


def test_non_relevance_bearing_kinds_are_never_orphaned() -> None:
    world = _world_with_deliverable_root()
    world.legacy(
        Assumption(
            id="ASM-1",
            project_id=PROJECT,
            authority=C,
            confidence=1.0,
            provenance=SYSTEM_PROV,
            created_at=goal().created_at,
            scope=(SCOPE,),
            statement="Refund volume stays low.",
            risk_level=RiskLevel.LOW,
        )
    )
    assert delivery_codes(world.governor.state()) == ()


def test_multiple_applicable_roots_block_delivery() -> None:
    world = _world_with_deliverable_root()
    world.legacy(intent("INTENT-second", authority=C))
    state = world.governor.state()
    assert evaluate_closure(state, SCOPE).closed is True
    # No ORPHANED judgement is fabricated against an arbitrary root.
    assert delivery_codes(state) == ("MULTIPLE_CANONICAL_ROOTS",)


def test_two_roots_in_unrelated_scopes_are_legal() -> None:
    world = World()
    world.admit_root("INTENT-billing", scope=("billing",))
    world.admit_root("INTENT-security", scope=("security",))
    admitted(
        world,
        requirement("REQ-b", authority=C, scope=("billing",), relations=serves("INTENT-billing")),
    )
    admitted(
        world,
        requirement("REQ-s", authority=C, scope=("security",), relations=serves("INTENT-security")),
    )
    state = world.governor.state()
    assert delivery_codes(state, "billing") == ()
    assert delivery_codes(state, "security") == ()


def test_a_global_root_plus_a_scoped_root_blocks_only_the_overlapping_scope() -> None:
    world = World()
    world.admit_root("INTENT-global", scope=())
    world.admit_root("INTENT-billing", scope=("billing",))
    admitted(world, requirement("REQ-g", authority=C, scope=(), relations=serves("INTENT-global")))
    admitted(
        world,
        requirement("REQ-s", authority=C, scope=("security",), relations=serves("INTENT-global")),
    )
    state = world.governor.state()
    assert "MULTIPLE_CANONICAL_ROOTS" in delivery_codes(state, "billing")
    assert delivery_codes(state, "security") == ()


def test_zero_roots_stays_a_closure_failure_not_a_new_code() -> None:
    world = World()
    world.legacy(requirement("REQ-1", authority=C))
    codes = delivery_codes(world.governor.state())
    assert "CLOSURE_NOT_MET" in codes
    assert not {"MULTIPLE_CANONICAL_ROOTS", "ORPHANED_CANONICAL_OBJECT"} & set(codes)


def test_a_historical_serves_cycle_is_diagnosed_even_beside_a_valid_path() -> None:
    world = _world_with_deliverable_root()
    world.legacy(
        goal("GOAL-a", authority=C, relations=serves("GOAL-b", ROOT_ID)),
        goal("GOAL-b", authority=C, relations=serves("GOAL-a")),
    )
    # Both goals reach the root, so nothing is orphaned -- the cycle is still reported.
    assert delivery_codes(world.governor.state()) == ("RELEVANCE_CYCLE",)


def test_a_diamond_is_not_a_cycle() -> None:
    world = _world_with_deliverable_root()
    admitted(world, goal("GOAL-top", authority=C, relations=serves(ROOT_ID)))
    admitted(world, goal("GOAL-l", authority=C, relations=serves("GOAL-top")))
    admitted(world, goal("GOAL-r", authority=C, relations=serves("GOAL-top")))
    admitted(world, requirement("REQ-d", authority=C, relations=serves("GOAL-l", "GOAL-r")))
    assert delivery_codes(world.governor.state()) == ()


def test_readiness_ignores_non_current_non_canonical_and_out_of_scope_orphans() -> None:
    world = _world_with_deliverable_root()
    world.legacy(
        requirement("REQ-old", authority=C, lifecycle=LifecycleStatus.SUPERSEDED),
        requirement("REQ-proposed"),
        requirement("REQ-billing", authority=C, scope=("billing",)),
    )
    assert delivery_codes(world.governor.state()) == ()


def test_a_historical_orphaned_decision_terminal_blocks_its_dependant() -> None:
    world = _world_with_deliverable_root()
    world.legacy(
        project_decision("DEC-o", authority=C),
        requirement("REQ-d", authority=C, relations=derived("DEC-o") + serves(ROOT_ID)),
    )
    handoff_state = world.governor.state()
    codes = delivery_codes(handoff_state)
    assert codes == ("ORPHANED_CANONICAL_OBJECT", "UNGROUNDED_CANONICAL_OBJECT")


def test_a_historical_out_of_scope_decision_terminal_blocks_its_dependant() -> None:
    world = World()
    world.admit_root("INTENT-global", scope=())
    admitted(world, requirement("REQ-ok", authority=C, relations=serves("INTENT-global")))
    world.legacy(
        project_decision(
            "DEC-b", authority=C, scope=("billing",), relations=serves("INTENT-global")
        ),
        requirement("REQ-d", authority=C, relations=derived("DEC-b") + serves("INTENT-global")),
    )
    assert delivery_codes(world.governor.state()) == ("UNGROUNDED_CANONICAL_OBJECT",)


def test_a_non_relevance_bearing_node_never_carries_a_path() -> None:
    """Only intended-state kinds are intermediates. History can hold a canonical Assumption
    that SERVES the root (IE2.1 forbids it now); leaning on it proves nothing."""
    world = _world_with_deliverable_root()
    world.legacy(
        Assumption(
            id="ASM-bridge",
            project_id=PROJECT,
            authority=C,
            confidence=1.0,
            provenance=SYSTEM_PROV,
            created_at=goal().created_at,
            scope=(SCOPE,),
            statement="A presumption is not intended state.",
            risk_level=RiskLevel.LOW,
            relations=serves(ROOT_ID),
        ),
        requirement("REQ-via-assumption", authority=C, relations=serves("ASM-bridge")),
    )
    assert delivery_codes(world.governor.state()) == ("ORPHANED_CANONICAL_OBJECT",)


def test_an_out_of_scope_decision_terminal_blocks_even_when_roots_are_ambiguous() -> None:
    """With several roots, relevance is not judged against an arbitrary one -- but a
    Decision that does not even apply to the scope still cannot ground anything here."""
    world = _world_with_deliverable_root()
    world.legacy(
        intent("INTENT-second", authority=C),
        project_decision("DEC-b", authority=C, scope=("billing",)),
        requirement("REQ-d", authority=C, relations=derived("DEC-b") + serves(ROOT_ID)),
    )
    assert delivery_codes(world.governor.state()) == (
        "MULTIPLE_CANONICAL_ROOTS",
        "UNGROUNDED_CANONICAL_OBJECT",
    )

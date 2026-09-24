"""IE2.1 — NonGoal enforcement, the delivery split, Constraint facets, ProjectDecision.

These are the types that existed as shapes without semantics. Before IE2.1 a `NonGoal`
appeared in the handoff and was enforced by nothing, and the delivery contract handed
Architecture one bucket containing both "we will never build billing" and "prefer boring
technology" — no way to tell what may be traded from what must never be reintroduced.
"""

from __future__ import annotations

import pytest

from foundry.application.package import build_intent_package
from foundry.domain.closure import evaluate_closure
from foundry.domain.common import Authority, RelationType
from foundry.domain.semantic import (
    Constraint,
    ConstraintFacet,
    Decision,
    ProjectDecision,
    SemanticKind,
)
from foundry.domain.state import IntentState
from tests.unit._ie21_fixtures import (
    PROJECT,
    SCOPE,
    constraint,
    goal,
    intent,
    non_goal,
    outcome,
    preference,
    rel,
    requirement,
)


def state_of(*objects: object) -> IntentState:
    return IntentState(project_id=PROJECT, objects={o.id: o for o in objects})  # type: ignore[attr-defined]


def codes(state: IntentState, scope: str = SCOPE) -> set[str]:
    return {b.code for b in evaluate_closure(state, scope).blockers}


CANON = {"authority": Authority.CANONICAL}


# --- NonGoal enforcement -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "builder"),
    [("REQ-1", requirement), ("CON-1", constraint), ("GOAL-1", goal), ("OUT-1", outcome)],
)
def test_a_canonical_non_goal_blocks_what_it_explicitly_excludes(target, builder) -> None:
    ng = non_goal(relations=(rel(RelationType.EXCLUDES, target),), **CANON)
    state = state_of(intent(**CANON), ng, builder(target, **CANON))
    assert "EXCLUDED_BY_NON_GOAL" in codes(state)


def test_a_non_canonical_non_goal_blocks_nothing() -> None:
    ng = non_goal(relations=(rel(RelationType.EXCLUDES, "REQ-1"),))
    state = state_of(intent(**CANON), ng, requirement(**CANON))
    assert "EXCLUDED_BY_NON_GOAL" not in codes(state)


def test_a_non_canonical_target_is_not_yet_a_conflict() -> None:
    ng = non_goal(relations=(rel(RelationType.EXCLUDES, "REQ-1"),), **CANON)
    state = state_of(intent(**CANON), ng, requirement())
    assert "EXCLUDED_BY_NON_GOAL" not in codes(state)


def test_exclusion_is_scoped() -> None:
    """I-EXCL-2: a non-goal constrains only within its own scope."""
    ng = non_goal(relations=(rel(RelationType.EXCLUDES, "REQ-1"),), scope=("other",), **CANON)
    state = state_of(intent(**CANON), ng, requirement(**CANON))
    assert "EXCLUDED_BY_NON_GOAL" not in codes(state)


def test_exclusion_needs_an_explicit_edge_not_contradictory_prose() -> None:
    """IE2.1 claims no inference from statement text, and this pins that boundary."""
    ng = non_goal(statement="We will never support refunds at all.", **CANON)
    state = state_of(intent(**CANON), ng, requirement(**CANON))
    assert "EXCLUDED_BY_NON_GOAL" not in codes(state)


# --- delivery split ------------------------------------------------------------------------


def closed_state() -> IntentState:
    return state_of(
        intent(**CANON),
        requirement(**CANON),
        non_goal(**CANON),
        preference(**CANON),
    )


def test_exclusions_and_preferences_are_delivered_separately() -> None:
    package = build_intent_package(closed_state(), SCOPE)
    assert package.exclusion_ids == ("NG-1",)
    assert package.preference_ids == ("PREF-1",)


def test_boundary_ids_remains_exactly_the_union() -> None:
    """Compatibility pin: the deprecated field cannot drift from the authoritative ones."""
    package = build_intent_package(closed_state(), SCOPE)
    assert package.boundary_ids == tuple(sorted(package.exclusion_ids + package.preference_ids))


def test_a_preference_never_becomes_an_obligation() -> None:
    """I-STR-1. The type carries the strength; nothing may promote it silently."""
    package = build_intent_package(closed_state(), SCOPE)
    assert "PREF-1" not in package.obligation_ids
    assert "NG-1" not in package.obligation_ids


def test_a_decision_never_becomes_an_obligation() -> None:
    """I-DEC-2: decisions are delivered on their own channel."""
    package = build_intent_package(closed_state(), SCOPE)
    assert all(not oid.startswith("DEC-") for oid in package.obligation_ids)


# --- Constraint facets ---------------------------------------------------------------------


def test_the_three_facets_classify_relaxation_not_topic() -> None:
    assert [f.value for f in ConstraintFacet] == [
        "EXTERNAL_MANDATE",
        "PROJECT_BOUNDARY",
        "EVIDENCE_BOUND",
    ]
    for rejected in ("TECHNICAL", "REGULATORY", "SCOPE_BOUNDARY", "INVARIANT", "BUSINESS"):
        assert not hasattr(ConstraintFacet, rejected), f"{rejected} was rejected by R19"


def test_a_constraint_without_a_facet_still_replays() -> None:
    """Historical constraints carry no facet; the field must never be required."""
    legacy = Constraint.model_validate(constraint().model_dump(mode="json"))
    assert legacy.facet is None


def test_a_facet_round_trips() -> None:
    con = constraint(facet=ConstraintFacet.EXTERNAL_MANDATE)
    assert Constraint.model_validate(con.model_dump(mode="json")).facet is (
        ConstraintFacet.EXTERNAL_MANDATE
    )


def test_no_generic_negotiability_field_was_introduced() -> None:
    """R5: strength lives in the type, not in a cross-cutting flag."""
    for model in (constraint(), preference(), requirement(), non_goal()):
        assert "negotiable" not in type(model).model_fields
        assert "negotiability" not in type(model).model_fields


# --- ProjectDecision -----------------------------------------------------------------------


def test_the_rename_is_serialization_neutral() -> None:
    assert Decision is ProjectDecision
    assert ProjectDecision.model_fields["kind"].default is SemanticKind.DECISION


def test_a_decision_is_intent_bearing_but_not_an_obligation_type() -> None:
    from foundry.domain.intent_synthesis import INTENT_BEARING_SEMANTIC_KINDS

    assert SemanticKind.DECISION in INTENT_BEARING_SEMANTIC_KINDS


def test_an_out_of_scope_excluded_object_is_not_blocked() -> None:
    """Scope is checked on the *excluded* object, not only on the non-goal.

    A non-goal in this scope must not reach across into another scope's canonical work.
    """
    ng = non_goal(relations=(rel(RelationType.EXCLUDES, "REQ-1"),), **CANON)
    elsewhere = requirement(scope=("other",), **CANON)
    state = state_of(intent(**CANON), ng, elsewhere)
    assert "EXCLUDED_BY_NON_GOAL" not in codes(state)

"""IE2.2c — the relevance/root law as pure domain functions shared by seam and readiness."""

from __future__ import annotations

import pytest

from foundry.domain.basis import basis_decision_terminals
from foundry.domain.common import Authority, RelationType
from foundry.domain.relevance import (
    MULTIPLE_CANONICAL_ROOTS,
    ORPHANED_CANONICAL_OBJECT,
    RELEVANCE_BEARING_KINDS,
    RELEVANCE_BLOCKER_CODES,
    RELEVANCE_CYCLE,
    RelevanceBlocker,
    canonical_roots,
    relevance_blockers,
)
from foundry.domain.scope import scope_applies
from foundry.domain.semantic import SemanticKind
from tests.unit._ie21_fixtures import SCOPE, goal, project_decision, rel, requirement
from tests.unit._ie22b_fixtures import ROOT_ID, World

C = Authority.CANONICAL


def serves(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.SERVES, t) for t in targets)


def derived(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.DERIVED_FROM, t) for t in targets)


def test_the_relevance_bearing_kinds_are_the_explicit_set() -> None:
    assert (
        frozenset(
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
        == RELEVANCE_BEARING_KINDS
    )


def test_the_codes_are_the_spec_codes_in_order() -> None:
    assert (MULTIPLE_CANONICAL_ROOTS, ORPHANED_CANONICAL_OBJECT, RELEVANCE_CYCLE) == (
        "MULTIPLE_CANONICAL_ROOTS",
        "ORPHANED_CANONICAL_OBJECT",
        "RELEVANCE_CYCLE",
    )
    assert RELEVANCE_BLOCKER_CODES == (
        MULTIPLE_CANONICAL_ROOTS,
        ORPHANED_CANONICAL_OBJECT,
        RELEVANCE_CYCLE,
    )


@pytest.mark.parametrize(
    ("descriptor", "evaluated", "expected"),
    [
        ((), "billing", True),
        (("billing",), "billing", True),
        (("billing", "security"), "security", True),
        (("billing",), "security", False),
    ],
)
def test_scope_applies_is_applicability_not_containment(
    descriptor: tuple[str, ...], evaluated: str, expected: bool
) -> None:
    assert scope_applies(descriptor, evaluated) is expected


def test_roots_are_current_canonical_applicable_intents_sorted() -> None:
    world = World()
    world.admit_root("INTENT-z", scope=())
    world.admit_root("INTENT-a", scope=(SCOPE,))
    world.admit_root("INTENT-other", scope=("billing",))
    assert canonical_roots(world.governor.state(), SCOPE) == ("INTENT-a", "INTENT-z")


def test_a_cycle_reports_its_participants_deterministically() -> None:
    world = World()
    world.admit_root()
    world.legacy(
        goal("GOAL-c", authority=C, relations=serves("GOAL-a")),
        goal("GOAL-a", authority=C, relations=serves("GOAL-b")),
        goal("GOAL-b", authority=C, relations=serves("GOAL-c")),
    )
    blockers = relevance_blockers(world.governor.state(), SCOPE)
    assert (
        RelevanceBlocker(code=RELEVANCE_CYCLE, object_ids=("GOAL-a", "GOAL-b", "GOAL-c"))
        in blockers
    )
    assert blockers == relevance_blockers(world.governor.state(), SCOPE)


def test_a_self_serving_object_is_a_cycle() -> None:
    world = World()
    world.admit_root()
    world.legacy(goal("GOAL-self", authority=C, relations=serves("GOAL-self", ROOT_ID)))
    assert relevance_blockers(world.governor.state(), SCOPE) == (
        RelevanceBlocker(code=RELEVANCE_CYCLE, object_ids=("GOAL-self",)),
    )


def test_a_long_historical_chain_does_not_exhaust_the_stack() -> None:
    world = World()
    world.admit_root()
    chain = [goal("G0", authority=C, relations=serves(ROOT_ID))]
    for i in range(1, 3000):
        chain.append(goal(f"G{i}", authority=C, relations=serves(f"G{i - 1}")))
    world.legacy(*chain)
    assert relevance_blockers(world.governor.state(), SCOPE) == ()


def test_multiple_roots_name_every_root_and_fabricate_no_orphan() -> None:
    world = World()
    world.admit_root("INTENT-a")
    world.admit_root("INTENT-b", scope=())
    world.legacy(requirement("REQ-orphan", authority=C))
    assert relevance_blockers(world.governor.state(), SCOPE) == (
        RelevanceBlocker(code=MULTIPLE_CANONICAL_ROOTS, object_ids=("INTENT-a", "INTENT-b")),
    )


def test_an_orphan_names_itself() -> None:
    world = World()
    world.admit_root()
    world.legacy(requirement("REQ-orphan", authority=C))
    assert relevance_blockers(world.governor.state(), SCOPE) == (
        RelevanceBlocker(code=ORPHANED_CANONICAL_OBJECT, object_ids=("REQ-orphan",)),
    )


# --- the one helper basis.py exposes for R59 -------------------------------------------------


def test_basis_reports_the_decision_terminals_its_lawful_basis_uses() -> None:
    world = World()
    world.admit_root()
    claim = world.claim("J-c", authority=C)
    world.legacy(
        project_decision("DEC-2", authority=C),
        project_decision("DEC-1", authority=C, relations=derived(claim)),
        goal("GOAL-mid", authority=C, relations=derived("DEC-2")),
    )
    obj = requirement("REQ-1", authority=C, relations=derived("DEC-1", "GOAL-mid", claim))
    assert basis_decision_terminals(world.governor.state(), obj) == ("DEC-1", "DEC-2")
    assert basis_decision_terminals(world.governor.state(), requirement("R", authority=C)) == ()

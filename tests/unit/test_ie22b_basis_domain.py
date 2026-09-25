"""IE2.2b — the basis law as a pure domain function.

The seam and readiness must evaluate *one* law. These tests pin the shared function both
call, so that a refusal at admission and a blocker at readiness cannot drift apart.
"""

from __future__ import annotations

import pytest

from foundry.domain import authority as authority_module
from foundry.domain import closure as closure_module
from foundry.domain.basis import (
    ASSUMPTION_IN_BASIS,
    BASIS_CYCLE,
    DEAD_BASIS,
    UNGROUNDED_CANONICAL_OBJECT,
    UNLAWFUL_BASIS_AUTHORITY,
    BasisDefect,
    UnlawfulBasisError,
    assert_lawful_basis,
    basis_defects,
)
from foundry.domain.common import Authority, LifecycleStatus, RelationType
from tests.unit._ie21_fixtures import goal, rel, requirement
from tests.unit._ie22b_fixtures import World

C = Authority.CANONICAL


def derived(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.DERIVED_FROM, t) for t in targets)


def test_the_codes_are_the_spec_codes() -> None:
    assert (
        UNGROUNDED_CANONICAL_OBJECT,
        DEAD_BASIS,
        UNLAWFUL_BASIS_AUTHORITY,
        ASSUMPTION_IN_BASIS,
        BASIS_CYCLE,
    ) == (
        "UNGROUNDED_CANONICAL_OBJECT",
        "DEAD_BASIS",
        "UNLAWFUL_BASIS_AUTHORITY",
        "ASSUMPTION_IN_BASIS",
        "BASIS_CYCLE",
    )


def test_a_lawful_basis_has_no_defects_and_does_not_raise() -> None:
    world = World()
    claim = world.claim("J-c", authority=C)
    obj = requirement("REQ-1", authority=C, relations=derived(claim))
    assert basis_defects(world.governor.state(), obj) == ()
    assert_lawful_basis(world.governor.state(), obj)


def test_a_defect_names_the_object_and_the_offending_node() -> None:
    world = World()
    weak = world.claim("J-w", authority=Authority.INFERRED)
    world.legacy(goal("GOAL-mid", authority=C, relations=derived(weak)))
    obj = requirement("REQ-1", authority=C, relations=derived("GOAL-mid"))

    (defect,) = basis_defects(world.governor.state(), obj)
    assert isinstance(defect, BasisDefect)
    assert defect.code == UNLAWFUL_BASIS_AUTHORITY
    assert defect.object_id == "REQ-1"
    assert defect.node_id == weak
    assert defect.reason


def test_the_refusal_is_a_value_error_carrying_the_code() -> None:
    world = World()
    obj = requirement("REQ-1", authority=C, relations=derived("GHOST"))
    with pytest.raises(UnlawfulBasisError, match=UNGROUNDED_CANONICAL_OBJECT) as info:
        assert_lawful_basis(world.governor.state(), obj)
    assert isinstance(info.value, ValueError)


def test_defects_are_reported_per_declared_root_in_a_deterministic_order() -> None:
    world = World()
    weak = world.claim("J-w", authority=Authority.INFERRED)
    obj = requirement("REQ-1", authority=C, relations=derived("GHOST", weak))
    first = basis_defects(world.governor.state(), obj)
    assert first == basis_defects(world.governor.state(), obj)
    assert {d.code for d in first} == {UNGROUNDED_CANONICAL_OBJECT, UNLAWFUL_BASIS_AUTHORITY}
    assert [d.node_id for d in first] == sorted(d.node_id for d in first)


def test_a_long_historical_chain_does_not_exhaust_the_stack() -> None:
    world = World()
    claim = world.claim("J-c", authority=C)
    chain = [goal("G0", authority=C, relations=derived(claim))]
    for i in range(1, 3000):
        chain.append(goal(f"G{i}", authority=C, relations=derived(f"G{i - 1}")))
    world.legacy(*chain)
    obj = requirement("REQ-1", authority=C, relations=derived("G2999"))
    assert basis_defects(world.governor.state(), obj) == ()


def test_a_cycle_the_object_itself_would_close_is_a_basis_cycle() -> None:
    """Readiness evaluates objects already in state, so the object's own id is on the path."""
    world = World()
    world.legacy(goal("GOAL-a", authority=C, relations=derived("REQ-1")))
    obj = requirement("REQ-1", authority=C, relations=derived("GOAL-a"))
    world.legacy(obj)
    codes = {d.code for d in basis_defects(world.governor.state(), obj)}
    assert codes == {BASIS_CYCLE}


# --- one definition of "current" -----------------------------------------------------------


@pytest.mark.parametrize(
    ("lifecycle", "authority", "expected"),
    [
        (LifecycleStatus.ACTIVE, C, True),
        (LifecycleStatus.ACTIVE, Authority.PROPOSED, True),
        (LifecycleStatus.SUPERSEDED, C, False),
        (LifecycleStatus.ACTIVE, Authority.SUPERSEDED, False),
        (LifecycleStatus.ACTIVE, Authority.REJECTED, False),
    ],
)
def test_object_is_current_is_the_single_liveness_rule(
    lifecycle: LifecycleStatus, authority: Authority, expected: bool
) -> None:
    obj = goal("G", authority=authority, lifecycle=lifecycle)
    assert authority_module.object_is_current(obj) is expected
    assert closure_module._is_current(obj) is expected  # noqa: SLF001


def test_a_claim_whose_cited_evidence_is_absent_grounds_nothing() -> None:
    """Defensive: governance never admits a claim without its evidence and evidence is
    never deleted, so this state is hand-built. The law must stand on its own anyway --
    "every cited evidence id exists" is one of the four terminal conditions (R35)."""
    world = World()
    claim = world.claim("J-c", authority=C)
    state = world.governor.state()
    hollow = state.model_copy(
        update={"semantic": state.semantic.model_copy(update={"evidence": {}})}
    )
    obj = requirement("REQ-1", authority=C, relations=derived(claim))
    assert basis_defects(state, obj) == ()
    (defect,) = basis_defects(hollow, obj)
    assert (defect.code, defect.node_id) == (UNGROUNDED_CANONICAL_OBJECT, claim)

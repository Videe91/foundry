"""Writer-independent claim-basis staleness (IE2 repair, R105-R107; IE3 design §30).

Two writers record the same dependency, ``object DERIVED_FROM SemanticClaim``, with different
edge parents:

* frozen Slice-1 synthesis (and the generic ``derive`` seam as used for it) hangs the child off
  ``claim.created_by_judgment_id``;
* IE2.1 generic admission (``INTENT_OBJECT_ADMITTED``) hangs it off the ``claim_id`` itself.

Superseding the judgment that asserted the claim must make both children stale. Writer choice
is history, not semantics. Every world here is built through the real governed path: evidence
ingested, address and claim asserted by a human, admission applied, then objects admitted
through ``record_intent_object`` or edges recorded through ``derive``. No ``SemanticState`` is
assembled by hand.
"""

from __future__ import annotations

from foundry.application.replay import replay
from foundry.domain.common import Authority, RelationType
from foundry.domain.derivation import stale_object_ids
from foundry.domain.events import EventType
from foundry.domain.semantic_view import active_judgment_ids, derive_view
from foundry.domain.state import IntentState
from tests.unit._ie21_fixtures import ALICE, HUMAN, PROJECT, rel, requirement
from tests.unit._ie22b_fixtures import World

D = RelationType.DERIVED_FROM


def _state(world: World) -> IntentState:
    return replay(PROJECT, world.store.load(PROJECT))


def _stale(world: World) -> frozenset[str]:
    return frozenset(derive_view(_state(world).semantic).stale_ids)


def _admit(world: World, object_id: str, *parents: str) -> None:
    """The real IE2.1 generic writer: ``INTENT_OBJECT_ADMITTED`` with DERIVED_FROM parents."""
    world.governor.record_intent_object(
        requirement(object_id, relations=tuple(rel(D, p) for p in parents)),
        author=HUMAN,
        human_actor_id=ALICE,
    )


def _claim_world(judgment_id: str = "J-claim") -> tuple[World, str]:
    world = World()
    return world, world.claim(judgment_id, authority=Authority.CANONICAL)


def _edge_parents(world: World, child_id: str) -> tuple[str, ...]:
    return tuple(
        edge.parent_id for edge in _state(world).semantic.derivations if edge.child_id == child_id
    )


# ---------------------------------------------------------------- 1. the generic writer


def test_generic_admission_records_the_claim_id_as_the_edge_parent() -> None:
    """The precondition of the defect: this writer really uses the claim-id convention."""
    world, claim = _claim_world()
    _admit(world, "REQ-generic", claim)
    assert _edge_parents(world, "REQ-generic") == (claim,)
    events = world.store.load(PROJECT)
    assert events[-1].event.event_type is EventType.INTENT_OBJECT_ADMITTED


def test_generic_admission_child_goes_stale_when_its_claim_is_superseded() -> None:
    world, claim = _claim_world()
    _admit(world, "REQ-generic", claim)
    assert "REQ-generic" not in _stale(world)

    world.supersede("J-sup", "J-claim")

    assert "REQ-generic" in _stale(world)


# ---------------------------------------------------------- 2. the frozen Slice-1 convention


def test_judgment_parent_convention_still_goes_stale() -> None:
    world, claim = _claim_world()
    judgment = _state(world).semantic.claims[claim].created_by_judgment_id
    world.governor.derive("REQ-slice1", judgment)
    assert "REQ-slice1" not in _stale(world)

    world.supersede("J-sup", "J-claim")

    assert "REQ-slice1" in _stale(world)


# --------------------------------------------------------------------- 3. writer parity


def test_both_conventions_agree_after_supersession() -> None:
    world, claim = _claim_world()
    judgment = _state(world).semantic.claims[claim].created_by_judgment_id
    world.governor.derive("REQ-by-judgment", judgment)  # convention A
    _admit(world, "REQ-by-claim", claim)  # convention B, the real IE2.1 writer
    world.governor.derive("D-by-claim", claim)  # convention B, the generic derive seam
    before = _stale(world)
    assert {"REQ-by-judgment", "REQ-by-claim", "D-by-claim"}.isdisjoint(before)

    world.supersede("J-sup", "J-claim")

    after = _stale(world)
    assert {"REQ-by-judgment", "REQ-by-claim", "D-by-claim"} <= after


# ----------------------------------------------------------------- 4. an active claim


def test_a_live_claim_does_not_stale_its_children() -> None:
    world, claim = _claim_world()
    _admit(world, "REQ-generic", claim)
    world.governor.derive("D-by-claim", claim)
    # Unrelated supersession elsewhere in the project changes nothing for this claim.
    other = world.claim("J-other", authority=Authority.CANONICAL, text="sixty days")
    world.supersede("J-sup-other", "J-other")
    stale = _stale(world)
    assert "REQ-generic" not in stale
    assert "D-by-claim" not in stale
    assert other not in stale


# ------------------------------------------------------------------ 5. transitive reach


def test_staleness_propagates_through_an_object_chain_hung_from_a_claim() -> None:
    world, claim = _claim_world()
    _admit(world, "REQ-A", claim)
    _admit(world, "REQ-B", "REQ-A")
    assert _edge_parents(world, "REQ-B") == ("REQ-A",)
    assert {"REQ-A", "REQ-B"}.isdisjoint(_stale(world))

    world.supersede("J-sup", "J-claim")

    assert {"REQ-A", "REQ-B"} <= _stale(world)


# ------------------------------------------------------------------ 6. mixed claim bases


def test_one_superseded_claim_in_a_mixed_basis_stales_the_object() -> None:
    world = World()
    claim_a = world.claim("J-a", authority=Authority.CANONICAL, text="thirty days")
    claim_b = world.claim("J-b", authority=Authority.CANONICAL, text="thirty calendar days")
    _admit(world, "REQ-mixed", claim_a, claim_b)
    assert "REQ-mixed" not in _stale(world)

    world.supersede("J-sup-b", "J-b")

    assert "REQ-mixed" in _stale(world)


def test_a_mixed_basis_of_live_claims_stays_clean() -> None:
    world = World()
    claim_a = world.claim("J-a", authority=Authority.CANONICAL, text="thirty days")
    claim_b = world.claim("J-b", authority=Authority.CANONICAL, text="thirty calendar days")
    _admit(world, "REQ-mixed", claim_a, claim_b)
    assert "REQ-mixed" not in _stale(world)


# ------------------------------------------------------------------- 7. reactivation


def test_superseding_the_superseder_restores_claim_id_children() -> None:
    world, claim = _claim_world()
    _admit(world, "REQ-generic", claim)
    world.governor.derive("D-by-claim", claim)
    world.supersede("J-sup", "J-claim")
    assert {"REQ-generic", "D-by-claim"} <= _stale(world)

    world.supersede("J-sup-sup", "J-sup")

    restored = _stale(world)
    assert "J-claim" in active_judgment_ids(_state(world).semantic)
    assert "REQ-generic" not in restored
    assert "D-by-claim" not in restored


def test_a_restored_claim_can_stale_its_children_again() -> None:
    world, claim = _claim_world()
    _admit(world, "REQ-generic", claim)
    world.supersede("J-sup", "J-claim")
    world.supersede("J-sup-sup", "J-sup")
    assert "REQ-generic" not in _stale(world)

    world.supersede("J-sup-again", "J-claim")

    assert "REQ-generic" in _stale(world)


# ------------------------------------------------------- 8. the claim is a cause, not output


def test_the_superseded_claim_itself_is_not_returned_as_stale() -> None:
    world, claim = _claim_world()
    _admit(world, "REQ-generic", claim)

    world.supersede("J-sup", "J-claim")

    stale = _stale(world)
    assert "REQ-generic" in stale
    assert claim not in stale
    assert "J-claim" not in stale  # the judgment was never returned either


def test_a_superseded_claim_with_no_children_adds_nothing() -> None:
    world, claim = _claim_world()
    before = _stale(world)
    world.supersede("J-sup", "J-claim")
    state = _state(world)
    assert claim not in stale_object_ids(state.semantic, active_judgment_ids(state.semantic))
    assert _stale(world) - before == frozenset(
        v
        for v, version in state.semantic.issue_versions.items()
        if version.created_by_judgment_id == "J-claim"
    )


# -------------------------------------------------------------- history is unchanged (R107)


def test_the_repair_never_alters_recorded_edges_or_replay() -> None:
    world, claim = _claim_world()
    _admit(world, "REQ-generic", claim)
    world.supersede("J-sup", "J-claim")
    events = world.store.load(PROJECT)
    first = _state(world)
    second = replay(PROJECT, events)
    assert first == second
    assert _edge_parents(world, "REQ-generic") == (claim,)
    assert [s.event.event_id for s in world.store.load(PROJECT)] == [
        s.event.event_id for s in events
    ]

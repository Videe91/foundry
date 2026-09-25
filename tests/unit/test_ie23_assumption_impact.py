"""IE2.3 — assumption dependency and blast radius (R63-R69).

The blast radius of an Assumption is exactly:

    direct explicit AFFECTS targets
    + every object that transitively DERIVED_FROM one of them

read from object-local relations only -- never ``DerivationEdge``, whose historical parent-id
conventions differ. Nothing else propagates: not SERVES (relevance, R64), not EXCLUDES (a
closure rule, R69), not any other relation.

Two results, deliberately separate (R66): the **historical** radius is everything the ledger's
dependency structure reaches, walked through dead intermediates; the **actionable** radius is
the current subset. A dead intermediate never hides a live descendant.

It is a projection. Nothing here appends, supersedes, stales or creates a gap.

The module is imported lazily per test so that, before it exists, every case fails on its
own rather than the whole file failing at collection.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest

from foundry.application.replay import replay
from foundry.domain.closure import evaluate_closure
from foundry.domain.common import Authority, LifecycleStatus, RelationType, RiskLevel
from foundry.domain.semantic import Assumption, SemanticObject
from foundry.domain.state import IntentState
from tests.unit._ie21_fixtures import (
    AT,
    MODEL,
    PROJECT,
    SCOPE,
    SYSTEM_PROV,
    constraint,
    goal,
    non_goal,
    rel,
    requirement,
)
from tests.unit._ie22b_fixtures import World

C = Authority.CANONICAL
MODULE = "foundry.domain.assumption_impact"


@pytest.fixture
def impact() -> ModuleType:
    return importlib.import_module(MODULE)


def derived(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.DERIVED_FROM, t) for t in targets)


def affects(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.AFFECTS, t) for t in targets)


def assumption(object_id: str = "ASM-1", *targets: str, **overrides: object) -> Assumption:
    payload: dict[str, object] = {
        "project_id": PROJECT,
        "authority": Authority.PROPOSED,
        "confidence": 0.6,
        "provenance": SYSTEM_PROV,
        "created_at": AT,
        "scope": (SCOPE,),
        "statement": "Refund volume stays below a thousand a day.",
        "risk_level": RiskLevel.MEDIUM,
        "relations": affects(*targets),
    }
    payload.update(overrides)
    return Assumption(id=object_id, **payload)  # type: ignore[arg-type]


def world(*objects: SemanticObject) -> World:
    w = World()
    w.legacy(*objects)
    return w


def radius(impact: ModuleType, w: World, asm: str = "ASM-1") -> tuple[str, ...]:
    return impact.assumption_blast_radius(w.governor.state(), asm)  # type: ignore[no-any-return]


def actionable(impact: ModuleType, w: World, asm: str = "ASM-1") -> tuple[str, ...]:
    return impact.actionable_assumption_blast_radius(w.governor.state(), asm)  # type: ignore[no-any-return]


# --- direct impact --------------------------------------------------------------------------


def test_direct_impact_is_the_explicit_affects_target(impact: ModuleType) -> None:
    w = world(requirement("REQ-A", authority=C), assumption("ASM-1", "REQ-A"))
    assert impact.direct_assumption_impacts(w.governor.state(), "ASM-1") == ("REQ-A",)


def test_every_direct_target_is_returned_sorted(impact: ModuleType) -> None:
    w = world(
        requirement("REQ-C", authority=C),
        goal("GOAL-A", authority=C),
        requirement("REQ-B", authority=C),
        assumption("ASM-1", "REQ-C", "GOAL-A", "REQ-B"),
    )
    expected = ("GOAL-A", "REQ-B", "REQ-C")
    assert impact.direct_assumption_impacts(w.governor.state(), "ASM-1") == expected
    assert radius(impact, w) == expected


def test_an_assumption_with_no_affects_has_an_empty_radius(impact: ModuleType) -> None:
    w = world(requirement("REQ-A", authority=C, scope=(SCOPE,)), assumption("ASM-1"))
    state = w.governor.state()
    assert impact.direct_assumption_impacts(state, "ASM-1") == ()
    assert impact.assumption_blast_radius(state, "ASM-1") == ()
    assert impact.actionable_assumption_blast_radius(state, "ASM-1") == ()


def test_a_non_assumption_source_is_rejected(impact: ModuleType) -> None:
    w = world(requirement("REQ-A", authority=C, relations=affects("REQ-A")))
    with pytest.raises(impact.NotAnAssumptionError):
        impact.assumption_blast_radius(w.governor.state(), "REQ-A")


def test_a_missing_assumption_fails_rather_than_meaning_empty(impact: ModuleType) -> None:
    w = world(requirement("REQ-A", authority=C))
    with pytest.raises(impact.UnknownAssumptionError):
        impact.direct_assumption_impacts(w.governor.state(), "ASM-ghost")
    with pytest.raises(impact.UnknownAssumptionError):
        impact.actionable_assumption_blast_radius(w.governor.state(), "ASM-ghost")


def test_a_dangling_affects_target_is_ignored_safely(impact: ModuleType) -> None:
    w = world(requirement("REQ-A", authority=C), assumption("ASM-1", "REQ-A", "GHOST"))
    assert radius(impact, w) == ("REQ-A",)


# --- transitive reverse DERIVED_FROM ---------------------------------------------------------


def test_a_child_derived_from_an_impacted_object_is_impacted(impact: ModuleType) -> None:
    w = world(
        requirement("REQ-A", authority=C),
        requirement("REQ-B", authority=C, relations=derived("REQ-A")),
        assumption("ASM-1", "REQ-A"),
    )
    assert impact.direct_assumption_impacts(w.governor.state(), "ASM-1") == ("REQ-A",)
    assert radius(impact, w) == ("REQ-A", "REQ-B")


def test_a_long_chain_is_walked_to_the_end_without_recursion(impact: ModuleType) -> None:
    chain = [requirement("R0", authority=C)]
    for i in range(1, 3000):
        chain.append(requirement(f"R{i}", authority=C, relations=derived(f"R{i - 1}")))
    w = world(*chain, assumption("ASM-1", "R0"))
    assert radius(impact, w) == tuple(sorted(f"R{i}" for i in range(3000)))


def test_direction_is_parent_to_child_never_child_to_parent(impact: ModuleType) -> None:
    """The assumption affects the child; the parent the child rests on is not affected."""
    w = world(
        requirement("REQ-parent", authority=C),
        requirement("REQ-child", authority=C, relations=derived("REQ-parent")),
        assumption("ASM-1", "REQ-child"),
    )
    assert radius(impact, w) == ("REQ-child",)


def test_a_diamond_yields_each_id_once(impact: ModuleType) -> None:
    w = world(
        requirement("A", authority=C),
        requirement("B", authority=C, relations=derived("A")),
        requirement("C", authority=C, relations=derived("A")),
        requirement("D", authority=C, relations=derived("B", "C")),
        assumption("ASM-1", "A"),
    )
    assert radius(impact, w) == ("A", "B", "C", "D")


def test_a_historical_derived_from_cycle_terminates(impact: ModuleType) -> None:
    w = world(
        requirement("A", authority=C, relations=derived("B")),
        requirement("B", authority=C, relations=derived("A")),
        requirement("X", authority=C, relations=derived("B")),
        assumption("ASM-1", "A"),
    )
    assert radius(impact, w) == ("A", "B", "X")


def test_an_unrelated_branch_is_excluded(impact: ModuleType) -> None:
    w = world(
        requirement("A", authority=C),
        requirement("B", authority=C, relations=derived("A")),
        requirement("OTHER-root", authority=C),
        requirement("OTHER-child", authority=C, relations=derived("OTHER-root")),
        assumption("ASM-1", "A"),
    )
    assert radius(impact, w) == ("A", "B")


def test_derivation_edges_are_not_read(impact: ModuleType) -> None:
    """R65: only object-local DERIVED_FROM. A DerivationEdge with no relation is ignored."""
    w = world(
        requirement("A", authority=C),
        requirement("EDGE-ONLY", authority=C),
        assumption("ASM-1", "A"),
    )
    w.governor.derive("EDGE-ONLY", "A")
    assert any(e.child_id == "EDGE-ONLY" for e in w.governor.state().semantic.derivations)
    assert radius(impact, w) == ("A",)


# --- historical vs actionable ------------------------------------------------------------


@pytest.mark.parametrize(
    ("lifecycle", "authority"),
    [
        (LifecycleStatus.SUPERSEDED, C),
        (LifecycleStatus.ACTIVE, Authority.SUPERSEDED),
        (LifecycleStatus.ACTIVE, Authority.REJECTED),
    ],
    ids=["superseded-lifecycle", "superseded-authority", "rejected-authority"],
)
def test_a_dead_impacted_object_is_historical_but_not_actionable(
    impact: ModuleType, lifecycle: LifecycleStatus, authority: Authority
) -> None:
    w = world(
        requirement("REQ-live", authority=C),
        requirement("REQ-dead", authority=authority, lifecycle=lifecycle),
        assumption("ASM-1", "REQ-live", "REQ-dead"),
    )
    assert radius(impact, w) == ("REQ-dead", "REQ-live")
    assert actionable(impact, w) == ("REQ-live",)


def test_a_dead_intermediate_does_not_hide_a_live_descendant(impact: ModuleType) -> None:
    """R66: ASM -> A; B (superseded) DERIVED_FROM A; C (current) DERIVED_FROM B."""
    w = world(
        requirement("A", authority=C),
        requirement("B", authority=C, lifecycle=LifecycleStatus.SUPERSEDED, relations=derived("A")),
        requirement("C", authority=C, relations=derived("B")),
        assumption("ASM-1", "A"),
    )
    assert radius(impact, w) == ("A", "B", "C")
    assert actionable(impact, w) == ("A", "C")


def test_actionable_keeps_current_non_canonical_objects(impact: ModuleType) -> None:
    """Current means object_is_current: a PROPOSED object is live intended work."""
    w = world(requirement("REQ-p"), assumption("ASM-1", "REQ-p"))
    assert actionable(impact, w) == ("REQ-p",)


# --- what never propagates ----------------------------------------------------------------


@pytest.mark.parametrize(
    "relation",
    [
        RelationType.SERVES,
        RelationType.EXCLUDES,
        RelationType.CONSTRAINS,
        RelationType.VERIFIED_BY,
        RelationType.MEASURED_BY,
        RelationType.CONFLICTS_WITH,
        RelationType.SUPERSEDES,
    ],
    ids=lambda r: r.value,
)
def test_only_derived_from_propagates(impact: ModuleType, relation: RelationType) -> None:
    """R63/R64/R69: e.g. a Requirement that SERVES an affected Goal is not in the radius."""
    w = world(
        goal("GOAL-A", authority=C),
        requirement("REQ-other", authority=C, relations=(rel(relation, "GOAL-A"),)),
        assumption("ASM-1", "GOAL-A"),
    )
    assert radius(impact, w) == ("GOAL-A",)


def test_serves_control_explicitly(impact: ModuleType) -> None:
    w = world(
        goal("GOAL-A", authority=C),
        requirement("REQ-serving", authority=C, relations=(rel(RelationType.SERVES, "GOAL-A"),)),
        assumption("ASM-1", "GOAL-A"),
    )
    assert "GOAL-A" in radius(impact, w)
    assert "REQ-serving" not in radius(impact, w)


def test_a_non_goal_excluding_an_affected_object_is_not_impacted(impact: ModuleType) -> None:
    w = world(
        requirement("REQ-A", authority=C),
        non_goal("NG-1", authority=C, relations=(rel(RelationType.EXCLUDES, "REQ-A"),)),
        assumption("ASM-1", "REQ-A"),
    )
    assert radius(impact, w) == ("REQ-A",)


def test_no_scope_or_prose_inference(impact: ModuleType) -> None:
    """Same scope and identical statement text as the target: still not impacted."""
    text = "Refunds must complete within thirty calendar days."
    w = world(
        requirement("REQ-A", authority=C, statement=text),
        requirement("REQ-twin", authority=C, statement=text),
        constraint("CON-same-scope", authority=C),
        assumption("ASM-1", "REQ-A", statement=text),
    )
    assert radius(impact, w) == ("REQ-A",)


def test_impact_does_not_depend_on_delivery_scope(impact: ModuleType) -> None:
    w = world(
        requirement("REQ-A", authority=C, scope=("billing",)),
        requirement("REQ-B", authority=C, scope=("security",), relations=derived("REQ-A")),
        assumption("ASM-1", "REQ-A", scope=("payments",)),
    )
    assert radius(impact, w) == ("REQ-A", "REQ-B")


def test_impact_grants_no_authority(impact: ModuleType) -> None:
    """Being in a radius changes nothing about an object; an Assumption is never a basis."""
    w = world(requirement("REQ-p"), assumption("ASM-1", "REQ-p", authority=C))
    before = w.governor.state()
    impact.actionable_assumption_blast_radius(before, "ASM-1")
    assert w.governor.state().objects["REQ-p"].authority is Authority.PROPOSED


def test_objects_from_another_project_cannot_enter_the_radius(impact: ModuleType) -> None:
    """Defensive: a hand-built state holding a foreign object. The walk is project-local."""
    local = requirement("REQ-A", authority=C)
    foreign = requirement("REQ-foreign", authority=C, relations=derived("REQ-A"))
    foreign = foreign.model_copy(update={"project_id": "PROJ-OTHER"})
    asm = assumption("ASM-1", "REQ-A")
    state = IntentState(project_id=PROJECT, objects={o.id: o for o in (local, foreign, asm)})
    assert impact.assumption_blast_radius(state, "ASM-1") == ("REQ-A",)


# --- a projection, not a mutation -----------------------------------------------------------


def test_the_projection_mutates_nothing_and_replay_is_unchanged(impact: ModuleType) -> None:
    w = world(
        requirement("REQ-A", authority=C),
        requirement("REQ-B", authority=C, relations=derived("REQ-A")),
        assumption("ASM-1", "REQ-A", risk_level=RiskLevel.HIGH),
    )
    events_before = [s.event for s in w.store.load(PROJECT)]
    state = w.governor.state()
    dumped = state.model_dump(mode="json")
    closure_before = evaluate_closure(state, SCOPE)

    for _ in range(3):
        assert impact.assumption_blast_radius(state, "ASM-1") == ("REQ-A", "REQ-B")
        assert impact.actionable_assumption_blast_radius(state, "ASM-1") == ("REQ-A", "REQ-B")

    assert state.model_dump(mode="json") == dumped
    assert [s.event for s in w.store.load(PROJECT)] == events_before
    assert replay(PROJECT, w.store.load(PROJECT)) == state
    # The existing closure law is untouched: still exactly one high-risk assumption blocker.
    assert evaluate_closure(state, SCOPE) == closure_before
    assert [b.object_ids for b in closure_before.blockers if "ASSUMPTION" in b.code] == [("ASM-1",)]


def test_an_assumption_admitted_through_the_seam_projects_the_same_way(
    impact: ModuleType,
) -> None:
    w = World()
    w.governor.record_intent_object(requirement("REQ-p"), author=MODEL)
    w.governor.record_intent_object(assumption("ASM-seam", "REQ-p"), author=MODEL)
    assert impact.assumption_blast_radius(w.governor.state(), "ASM-seam") == ("REQ-p",)


def test_direct_impacts_are_sorted_regardless_of_declaration_order(impact: ModuleType) -> None:
    """Enough targets, declared in reverse, that an unsorted set could not pass by luck."""
    ids = [f"REQ-{i:02d}" for i in range(24)]
    w = world(*(requirement(i, authority=C) for i in ids), assumption("ASM-1", *reversed(ids)))
    assert impact.direct_assumption_impacts(w.governor.state(), "ASM-1") == tuple(ids)

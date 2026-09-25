"""IE2.2b — grounding at the IE2 seam and at readiness.

Two enforcement points, one law (spec §5a):

* the IE2 seam refuses a new ``CANONICAL`` object whose declared basis is unlawful, before
  anything is appended;
* history cannot be refused, so an unlawful basis already in state replays unchanged and
  current-state readiness reports the same law as a deterministic blocker.

Every claim here is asserted through real governance (``World``), because the law reads the
asserting judgment's liveness and the claim's authority. Non-canonical objects are never
constrained: a Requirement proposed before its basis is sound is ordinary incremental work.

These tests match on the blocker *code* rather than importing it, so the seam's refusals are
proven behaviourally and not merely by the absence of a module.
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
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    RelationType,
    RiskLevel,
)
from foundry.domain.handoff_v2 import scoped_basis_blockers
from foundry.domain.semantic import Assumption, ConstraintFacet, SemanticObject
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
    project_decision,
    rel,
    requirement,
)
from tests.unit._ie22b_fixtures import EVIDENCE_ID, World

C = Authority.CANONICAL


def derived(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.DERIVED_FROM, t) for t in targets)


def assumption(object_id: str = "ASM-1", **overrides: object) -> Assumption:
    return Assumption(
        id=object_id,
        project_id=PROJECT,
        authority=overrides.pop("authority", C),  # type: ignore[arg-type]
        confidence=1.0,
        provenance=SYSTEM_PROV,
        created_at=goal().created_at,
        scope=(SCOPE,),
        statement="Refund volume stays low.",
        risk_level=RiskLevel.LOW,
        **overrides,  # type: ignore[arg-type]
    )


def refused(world: World, obj: SemanticObject, code: str) -> None:
    before = world.event_count()
    with pytest.raises(ValueError, match=code):
        world.admit_canonical(obj)
    assert world.event_count() == before, "a refusal appends nothing"


def admitted(world: World, obj: SemanticObject) -> None:
    world.admit_canonical(obj)
    assert world.governor.state().objects[obj.id].authority is obj.authority


# --- the evidential terminal ----------------------------------------------------------------


def test_a_canonical_claim_is_a_lawful_terminal() -> None:
    world = World()
    claim = world.claim("J-c", authority=C)
    admitted(world, requirement("REQ-1", authority=C, relations=derived(claim)))


@pytest.mark.parametrize("weak", [Authority.INFERRED, Authority.OBSERVED, Authority.PROPOSED])
def test_a_non_canonical_claim_is_an_unlawful_basis(weak: Authority) -> None:
    """R42: CANONICAL only. OBSERVED is not trusted observation -- a model may assert it."""
    world = World()
    claim = world.claim("J-weak", authority=weak)
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived(claim)),
        "UNLAWFUL_BASIS_AUTHORITY",
    )


def test_a_claim_whose_judgment_was_superseded_is_a_dead_basis() -> None:
    world = World()
    claim = world.claim("J-old", authority=C)
    world.supersede("J-retire", "J-old")
    refused(world, requirement("REQ-1", authority=C, relations=derived(claim)), "DEAD_BASIS")


def test_evidence_is_not_a_direct_terminal() -> None:
    """DERIVED_FROM -> EvidenceItem is legal (IE2.1) but grounds nothing: a claim must say
    what the evidence means before intent may rest on it."""
    world = World()
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived(EVIDENCE_ID)),
        "UNGROUNDED_CANONICAL_OBJECT",
    )


def test_one_unlawful_basis_among_lawful_ones_still_refuses() -> None:
    """Every declared basis must be lawful; one good root does not excuse a bad one."""
    world = World()
    good = world.claim("J-good", authority=C)
    bad = world.claim("J-bad", authority=Authority.INFERRED, text="forty days")
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived(good, bad)),
        "UNLAWFUL_BASIS_AUTHORITY",
    )


# --- intermediates -------------------------------------------------------------------------


@pytest.mark.parametrize("build", [goal, outcome, requirement], ids=["goal", "outcome", "req"])
def test_a_canonical_intermediate_with_a_lawful_basis_carries_it(build) -> None:  # type: ignore[no-untyped-def]
    world = World()
    claim = world.claim("J-c", authority=C)
    admitted(world, build("MID", authority=C, relations=derived(claim)))
    admitted(world, requirement("REQ-top", authority=C, relations=derived("MID")))


def test_a_canonical_constraint_intermediate_carries_a_lawful_basis() -> None:
    world = World()
    claim = world.claim("J-c", authority=C)
    admitted(
        world,
        constraint(
            "CON-mid", authority=C, facet=ConstraintFacet.EVIDENCE_BOUND, relations=derived(claim)
        ),
    )
    admitted(world, requirement("REQ-top", authority=C, relations=derived("CON-mid")))


def test_a_proposed_intermediate_is_an_unlawful_basis() -> None:
    """R33 baseline: every node in a basis chain is canonical. A model-proposed Goal resting
    on a canonical claim is still only proposed."""
    world = World()
    claim = world.claim("J-c", authority=C)
    world.governor.record_intent_object(goal("GOAL-p", relations=derived(claim)), author=MODEL)
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("GOAL-p")),
        "UNLAWFUL_BASIS_AUTHORITY",
    )


def test_a_canonical_intermediate_with_no_further_basis_grounds_nothing() -> None:
    """I-BASIS-2: a chain must reach a claim or a Decision. A Goal is never a terminal."""
    world = World()
    admitted(world, goal("GOAL-bare", authority=C))
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("GOAL-bare")),
        "UNGROUNDED_CANONICAL_OBJECT",
    )


def test_a_chain_is_walked_to_its_terminal_not_just_one_level() -> None:
    world = World()
    weak = world.claim("J-weak", authority=Authority.INFERRED)
    # Recorded as history: the seam would now refuse the Goal itself.
    world.legacy(goal("GOAL-deep", authority=C, relations=derived(weak)))
    world.legacy(outcome("OUT-mid", authority=C, relations=derived("GOAL-deep")))
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("OUT-mid")),
        "UNLAWFUL_BASIS_AUTHORITY",
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
def test_a_non_current_intermediate_is_a_dead_basis(
    lifecycle: LifecycleStatus, authority: Authority
) -> None:
    world = World()
    claim = world.claim("J-c", authority=C)
    world.legacy(
        goal("GOAL-dead", authority=authority, lifecycle=lifecycle, relations=derived(claim))
    )
    refused(world, requirement("REQ-1", authority=C, relations=derived("GOAL-dead")), "DEAD_BASIS")


def test_an_assumption_anywhere_in_the_chain_is_refused() -> None:
    """I-BASIS-3. Only history can hold this shape: IE2.1 forbids DERIVED_FROM -> ASSUMPTION."""
    world = World()
    claim = world.claim("J-c", authority=C)
    world.legacy(
        assumption("ASM-1"),
        goal("GOAL-a", authority=C, relations=derived(claim, "ASM-1")),
    )
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("GOAL-a")),
        "ASSUMPTION_IN_BASIS",
    )


def test_a_non_goal_is_never_a_basis() -> None:
    world = World()
    world.legacy(
        non_goal("NG-1", authority=C),
        goal("GOAL-ng", authority=C, relations=derived("NG-1")),
    )
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("GOAL-ng")),
        "UNGROUNDED_CANONICAL_OBJECT",
    )


def test_a_dangling_historical_basis_grounds_nothing() -> None:
    world = World()
    world.legacy(goal("GOAL-dangle", authority=C, relations=derived("GHOST")))
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("GOAL-dangle")),
        "UNGROUNDED_CANONICAL_OBJECT",
    )


def test_a_historical_basis_cycle_is_refused_and_the_walk_terminates() -> None:
    world = World()
    world.legacy(
        goal("GOAL-a", authority=C, relations=derived("GOAL-b")),
        goal("GOAL-b", authority=C, relations=derived("GOAL-a")),
    )
    refused(world, requirement("REQ-1", authority=C, relations=derived("GOAL-a")), "BASIS_CYCLE")


def test_a_diamond_is_walked_once_and_is_lawful() -> None:
    world = World()
    claim = world.claim("J-c", authority=C)
    admitted(world, goal("GOAL-root", authority=C, relations=derived(claim)))
    admitted(world, goal("GOAL-l", authority=C, relations=derived("GOAL-root")))
    admitted(world, goal("GOAL-r", authority=C, relations=derived("GOAL-root")))
    admitted(world, requirement("REQ-1", authority=C, relations=derived("GOAL-l", "GOAL-r")))


# --- the authoritative terminal -------------------------------------------------------------


def test_a_canonical_decision_is_a_lawful_terminal() -> None:
    world = World()
    admitted(world, project_decision("DEC-1", authority=C))
    admitted(world, requirement("REQ-1", authority=C, relations=derived("DEC-1")))


def test_a_decisions_declared_rationale_must_itself_be_lawful() -> None:
    world = World()
    weak = world.claim("J-weak", authority=Authority.INFERRED)
    world.legacy(project_decision("DEC-1", authority=C, relations=derived(weak)))
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("DEC-1")),
        "UNLAWFUL_BASIS_AUTHORITY",
    )


def test_a_decision_with_an_unlawful_rationale_is_refused_at_its_own_admission() -> None:
    world = World()
    weak = world.claim("J-weak", authority=Authority.INFERRED)
    refused(
        world,
        project_decision("DEC-1", authority=C, relations=derived(weak)),
        "UNLAWFUL_BASIS_AUTHORITY",
    )


def test_a_proposed_decision_is_not_a_terminal() -> None:
    world = World()
    world.governor.record_intent_object(project_decision("DEC-p"), author=MODEL)
    refused(
        world,
        requirement("REQ-1", authority=C, relations=derived("DEC-p")),
        "UNLAWFUL_BASIS_AUTHORITY",
    )


# --- kinds whose grounding is required, optional, or absent (§4) ----------------------------


def test_a_directly_authorized_requirement_needs_no_basis() -> None:
    """R37: absence of DERIVED_FROM is lawful; only a *declared* basis must be valid."""
    world = World()
    admitted(world, requirement("REQ-1", authority=C))


@pytest.mark.parametrize(
    "facet", [ConstraintFacet.EVIDENCE_BOUND, ConstraintFacet.EXTERNAL_MANDATE]
)
def test_an_evidence_requiring_constraint_without_basis_is_ungrounded(
    facet: ConstraintFacet,
) -> None:
    world = World()
    refused(
        world,
        constraint("CON-1", authority=C, facet=facet, provenance=SYSTEM_PROV),
        "UNGROUNDED_CANONICAL_OBJECT",
    )


@pytest.mark.parametrize(
    "facet", [ConstraintFacet.EVIDENCE_BOUND, ConstraintFacet.EXTERNAL_MANDATE]
)
def test_an_evidence_requiring_constraint_on_a_lawful_claim_is_admitted(
    facet: ConstraintFacet,
) -> None:
    world = World()
    claim = world.claim("J-c", authority=C)
    admitted(
        world,
        constraint(
            "CON-1", authority=C, facet=facet, provenance=SYSTEM_PROV, relations=derived(claim)
        ),
    )


def test_an_evidence_requiring_constraint_on_a_decision_alone_is_ungrounded() -> None:
    """§11: EVIDENCE_BOUND / EXTERNAL_MANDATE need an *evidential* basis. A project choice is
    not evidence that the boundary is externally imposed or evidence-bound."""
    world = World()
    admitted(world, project_decision("DEC-1", authority=C))
    refused(
        world,
        constraint(
            "CON-1",
            authority=C,
            facet=ConstraintFacet.EVIDENCE_BOUND,
            relations=derived("DEC-1"),
        ),
        "UNGROUNDED_CANONICAL_OBJECT",
    )


def test_a_project_boundary_needs_no_basis() -> None:
    world = World()
    admitted(world, constraint("CON-1", authority=C, facet=ConstraintFacet.PROJECT_BOUNDARY))


def test_non_canonical_objects_are_never_constrained() -> None:
    """A Requirement proposed before its basis is sound is ordinary incremental work."""
    world = World()
    weak = world.claim("J-weak", authority=Authority.INFERRED)
    world.governor.record_intent_object(requirement("REQ-p", relations=derived(weak)), author=MODEL)
    assert world.governor.state().objects["REQ-p"].authority is Authority.PROPOSED


# --- readiness: history replays, the same law blocks delivery (R52-R56) ---------------------
#
# Closure and the package are the canonical contract; v2 readiness decides whether that
# contract is safe to hand downstream now. A basis defect lives only in the latter (P4).


def _deliverable_scope(world: World) -> None:
    world.admit_canonical(intent("INTENT-payments", authority=C))


def basis_codes(world: World) -> dict[str, tuple[str, ...]]:
    codes: dict[str, tuple[str, ...]] = {}
    for blocker in scoped_basis_blockers(world.governor.state(), SCOPE):
        codes[blocker.code] = codes.get(blocker.code, ()) + blocker.object_ids
    return codes


def test_a_lawful_canonical_basis_leaves_delivery_unblocked() -> None:
    world = World()
    _deliverable_scope(world)
    claim = world.claim("J-c", authority=C)
    world.admit_canonical(requirement("REQ-1", authority=C, relations=derived(claim)))
    handoff = build_intent_decision_handoff_v2(world.governor.state(), SCOPE)
    assert handoff.readiness.deliverable is True
    assert handoff.readiness.basis_blockers == ()


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        ("inferred-claim", "UNLAWFUL_BASIS_AUTHORITY"),
        ("dead-claim", "DEAD_BASIS"),
        ("evidence", "UNGROUNDED_CANONICAL_OBJECT"),
        ("assumption", "ASSUMPTION_IN_BASIS"),
        ("cycle", "BASIS_CYCLE"),
        ("bare-evidence-bound", "UNGROUNDED_CANONICAL_OBJECT"),
    ],
)
def test_historical_unlawful_bases_replay_close_and_block_only_delivery(
    setup: str, code: str
) -> None:
    world = World()
    _deliverable_scope(world)
    obj: SemanticObject
    if setup == "inferred-claim":
        weak = world.claim("J-w", authority=Authority.INFERRED)
        obj = requirement("REQ-h", authority=C, relations=derived(weak))
    elif setup == "dead-claim":
        claim = world.claim("J-old", authority=C)
        world.supersede("J-retire", "J-old")
        obj = requirement("REQ-h", authority=C, relations=derived(claim))
    elif setup == "evidence":
        obj = requirement("REQ-h", authority=C, relations=derived(EVIDENCE_ID))
    elif setup == "assumption":
        world.legacy(assumption("ASM-1"))
        obj = requirement("REQ-h", authority=C, relations=derived("ASM-1"))
    elif setup == "cycle":
        world.legacy(goal("GOAL-a", authority=C, relations=derived("REQ-h")))
        obj = requirement("REQ-h", authority=C, relations=derived("GOAL-a"))
    else:
        obj = constraint(
            "CON-h", authority=C, facet=ConstraintFacet.EVIDENCE_BOUND, provenance=SYSTEM_PROV
        )
    world.legacy(obj)

    # History replays unchanged: the object stays exactly as recorded, canonical included.
    state = replay(PROJECT, world.store.load(PROJECT))
    assert state == world.governor.state()
    assert state.objects[obj.id] == obj

    # The contract is untouched: closure closes and the package builds (P4, R52).
    assert evaluate_closure(state, SCOPE).closed is True
    assert obj.id in build_intent_package(state, SCOPE).obligation_ids

    # Only delivery refuses, naming the specific category.
    codes = basis_codes(world)
    assert code in codes, codes
    assert obj.id in codes[code]
    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(state, SCOPE)
    assert code in excinfo.value.blocker_codes


def test_every_applicable_basis_category_is_exposed_in_order() -> None:
    """R54: categories are never collapsed into one generic code."""
    world = World()
    _deliverable_scope(world)
    weak = world.claim("J-w", authority=Authority.INFERRED)
    world.legacy(
        assumption("ASM-1"),
        requirement("REQ-a", authority=C, relations=derived(weak)),
        requirement("REQ-b", authority=C, relations=derived("ASM-1")),
        requirement("REQ-c", authority=C, relations=derived(EVIDENCE_ID)),
    )
    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(world.governor.state(), SCOPE)
    assert excinfo.value.blocker_codes == (
        "UNGROUNDED_CANONICAL_OBJECT",
        "UNLAWFUL_BASIS_AUTHORITY",
        "ASSUMPTION_IN_BASIS",
    )


def test_delivery_ignores_non_current_objects_with_bad_bases() -> None:
    """A superseded object is history, not intended state; it cannot block delivery."""
    world = World()
    _deliverable_scope(world)
    weak = world.claim("J-w", authority=Authority.INFERRED)
    world.admit_canonical(requirement("REQ-ok", authority=C))
    world.legacy(
        requirement(
            "REQ-old",
            authority=Authority.SUPERSEDED,
            lifecycle=LifecycleStatus.SUPERSEDED,
            relations=derived(weak),
        )
    )
    assert basis_codes(world) == {}
    assert build_intent_decision_handoff_v2(world.governor.state(), SCOPE).readiness.deliverable


def test_delivery_ignores_non_canonical_objects_with_bad_bases() -> None:
    world = World()
    _deliverable_scope(world)
    weak = world.claim("J-w", authority=Authority.INFERRED)
    world.admit_canonical(requirement("REQ-ok", authority=C))
    world.governor.record_intent_object(requirement("REQ-p", relations=derived(weak)), author=MODEL)
    assert basis_codes(world) == {}


def test_delivery_ignores_objects_outside_the_evaluated_scope() -> None:
    world = World()
    _deliverable_scope(world)
    world.admit_canonical(requirement("REQ-ok", authority=C))
    world.legacy(
        requirement("REQ-elsewhere", authority=C, scope=("billing",), relations=derived("GHOST"))
    )
    assert basis_codes(world) == {}
    # ...while the scope it does apply to sees it.
    assert {b.code for b in scoped_basis_blockers(world.governor.state(), "billing")} == {
        "UNGROUNDED_CANONICAL_OBJECT"
    }

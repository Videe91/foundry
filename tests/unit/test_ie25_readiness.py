"""IE2.5 — completeness/readiness integration (R86-R98).

v2 readiness now answers, by composing laws that already exist:

* can this scope be delivered, and exactly why not   (unchanged gate)
* which open in-scope gaps remain, and how they may be closed   (IE2.4 plans, R87-R89)
* what current intended state an unsupported assumption exposes   (IE2.3 via the plan, R90)
* which canonical Decisions currently have no consequence   (I-DEC-1, report-only, R91-R93)
* which Preferences are present and deliberately non-blocking   (R94)

Nothing here is a new blocker. Closure and the package are untouched (R86), exclusions stay a
closure law (R95), and one gap-scope law serves both closure and readiness (R88).

New modules are imported lazily per test so each case fails on its own before they exist.
"""

from __future__ import annotations

import importlib
from itertools import count

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
    Materiality,
    RelationType,
    RiskLevel,
)
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    GapPayload,
    GapResolvedPayload,
    GapWaivedPayload,
)
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.handoff import build_semantic_readiness, locus_in_scope
from foundry.domain.handoff_v2 import IntentDeliveryReadiness, build_intent_delivery_readiness
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import Assumption, SemanticObject
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from tests.unit._ie21_fixtures import (
    ALICE,
    AT,
    MODEL,
    PROJECT,
    SCOPE,
    SYSTEM_PROV,
    non_goal,
    preference,
    project_decision,
    rel,
    requirement,
)
from tests.unit._ie22b_fixtures import ROOT_ID, World

C = Authority.CANONICAL
_IDS = count(1)


def serves(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.SERVES, t) for t in targets)


def derived(*targets: str) -> tuple:  # type: ignore[type-arg]
    return tuple(rel(RelationType.DERIVED_FROM, t) for t in targets)


def deliverable_world() -> World:
    """A deliverable scope: one root, one rooted canonical obligation."""
    w = World()
    w.admit_root()
    w.admit_canonical(requirement("REQ-ok", authority=C, relations=serves(ROOT_ID)))
    return w


def readiness(state: IntentState, scope: str = SCOPE) -> IntentDeliveryReadiness:
    view = derive_view(state.semantic)
    loci = tuple(locus for locus in view.loci if locus_in_scope(locus, scope))
    return build_intent_delivery_readiness(
        state, view, scope, loci, build_semantic_readiness(state, view, scope, loci)
    )


def gap(
    gap_id: str,
    kind: GapKind,
    *affected: str,
    blocking: bool = False,
    synthesis_scope: tuple[str, ...] | None = None,
) -> Gap:
    fields: dict[str, object] = {
        "id": gap_id,
        "project_id": PROJECT,
        "kind": kind,
        "description": f"{kind.value}.",
        "affected_object_ids": affected,
        "blocking": blocking,
    }
    if synthesis_scope is not None:
        return IntentSynthesisGap(**fields, scope=synthesis_scope)  # type: ignore[arg-type]
    return Gap(**fields, materiality=Materiality.MEDIUM, risk=RiskLevel.MEDIUM)  # type: ignore[arg-type]


def _append(w: World, event_type: EventType, payload: object) -> None:
    w.store.append(
        EventEnvelope(
            event_id=f"EVT-ie25-{next(_IDS)}",
            project_id=PROJECT,
            event_type=event_type,
            occurred_at=AT,
            payload=payload,  # type: ignore[arg-type]
        ),
        expected_sequence=w.store.current_sequence(PROJECT),
    )


def record(w: World, *gaps: Gap) -> None:
    for g in gaps:
        _append(w, EventType.GAP_RECORDED, GapPayload(gap=g))


def assumption(object_id: str, *targets: str) -> Assumption:
    return Assumption(
        id=object_id,
        project_id=PROJECT,
        authority=Authority.PROPOSED,
        confidence=0.6,
        provenance=SYSTEM_PROV,
        created_at=AT,
        scope=(SCOPE,),
        statement="Refund volume stays low.",
        risk_level=RiskLevel.MEDIUM,
        relations=tuple(rel(RelationType.AFFECTS, t) for t in targets),
    )


def refusal(state: IntentState) -> tuple[str, ...]:
    try:
        build_intent_decision_handoff_v2(state, SCOPE)
    except IntentDeliveryNotReadyError as error:
        return error.blocker_codes
    return ()


# --- R88: one gap-scope law, extracted without behaviour change ------------------------------


def _reference_gap_applies(gap: Gap, state: IntentState, scope: str) -> bool:
    """closure._gap_applies as it stood at c6b3437, copied verbatim for the regression."""
    if isinstance(gap, IntentSynthesisGap) and gap.scope != () and scope not in gap.scope:
        return False
    if gap.affected_object_ids == ():
        return True
    for object_id in gap.affected_object_ids:
        obj = state.objects.get(object_id)
        if obj is None:
            return True
        if obj.scope == () or scope in obj.scope:
            return True
    return False


GAP_SCOPE_MATRIX = [
    ("synthesis-named-in", gap("G", GapKind.AMBIGUITY, synthesis_scope=(SCOPE,)), True),
    ("synthesis-named-out", gap("G", GapKind.AMBIGUITY, synthesis_scope=("billing",)), False),
    ("synthesis-project-wide", gap("G", GapKind.AMBIGUITY, synthesis_scope=()), True),
    ("legacy-applicable-object", gap("G", GapKind.AMBIGUITY, "REQ-in"), True),
    ("legacy-non-applicable-object", gap("G", GapKind.AMBIGUITY, "REQ-billing"), False),
    ("legacy-unknown-object", gap("G", GapKind.AMBIGUITY, "GHOST"), True),
    ("no-affected-ids", gap("G", GapKind.AMBIGUITY), True),
    (
        "synthesis-named-out-unknown-object",
        gap("G", GapKind.AMBIGUITY, "GHOST", synthesis_scope=("billing",)),
        False,
    ),
]


def _scope_world() -> World:
    w = deliverable_world()
    w.legacy(
        requirement("REQ-in", scope=(SCOPE,)),
        requirement("REQ-billing", scope=("billing",)),
    )
    return w


@pytest.mark.parametrize(
    ("label", "the_gap", "expected"), GAP_SCOPE_MATRIX, ids=[m[0] for m in GAP_SCOPE_MATRIX]
)
def test_gap_applies_is_the_old_closure_law_exactly(
    label: str, the_gap: Gap, expected: bool
) -> None:
    gap_scope = importlib.import_module("foundry.domain.gap_scope")
    state = _scope_world().governor.state()
    assert _reference_gap_applies(the_gap, state, SCOPE) is expected
    assert gap_scope.gap_applies(state, the_gap, SCOPE) is expected


@pytest.mark.parametrize(
    ("label", "the_gap", "expected"), GAP_SCOPE_MATRIX, ids=[m[0] for m in GAP_SCOPE_MATRIX]
)
def test_closure_output_is_unchanged_by_the_extraction(
    label: str, the_gap: Gap, expected: bool
) -> None:
    w = _scope_world()
    record(w, the_gap.model_copy(update={"blocking": True}))
    closure = evaluate_closure(w.governor.state(), SCOPE)
    assert ("OPEN_BLOCKING_GAP" in {b.code for b in closure.blockers}) is expected
    assert closure.closed is (not expected)


def test_closure_uses_the_shared_gap_scope_helper() -> None:
    gap_scope = importlib.import_module("foundry.domain.gap_scope")
    closure_module = importlib.import_module("foundry.domain.closure")
    assert closure_module.gap_applies is gap_scope.gap_applies


# --- R87/R89: open in-scope gaps expose lawful resolution plans ------------------------------


def test_readiness_exposes_plans_for_open_in_scope_gaps_blocking_or_not() -> None:
    w = deliverable_world()
    record(
        w,
        gap("GAP-block", GapKind.STALE_EVIDENCE, blocking=True),
        gap("GAP-soft", GapKind.MISSING_INFORMATION),
        gap("GAP-out", GapKind.AMBIGUITY, synthesis_scope=("billing",)),
        gap("GAP-resolved", GapKind.MISSING_AUTHORITY),
        gap("GAP-waived", GapKind.CONTRADICTION),
    )
    _append(w, EventType.GAP_RESOLVED, GapResolvedPayload(gap_id="GAP-resolved"))
    _append(
        w,
        EventType.GAP_WAIVED,
        GapWaivedPayload(gap_id="GAP-waived", reason="accepted", authorized_by=ALICE),
    )
    plans = readiness(w.governor.state()).gap_resolution_plans
    assert [p.gap_id for p in plans] == ["GAP-block", "GAP-soft"]
    assert plans[0].deterministic_route is not None
    assert plans[0].deterministic_route.value == "RESEARCH"
    assert plans[1].deterministic_route is None


def test_the_scoped_helper_reuses_the_ie24_planner() -> None:
    completeness = importlib.import_module("foundry.domain.completeness")
    gr = importlib.import_module("foundry.domain.gap_resolution")
    w = deliverable_world()
    record(w, gap("GAP-b", GapKind.AMBIGUITY), gap("GAP-a", GapKind.CONTEXT_FAILURE))
    state = w.governor.state()
    plans = completeness.scoped_open_gap_resolution_plans(state, SCOPE)
    assert plans == tuple(gr.gap_resolution_plan(state, i) for i in ("GAP-a", "GAP-b"))


def test_a_blocking_stale_evidence_gap_routes_to_research_and_still_blocks() -> None:
    w = deliverable_world()
    record(w, gap("GAP-stale", GapKind.STALE_EVIDENCE, blocking=True))
    r = readiness(w.governor.state())
    (plan,) = r.gap_resolution_plans
    assert plan.deterministic_route is not None and plan.deterministic_route.value == "RESEARCH"
    assert r.deliverable is False
    assert refusal(w.governor.state()) == ("CLOSURE_NOT_MET",)


def test_preserve_wait_being_lawful_does_not_unblock_delivery() -> None:
    w = deliverable_world()
    record(w, gap("GAP-wait", GapKind.INSUFFICIENT_EVIDENCE, blocking=True))
    r = readiness(w.governor.state())
    (plan,) = r.gap_resolution_plans
    assert "PRESERVE_WAIT" in {route.value for route in plan.candidate_routes}
    assert r.deliverable is False
    assert w.governor.state().gaps["GAP-wait"].status is GapStatus.OPEN


def test_a_non_blocking_open_gap_is_visible_but_does_not_block() -> None:
    w = deliverable_world()
    record(w, gap("GAP-soft", GapKind.AMBIGUITY))
    r = readiness(w.governor.state())
    assert [p.gap_id for p in r.gap_resolution_plans] == ["GAP-soft"]
    assert r.deliverable is True
    assert w.governor.state().gaps["GAP-soft"].status is GapStatus.OPEN


# --- R90: unsupported-assumption impact arrives through the plan -----------------------------


def test_unsupported_assumption_impact_is_visible_through_readiness() -> None:
    w = deliverable_world()
    w.legacy(
        requirement("REQ-A", relations=serves(ROOT_ID)),
        requirement("REQ-B", relations=derived("REQ-A") + serves(ROOT_ID)),
        assumption("ASM-1", "REQ-A"),
    )
    record(w, gap("GAP-asm", GapKind.UNSUPPORTED_ASSUMPTION, "ASM-1"))
    (plan,) = readiness(w.governor.state()).gap_resolution_plans
    assert plan.assumption_impact_ids == ("REQ-A", "REQ-B")


# --- R91-R93: inert canonical Decisions, report-only ---------------------------------------


def _decision_world(*extra: SemanticObject) -> World:
    w = deliverable_world()
    w.legacy(project_decision("DEC-1", authority=C, relations=serves(ROOT_ID)), *extra)
    return w


def inert(w: World, scope: str = SCOPE) -> tuple[str, ...]:
    return readiness(w.governor.state(), scope).inert_decision_ids


def test_a_canonical_decision_with_no_consequence_is_inert_and_not_a_blocker() -> None:
    w = _decision_world()
    r = readiness(w.governor.state())
    assert r.inert_decision_ids == ("DEC-1",)
    assert r.deliverable is True


@pytest.mark.parametrize(
    "consequence_authority", [Authority.PROPOSED, C], ids=["proposed", "canonical"]
)
def test_a_current_consequence_makes_a_decision_not_inert(
    consequence_authority: Authority,
) -> None:
    w = _decision_world(
        requirement(
            "REQ-because",
            authority=consequence_authority,
            relations=derived("DEC-1") + serves(ROOT_ID),
        )
    )
    assert inert(w) == ()


@pytest.mark.parametrize(
    ("lifecycle", "authority"),
    [(LifecycleStatus.ACTIVE, Authority.REJECTED), (LifecycleStatus.SUPERSEDED, C)],
    ids=["rejected", "superseded"],
)
def test_a_dead_consequence_does_not_count(
    lifecycle: LifecycleStatus, authority: Authority
) -> None:
    w = _decision_world(
        requirement(
            "REQ-dead", authority=authority, lifecycle=lifecycle, relations=derived("DEC-1")
        )
    )
    assert inert(w) == ("DEC-1",)


def test_an_out_of_scope_consequence_does_not_count_for_this_scope() -> None:
    w = World()
    w.admit_root(scope=())
    w.admit_canonical(requirement("REQ-ok", authority=C, relations=serves(ROOT_ID)))
    w.legacy(
        project_decision("DEC-g", authority=C, scope=(), relations=serves(ROOT_ID)),
        requirement("REQ-billing", scope=("billing",), relations=derived("DEC-g")),
    )
    assert inert(w, SCOPE) == ("DEC-g",)
    assert inert(w, "billing") == ()


def test_non_canonical_or_dead_decisions_are_never_reported() -> None:
    w = deliverable_world()
    w.legacy(
        project_decision("DEC-proposed"),
        project_decision("DEC-rejected", authority=Authority.REJECTED),
        project_decision("DEC-old", authority=C, lifecycle=LifecycleStatus.SUPERSEDED),
    )
    assert inert(w) == ()


def test_a_decisions_own_basis_or_relevance_edges_are_not_consequence() -> None:
    """Direction: the consequence object names the Decision as DERIVED_FROM target."""
    claim_world = _decision_world()
    claim = claim_world.claim("J-c", authority=C)
    claim_world.legacy(
        project_decision(
            "DEC-2", authority=C, relations=derived(claim) + serves(ROOT_ID, "REQ-ok")
        ),
        requirement("REQ-cited", authority=C, relations=serves(ROOT_ID)),
        project_decision("DEC-3", authority=C, relations=derived("REQ-cited") + serves(ROOT_ID)),
    )
    assert inert(claim_world) == ("DEC-1", "DEC-2", "DEC-3")


def test_the_inert_helper_is_the_readiness_source() -> None:
    completeness = importlib.import_module("foundry.domain.completeness")
    w = _decision_world()
    state = w.governor.state()
    assert completeness.scoped_inert_decision_ids(state, SCOPE) == ("DEC-1",)


# --- R94: Preferences are visible and never blocking ---------------------------------------


def test_current_applicable_preferences_are_reported_whatever_their_authority() -> None:
    w = deliverable_world()
    w.legacy(
        preference("PREF-proposed"),
        preference("PREF-canonical", authority=C, relations=serves(ROOT_ID)),
        preference("PREF-rejected", authority=Authority.REJECTED),
        preference("PREF-old", lifecycle=LifecycleStatus.SUPERSEDED),
        preference("PREF-billing", scope=("billing",)),
    )
    state = w.governor.state()
    r = readiness(state)
    assert r.preference_ids == ("PREF-canonical", "PREF-proposed")
    # Agrees with the package's own reading of preferences, and never becomes an obligation.
    package = build_intent_package(state, SCOPE)
    assert r.preference_ids == package.preference_ids
    assert not set(r.preference_ids) & set(package.obligation_ids)


def test_a_preference_never_changes_the_gate() -> None:
    without = deliverable_world()
    with_pref = deliverable_world()
    with_pref.legacy(preference("PREF-1"))
    a, b = readiness(without.governor.state()), readiness(with_pref.governor.state())
    assert a.deliverable is b.deliverable is True
    assert b.preference_ids == ("PREF-1",)
    assert refusal(with_pref.governor.state()) == ()


# --- R95/R96: exclusions stay in closure; the gate is unchanged ----------------------------


def test_an_exclusion_still_blocks_through_closure_not_a_new_v2_blocker() -> None:
    w = deliverable_world()
    w.legacy(
        non_goal(
            "NG-1", authority=C, relations=(rel(RelationType.EXCLUDES, "REQ-ok"),) + serves(ROOT_ID)
        )
    )
    state = w.governor.state()
    r = readiness(state)
    assert "EXCLUDED_BY_NON_GOAL" in {b.code for b in r.semantic_readiness.closure.blockers}
    assert refusal(state) == ("CLOSURE_NOT_MET",)
    assert not any("EXCLU" in b.code for b in r.basis_blockers + r.relevance_blockers)


def test_the_new_fields_are_diagnostics_only() -> None:
    w = deliverable_world()
    w.legacy(project_decision("DEC-1", authority=C, relations=serves(ROOT_ID)), preference("P"))
    record(w, gap("GAP-soft", GapKind.AMBIGUITY))
    r = readiness(w.governor.state())
    assert r.inert_decision_ids and r.preference_ids and r.gap_resolution_plans
    assert r.deliverable is True


# --- a projection only -----------------------------------------------------------------------


def test_readiness_projection_mutates_nothing() -> None:
    w = deliverable_world()
    w.legacy(assumption("ASM-1", "REQ-ok"), project_decision("DEC-1", authority=C))
    record(w, gap("GAP-asm", GapKind.UNSUPPORTED_ASSUMPTION, "ASM-1", blocking=True))
    state = w.governor.state()
    dumped = state.model_dump(mode="json")
    events = [s.event for s in w.store.load(PROJECT)]
    first = readiness(state)
    assert readiness(state) == first
    assert state.model_dump(mode="json") == dumped
    assert [s.event for s in w.store.load(PROJECT)] == events
    assert dict(state.jobs) == {}
    assert replay(PROJECT, w.store.load(PROJECT)) == state


def test_a_model_proposed_consequence_through_the_seam_counts() -> None:
    w = _decision_world()
    w.governor.record_intent_object(
        requirement("REQ-seam", relations=derived("DEC-1")), author=MODEL
    )
    assert inert(w) == ()

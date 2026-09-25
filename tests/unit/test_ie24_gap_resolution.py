"""IE2.4 — gap resolution routing (R70-R82).

``GapKind`` says *what* is wrong; ``GapResolutionRoute`` says *how* closure may proceed. The
route is a separate projection: no field is added to ``Gap`` or ``IntentSynthesisGap``, no
event is appended, no job is created, and nothing is executed.

A plan carries the **lawful candidate routes** for an open gap. A ``deterministic_route`` is
filled only when exactly one route is lawful; a multi-route plan never has one chosen for it.

Gaps are recorded through real ``GAP_RECORDED`` / ``GAP_RESOLVED`` / ``GAP_WAIVED`` events so
the projection is exercised against replayed state. The module is imported lazily per test so
that, before it exists, every case fails on its own.
"""

from __future__ import annotations

import importlib
from itertools import count
from types import ModuleType

import pytest

from foundry.application.replay import replay
from foundry.domain.closure import evaluate_closure
from foundry.domain.common import Authority, LifecycleStatus, Materiality, RelationType, RiskLevel
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    GapPayload,
    GapResolvedPayload,
    GapWaivedPayload,
)
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import Assumption
from tests.unit._ie21_fixtures import ALICE, AT, PROJECT, SCOPE, SYSTEM_PROV, rel, requirement
from tests.unit._ie22b_fixtures import World

MODULE = "foundry.domain.gap_resolution"
C = Authority.CANONICAL
_IDS = count(1)

MATRIX = {
    GapKind.MISSING_INFORMATION: ("DERIVE", "RESEARCH", "ASK_HUMAN", "PRESERVE_WAIT"),
    GapKind.AMBIGUITY: ("DERIVE", "ASK_HUMAN", "PRESERVE_WAIT"),
    GapKind.CONTRADICTION: ("RESEARCH", "ASK_HUMAN", "RECONCILE"),
    GapKind.UNSUPPORTED_ASSUMPTION: ("RESEARCH", "ASK_HUMAN", "PRESERVE_WAIT"),
    GapKind.MISSING_AUTHORITY: ("ASK_HUMAN",),
    GapKind.MISSING_SUCCESS_METRIC: ("DERIVE", "ASK_HUMAN"),
    GapKind.MISSING_VERIFICATION_OBLIGATION: ("DERIVE", "ASK_HUMAN"),
    GapKind.UNRESOLVED_RISK: ("RESEARCH", "ASK_HUMAN", "PRESERVE_WAIT"),
    GapKind.STALE_EVIDENCE: ("RESEARCH",),
    GapKind.INSUFFICIENT_EVIDENCE: ("RESEARCH", "PRESERVE_WAIT"),
    GapKind.UNDERSPECIFIED_SCOPE: ("ASK_HUMAN",),
    GapKind.UNRESOLVED_DEPENDENCY: (
        "DERIVE",
        "RESEARCH",
        "ASK_HUMAN",
        "RECONCILE",
        "PRESERVE_WAIT",
    ),
    GapKind.WORKER_DIVERGENCE: ("RECONCILE",),
    GapKind.CONTEXT_FAILURE: ("DERIVE",),
}
"""R72, restated independently of the implementation so a changed table is caught."""


@pytest.fixture
def gr() -> ModuleType:
    return importlib.import_module(MODULE)


def gap(
    gap_id: str,
    kind: GapKind,
    *affected: str,
    blocking: bool = False,
    synthesis: bool = False,
) -> Gap:
    fields: dict[str, object] = {
        "id": gap_id,
        "project_id": PROJECT,
        "kind": kind,
        "description": f"{kind.value} for the refund window.",
        "affected_object_ids": affected,
        "blocking": blocking,
    }
    if synthesis:
        return IntentSynthesisGap(**fields, scope=(SCOPE,))  # type: ignore[arg-type]
    return Gap(**fields, materiality=Materiality.MEDIUM, risk=RiskLevel.MEDIUM)  # type: ignore[arg-type]


def record(w: World, *gaps: Gap) -> None:
    for g in gaps:
        _append(w, EventType.GAP_RECORDED, GapPayload(gap=g))


def resolve(w: World, gap_id: str) -> None:
    _append(w, EventType.GAP_RESOLVED, GapResolvedPayload(gap_id=gap_id))


def waive(w: World, gap_id: str) -> None:
    _append(
        w,
        EventType.GAP_WAIVED,
        GapWaivedPayload(gap_id=gap_id, reason="accepted for v1", authorized_by=ALICE),
    )


def _append(w: World, event_type: EventType, payload: object) -> None:
    w.store.append(
        EventEnvelope(
            event_id=f"EVT-gap-{next(_IDS)}",
            project_id=PROJECT,
            event_type=event_type,
            occurred_at=AT,
            payload=payload,  # type: ignore[arg-type]
        ),
        expected_sequence=w.store.current_sequence(PROJECT),
    )


def assumption(object_id: str, *targets: str, **overrides: object) -> Assumption:
    payload: dict[str, object] = {
        "project_id": PROJECT,
        "authority": Authority.PROPOSED,
        "confidence": 0.6,
        "provenance": SYSTEM_PROV,
        "created_at": AT,
        "scope": (SCOPE,),
        "statement": "Refund volume stays low.",
        "risk_level": RiskLevel.MEDIUM,
        "relations": tuple(rel(RelationType.AFFECTS, t) for t in targets),
    }
    payload.update(overrides)
    return Assumption(id=object_id, **payload)  # type: ignore[arg-type]


def names(routes: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(str(getattr(r, "value", r)) for r in routes)


# --- the vocabulary and the policy table -----------------------------------------------------


def test_the_route_vocabulary_is_exactly_five(gr: ModuleType) -> None:
    assert [r.value for r in gr.GapResolutionRoute] == [
        "DERIVE",
        "RESEARCH",
        "ASK_HUMAN",
        "RECONCILE",
        "PRESERVE_WAIT",
    ]
    with pytest.raises(ValueError):
        gr.GapResolutionRoute("GUESS")


@pytest.mark.parametrize("kind", list(GapKind), ids=lambda k: k.value)
def test_every_gap_kind_has_exactly_its_lawful_routes(gr: ModuleType, kind: GapKind) -> None:
    w = World()
    record(w, gap("GAP-1", kind))
    plan = gr.gap_resolution_plan(w.governor.state(), "GAP-1")
    assert names(plan.candidate_routes) == MATRIX[kind]
    assert plan.candidate_routes  # never empty


def test_no_gap_kind_is_omitted_from_the_policy(gr: ModuleType) -> None:
    assert set(gr.LAWFUL_ROUTES) == set(GapKind)
    assert all(gr.LAWFUL_ROUTES[k] for k in GapKind)


def test_route_is_a_separate_axis_not_a_gap_field(gr: ModuleType) -> None:
    for model in (Gap, IntentSynthesisGap):
        assert not {"route", "resolution_route", "candidate_routes"} & set(model.model_fields)


# --- singletons are routed; multi-route plans are not decided for anyone ---------------------


@pytest.mark.parametrize(
    ("kind", "route"),
    [
        (GapKind.MISSING_AUTHORITY, "ASK_HUMAN"),
        (GapKind.STALE_EVIDENCE, "RESEARCH"),
        (GapKind.UNDERSPECIFIED_SCOPE, "ASK_HUMAN"),
        (GapKind.WORKER_DIVERGENCE, "RECONCILE"),
        (GapKind.CONTEXT_FAILURE, "DERIVE"),
    ],
    ids=lambda v: getattr(v, "value", v),
)
def test_a_singleton_route_is_deterministic(gr: ModuleType, kind: GapKind, route: str) -> None:
    w = World()
    record(w, gap("GAP-1", kind))
    plan = gr.gap_resolution_plan(w.governor.state(), "GAP-1")
    assert plan.deterministic_route is gr.GapResolutionRoute(route)


@pytest.mark.parametrize("kind", [k for k in GapKind if len(MATRIX[k]) > 1], ids=lambda k: k.value)
def test_a_multi_route_plan_selects_nothing(gr: ModuleType, kind: GapKind) -> None:
    w = World()
    record(w, gap("GAP-1", kind))
    assert gr.gap_resolution_plan(w.governor.state(), "GAP-1").deterministic_route is None


# --- the validator is the single source of lawful selection ----------------------------------


@pytest.mark.parametrize(
    ("kind", "illegal"),
    [
        (GapKind.MISSING_AUTHORITY, "RESEARCH"),
        (GapKind.STALE_EVIDENCE, "ASK_HUMAN"),
        (GapKind.WORKER_DIVERGENCE, "DERIVE"),
        (GapKind.CONTEXT_FAILURE, "PRESERVE_WAIT"),
        (GapKind.MISSING_INFORMATION, "RECONCILE"),
    ],
    ids=lambda v: getattr(v, "value", v),
)
def test_the_validator_rejects_a_route_outside_the_lawful_set(
    gr: ModuleType, kind: GapKind, illegal: str
) -> None:
    w = World()
    record(w, gap("GAP-1", kind))
    plan = gr.gap_resolution_plan(w.governor.state(), "GAP-1")
    route = gr.GapResolutionRoute(illegal)
    assert gr.route_is_allowed(plan, route) is False
    with pytest.raises(gr.IllegalGapRouteError):
        gr.assert_route_allowed(plan, route)


@pytest.mark.parametrize("kind", list(GapKind), ids=lambda k: k.value)
def test_the_validator_accepts_every_lawful_route(gr: ModuleType, kind: GapKind) -> None:
    w = World()
    record(w, gap("GAP-1", kind))
    plan = gr.gap_resolution_plan(w.governor.state(), "GAP-1")
    for name in MATRIX[kind]:
        route = gr.GapResolutionRoute(name)
        assert gr.route_is_allowed(plan, route) is True
        gr.assert_route_allowed(plan, route)


# --- open gaps only --------------------------------------------------------------------------


def test_an_unknown_gap_fails_explicitly(gr: ModuleType) -> None:
    with pytest.raises(gr.UnknownGapError):
        gr.gap_resolution_plan(World().governor.state(), "GAP-ghost")


@pytest.mark.parametrize("close", [resolve, waive], ids=["resolved", "waived"])
def test_a_closed_gap_cannot_be_planned_as_active_work(gr: ModuleType, close) -> None:  # type: ignore[no-untyped-def]
    w = World()
    record(w, gap("GAP-1", GapKind.MISSING_AUTHORITY))
    close(w, "GAP-1")
    assert w.governor.state().gaps["GAP-1"].status is not GapStatus.OPEN
    with pytest.raises(gr.GapNotOpenError):
        gr.gap_resolution_plan(w.governor.state(), "GAP-1")


def test_bulk_planning_returns_open_gaps_only_in_stable_order(gr: ModuleType) -> None:
    w = World()
    record(
        w,
        gap("GAP-c", GapKind.AMBIGUITY),
        gap("GAP-a", GapKind.STALE_EVIDENCE),
        gap("GAP-resolved", GapKind.MISSING_AUTHORITY),
        gap("GAP-b", GapKind.CONTEXT_FAILURE, synthesis=True),
        gap("GAP-waived", GapKind.CONTRADICTION),
    )
    resolve(w, "GAP-resolved")
    waive(w, "GAP-waived")
    state = w.governor.state()
    plans = gr.open_gap_resolution_plans(state)
    assert [p.gap_id for p in plans] == ["GAP-a", "GAP-b", "GAP-c"]
    assert plans == gr.open_gap_resolution_plans(state)


def test_legacy_and_synthesis_gaps_both_plan(gr: ModuleType) -> None:
    w = World()
    record(
        w,
        gap("GAP-legacy", GapKind.MISSING_INFORMATION, "REQ-x"),
        gap("GAP-synth", GapKind.MISSING_INFORMATION, "REQ-x", synthesis=True),
    )
    state = w.governor.state()
    assert isinstance(state.gaps["GAP-synth"], IntentSynthesisGap)
    legacy = gr.gap_resolution_plan(state, "GAP-legacy")
    synth = gr.gap_resolution_plan(state, "GAP-synth")
    assert legacy.candidate_routes == synth.candidate_routes
    assert legacy.affected_object_ids == synth.affected_object_ids == ("REQ-x",)


# --- UNSUPPORTED_ASSUMPTION consumes IE2.3 ----------------------------------------------------


def test_an_unsupported_assumption_gap_expands_the_actionable_blast_radius(
    gr: ModuleType,
) -> None:
    w = World()
    w.legacy(
        requirement("REQ-A", authority=C),
        requirement("REQ-B", authority=C, relations=(rel(RelationType.DERIVED_FROM, "REQ-A"),)),
        requirement(
            "REQ-dead",
            authority=C,
            lifecycle=LifecycleStatus.SUPERSEDED,
            relations=(rel(RelationType.DERIVED_FROM, "REQ-A"),),
        ),
        requirement("REQ-C", authority=C),
        assumption("ASM-1", "REQ-A"),
        assumption("ASM-2", "REQ-C"),
        assumption("ASM-3", "REQ-A", "REQ-C"),
    )
    record(w, gap("GAP-asm", GapKind.UNSUPPORTED_ASSUMPTION, "ASM-2", "ASM-1", "ASM-3"))
    plan = gr.gap_resolution_plan(w.governor.state(), "GAP-asm")
    # Every Assumption id is expanded (not just the first), deduplicated and sorted; the
    # superseded dependant is historical, so it is not actionable.
    assert plan.assumption_impact_ids == ("REQ-A", "REQ-B", "REQ-C")
    # The durable diagnosis is preserved exactly, in its recorded order.
    assert plan.affected_object_ids == ("ASM-2", "ASM-1", "ASM-3")


def test_dangling_and_non_assumption_ids_stay_visible_and_contribute_nothing(
    gr: ModuleType,
) -> None:
    w = World()
    w.legacy(requirement("REQ-A", authority=C), assumption("ASM-1", "REQ-A"))
    record(w, gap("GAP-asm", GapKind.UNSUPPORTED_ASSUMPTION, "GHOST", "REQ-A", "ASM-1"))
    plan = gr.gap_resolution_plan(w.governor.state(), "GAP-asm")
    assert plan.affected_object_ids == ("GHOST", "REQ-A", "ASM-1")
    assert plan.assumption_impact_ids == ("REQ-A",)


def test_assumption_impact_is_only_computed_for_unsupported_assumption_gaps(
    gr: ModuleType,
) -> None:
    w = World()
    w.legacy(requirement("REQ-A", authority=C), assumption("ASM-1", "REQ-A"))
    record(w, gap("GAP-risk", GapKind.UNRESOLVED_RISK, "ASM-1"))
    assert gr.gap_resolution_plan(w.governor.state(), "GAP-risk").assumption_impact_ids == ()


def test_routing_an_unsupported_assumption_does_not_declare_it_false(gr: ModuleType) -> None:
    w = World()
    w.legacy(requirement("REQ-A", authority=C), assumption("ASM-1", "REQ-A"))
    record(w, gap("GAP-asm", GapKind.UNSUPPORTED_ASSUMPTION, "ASM-1", blocking=True))
    before = w.governor.state()
    plan = gr.gap_resolution_plan(before, "GAP-asm")
    assert names(plan.candidate_routes) == ("RESEARCH", "ASK_HUMAN", "PRESERVE_WAIT")
    after = w.governor.state()
    assert after.objects["ASM-1"] == before.objects["ASM-1"]
    assert after.objects["ASM-1"].lifecycle is LifecycleStatus.ACTIVE
    assert after.gaps["GAP-asm"].status is GapStatus.OPEN
    assert not {n for n in dir(gr) if "FALSE" in n.upper() or "INVALIDATED" in n.upper()}


# --- PRESERVE_WAIT is a lawful non-progress state --------------------------------------------


def test_preserve_wait_leaves_a_blocking_gap_open_and_blocking(gr: ModuleType) -> None:
    w = World()
    record(w, gap("GAP-wait", GapKind.INSUFFICIENT_EVIDENCE, blocking=True))
    state = w.governor.state()
    plan = gr.gap_resolution_plan(state, "GAP-wait")
    gr.assert_route_allowed(plan, gr.GapResolutionRoute.PRESERVE_WAIT)
    assert state.gaps["GAP-wait"].status is GapStatus.OPEN
    assert "OPEN_BLOCKING_GAP" in {b.code for b in evaluate_closure(state, SCOPE).blockers}
    assert gr.GapResolutionRoute.PRESERVE_WAIT.value not in {s.value for s in GapStatus}


# --- a projection only ----------------------------------------------------------------------


def test_planning_mutates_nothing_appends_nothing_and_creates_no_job(gr: ModuleType) -> None:
    w = World()
    w.legacy(requirement("REQ-A", authority=C), assumption("ASM-1", "REQ-A"))
    record(
        w,
        gap("GAP-asm", GapKind.UNSUPPORTED_ASSUMPTION, "ASM-1", blocking=True),
        gap("GAP-auth", GapKind.MISSING_AUTHORITY),
    )
    state = w.governor.state()
    gap_before = state.gaps["GAP-asm"].model_dump(mode="json")
    state_before = state.model_dump(mode="json")
    events_before = [s.event for s in w.store.load(PROJECT)]

    for _ in range(3):
        gr.open_gap_resolution_plans(state)
        gr.gap_resolution_plan(state, "GAP-asm")

    assert state.gaps["GAP-asm"].model_dump(mode="json") == gap_before
    assert state.model_dump(mode="json") == state_before
    assert [s.event for s in w.store.load(PROJECT)] == events_before
    assert state.jobs == {} or dict(state.jobs) == {}
    assert replay(PROJECT, w.store.load(PROJECT)) == state


def test_a_plan_is_ids_only(gr: ModuleType) -> None:
    assert set(gr.GapResolutionPlan.model_fields) == {
        "gap_id",
        "gap_kind",
        "candidate_routes",
        "affected_object_ids",
        "assumption_impact_ids",
        "deterministic_route",
    }


def test_the_module_imports_no_execution_or_provider_code(gr: ModuleType) -> None:
    """Routing is a contract, not execution: no jobs, providers, adapters or application."""
    with open(gr.__file__, encoding="utf-8") as handle:
        source = handle.read()
    imported = {
        line.split()[1] for line in source.splitlines() if line.startswith(("import ", "from "))
    }
    assert not {m for m in imported if m.endswith(".jobs") or "model_runtime" in m}
    assert not {m for m in imported if "adapters" in m or m.startswith("foundry.application")}


# --- R83-R85: a plan is a validated projection of LAWFUL_ROUTES, never an authority ------------

POLICY = "LAWFUL_ROUTES"
"""Every consistency refusal names the policy it enforces."""


def test_a_forged_plan_with_a_route_outside_policy_is_refused(gr: ModuleType) -> None:
    with pytest.raises(ValueError, match=POLICY):
        gr.GapResolutionPlan(
            gap_id="GAP-1",
            gap_kind=GapKind.MISSING_AUTHORITY,
            candidate_routes=(gr.GapResolutionRoute.RESEARCH,),
            affected_object_ids=(),
            deterministic_route=gr.GapResolutionRoute.RESEARCH,
        )


def test_a_forged_decision_on_a_multi_route_plan_is_refused(gr: ModuleType) -> None:
    candidates = tuple(gr.GapResolutionRoute(n) for n in MATRIX[GapKind.MISSING_INFORMATION])
    with pytest.raises(ValueError, match=POLICY):
        gr.GapResolutionPlan(
            gap_id="GAP-1",
            gap_kind=GapKind.MISSING_INFORMATION,
            candidate_routes=candidates,
            affected_object_ids=(),
            deterministic_route=gr.GapResolutionRoute.DERIVE,
        )


def test_a_singleton_plan_without_its_deterministic_route_is_refused(gr: ModuleType) -> None:
    with pytest.raises(ValueError, match=POLICY):
        gr.GapResolutionPlan(
            gap_id="GAP-1",
            gap_kind=GapKind.MISSING_AUTHORITY,
            candidate_routes=(gr.GapResolutionRoute.ASK_HUMAN,),
            affected_object_ids=(),
            deterministic_route=None,
        )


def test_a_reordered_candidate_tuple_is_refused(gr: ModuleType) -> None:
    candidates = tuple(gr.GapResolutionRoute(n) for n in reversed(MATRIX[GapKind.AMBIGUITY]))
    with pytest.raises(ValueError, match=POLICY):
        gr.GapResolutionPlan(
            gap_id="GAP-1",
            gap_kind=GapKind.AMBIGUITY,
            candidate_routes=candidates,
            affected_object_ids=(),
        )


def test_route_validation_reads_the_policy_not_the_plans_candidates(gr: ModuleType) -> None:
    """Even a plan smuggled past validation (``model_construct``) cannot widen the policy."""
    forged = gr.GapResolutionPlan.model_construct(
        gap_id="GAP-1",
        gap_kind=GapKind.MISSING_AUTHORITY,
        candidate_routes=(gr.GapResolutionRoute.RESEARCH, gr.GapResolutionRoute.ASK_HUMAN),
        affected_object_ids=(),
        assumption_impact_ids=(),
        deterministic_route=None,
    )
    assert gr.route_is_allowed(forged, gr.GapResolutionRoute.RESEARCH) is False
    with pytest.raises(gr.IllegalGapRouteError):
        gr.assert_route_allowed(forged, gr.GapResolutionRoute.RESEARCH)
    assert gr.route_is_allowed(forged, gr.GapResolutionRoute.ASK_HUMAN) is True


@pytest.mark.parametrize("synthesis", [False, True], ids=["legacy", "synthesis"])
@pytest.mark.parametrize("kind", list(GapKind), ids=lambda k: k.value)
def test_the_planner_records_the_gaps_actual_kind(
    gr: ModuleType, kind: GapKind, synthesis: bool
) -> None:
    w = World()
    record(w, gap("GAP-1", kind, "REQ-x", synthesis=synthesis))
    plan = gr.gap_resolution_plan(w.governor.state(), "GAP-1")
    assert plan.gap_kind is kind
    # A legitimate projected plan round-trips through its own validation unchanged.
    assert gr.GapResolutionPlan.model_validate(plan.model_dump()) == plan
    assert gr.GapResolutionPlan.model_validate_json(plan.model_dump_json()) == plan

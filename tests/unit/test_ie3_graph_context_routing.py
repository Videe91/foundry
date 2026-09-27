"""IE3 Slice 3 — bounded graph context, R109 origin and pure whole-graph routing.

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§13, §17-§21; R102,
R104, R109; Q4). Context is compiled from real governed state; origin and routing are pure.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from foundry.application.intent_graph_synthesis_context import (
    IntentGraphResultError,
    compile_intent_graph_context,
    graph_visibility_from_request,
    known_graph_context_character_count,
    validate_graph_result,
)
from foundry.application.intent_synthesis_context import (
    KNOWN_INTENT_OBJECT_THRESHOLD,
    MAX_KNOWN_INTENT_CONTEXT_CHARS,
)
from foundry.application.replay import replay
from foundry.domain.common import Authority, RelationType, SourceKind
from foundry.domain.events import EventEnvelope, EventType, GapPayload
from foundry.domain.gaps import Gap, GapKind
from foundry.domain.intent_graph import (
    IE3_GRAPH_NODE_KINDS,
    IE3_MODEL_GAP_KINDS,
    IntentGraphSynthesisResult,
)
from foundry.domain.intent_graph_routing import (
    GraphRoutingOutcome,
    derive_graph_origins,
    route_graph_with_assigned_authority,
    route_intent_graph,
)
from foundry.domain.intent_synthesis import IntentSynthesisRoute, SynthesisOrigin
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import ConstraintFacet, SemanticKind
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.domain.state import IntentState
from foundry.ports.intent_graph_synthesizer import (
    GraphLimits,
    IntentGraphSynthesisRequest,
    KnownGraphObject,
)
from tests.unit._ie3_fixtures import b, e, edge, gap, node, result
from tests.unit._ie3_s3_fixtures import AI, BOB, HUMAN_BOB, HUMAN_G, RESEARCHER
from tests.unit._ie21_fixtures import (
    ALICE,
    PROJECT,
    SCOPE,
    goal,
    project_decision,
    rel,
    requirement,
)
from tests.unit._ie22b_fixtures import ROOT_ID, World

K = SemanticKind
S = RelationType.SERVES
D = RelationType.DERIVED_FROM
A = RelationType.AFFECTS
R = IntentSynthesisRoute
AT = "2026-09-27T12:00:00Z"


def _state(world: World) -> IntentState:
    return replay(PROJECT, world.store.load(PROJECT))


def _gap_event(world: World, gap_obj: Gap) -> None:
    world.store.append(
        EventEnvelope(
            event_id=f"EVT-gap-{gap_obj.id}",
            project_id=PROJECT,
            event_type=EventType.GAP_RECORDED,
            occurred_at=AT,
            payload=GapPayload(gap=gap_obj),
        ),
        expected_sequence=world.store.current_sequence(PROJECT),
    )


def _rich_world() -> tuple[World, str]:
    """Root, goals, a Decision with private rationale, dead/other-scope/stale objects, gaps."""
    world = World()
    # Old first, live last: the address head must be the live version, or the locus is stale.
    old = world.claim("J-old", authority=Authority.CANONICAL, text="thirty calendar days")
    live = world.claim("J-live", authority=Authority.CANONICAL)
    world.admit_root()
    world.legacy(
        goal("GOAL-live", relations=(rel(S, ROOT_ID), rel(RelationType.RELATES_TO, ROOT_ID))),
        goal("GOAL-hidden-target", relations=(rel(S, "GOAL-other-scope"),)),
        goal("GOAL-other-scope", scope=("elsewhere",)),
        goal("GOAL-dead", authority=Authority.SUPERSEDED),
        goal("GOAL-project-wide", scope=(), relations=(rel(S, ROOT_ID),)),
        project_decision(
            "DEC-private", rationale="PRIVATE-DELIBERATION-TEXT", relations=(rel(S, "GOAL-live"),)
        ),
        requirement("REQ-stale", relations=(rel(S, "GOAL-live"), rel(D, old))),
    )
    world.governor.derive("REQ-stale", old)
    world.supersede("J-sup", "J-old")
    _gap_event(
        world,
        Gap(
            id="GAP-open",
            project_id=PROJECT,
            kind=GapKind.MISSING_INFORMATION,
            description="Which currency?",
            materiality="LOW",
            risk="LOW",
            affected_object_ids=("GOAL-live", "GOAL-other-scope"),
            blocking=True,
        ),
    )
    _gap_event(
        world,
        IntentSynthesisGap(
            id="GAP-elsewhere",
            project_id=PROJECT,
            kind=GapKind.AMBIGUITY,
            description="Not ours.",
            affected_object_ids=(),
            blocking=True,
            scope=("elsewhere",),
        ),
    )
    return world, live


# ------------------------------------------------------------------------ context


def test_request_shows_exactly_the_current_in_scope_ie3_objects() -> None:
    world, live = _rich_world()
    context = compile_intent_graph_context(_state(world), scope=SCOPE)
    assert context.context_failure is None
    request = context.request
    assert request is not None
    ids = [o.object_id for o in request.known_objects]
    assert ids == sorted(ids)
    assert set(ids) == {
        ROOT_ID,
        "GOAL-live",
        "GOAL-hidden-target",
        "GOAL-project-wide",
        "DEC-private",
        "REQ-stale",
    }
    assert request.project_id == PROJECT
    assert request.scope == SCOPE


def test_stale_objects_are_shown_and_flagged() -> None:
    world, _ = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    flags = {o.object_id: o.is_stale for o in request.known_objects}
    assert flags["REQ-stale"] is True
    assert flags["GOAL-live"] is False


def test_decision_rationale_is_never_shown() -> None:
    world, _ = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    assert "PRIVATE-DELIBERATION-TEXT" not in request.model_dump_json()
    decision = next(o for o in request.known_objects if o.object_id == "DEC-private")
    assert decision.text == "We chose PostgreSQL."
    assert "rationale" not in KnownGraphObject.model_fields


def test_relations_are_filtered_to_four_axes_and_visible_targets() -> None:
    world, live = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    by_id = {o.object_id: o for o in request.known_objects}
    assert [(r.relation_type, r.target_id) for r in by_id["GOAL-live"].relations] == [(S, ROOT_ID)]
    assert by_id["GOAL-hidden-target"].relations == ()
    stale = by_id["REQ-stale"]
    # The superseded claim is no longer shown as basis, so its edge is filtered too.
    assert [(r.relation_type, r.target_id) for r in stale.relations] == [(S, "GOAL-live")]


def test_canonical_roots_and_open_applicable_gaps() -> None:
    world, _ = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    assert request.root_intent_ids == (ROOT_ID,)
    assert [g.gap_id for g in request.open_gaps] == ["GAP-open"]
    assert request.open_gaps[0].affected_object_ids == ("GOAL-live",)


def test_basis_is_the_live_semantic_basis_only() -> None:
    world, live = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    shown = {c.claim_id for locus in request.basis for c in locus.live_claims}
    assert live in shown


def test_the_request_is_deterministic_and_pinned() -> None:
    world, _ = _rich_world()
    state = _state(world)
    first = compile_intent_graph_context(state, scope=SCOPE)
    assert first == compile_intent_graph_context(state, scope=SCOPE)
    request = first.request
    assert request is not None
    assert request.allowed_node_kinds == IE3_GRAPH_NODE_KINDS
    assert request.allowed_gap_kinds == IE3_MODEL_GAP_KINDS
    assert (request.limits.max_nodes, request.limits.max_relations, request.limits.max_gaps) == (
        32,
        128,
        16,
    )
    with pytest.raises(ValidationError):
        GraphLimits(max_nodes=33)


def test_basis_may_be_empty_when_known_objects_carry_the_run() -> None:
    world = World()
    world.admit_root()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    assert request.basis == ()
    assert [o.object_id for o in request.known_objects] == [ROOT_ID]


def test_nothing_to_show_means_no_request_and_no_failure() -> None:
    context = compile_intent_graph_context(_state(World()), scope=SCOPE)
    assert context.request is None
    assert context.context_failure is None


def test_a_request_needs_basis_or_known_objects() -> None:
    with pytest.raises(ValidationError, match="basis or known_objects"):
        IntentGraphSynthesisRequest(project_id=PROJECT, scope=SCOPE)


def test_over_the_object_bound_is_a_context_failure_never_a_truncation() -> None:
    world = World()
    world.legacy(*(goal(f"GOAL-{i:03d}") for i in range(KNOWN_INTENT_OBJECT_THRESHOLD + 1)))
    context = compile_intent_graph_context(_state(world), scope=SCOPE)
    assert context.request is None
    assert context.context_failure is not None
    assert str(KNOWN_INTENT_OBJECT_THRESHOLD) in context.context_failure


def test_exactly_at_the_object_bound_is_accepted() -> None:
    world = World()
    world.legacy(*(goal(f"GOAL-{i:03d}") for i in range(KNOWN_INTENT_OBJECT_THRESHOLD)))
    context = compile_intent_graph_context(_state(world), scope=SCOPE)
    assert context.request is not None
    assert len(context.request.known_objects) == KNOWN_INTENT_OBJECT_THRESHOLD


def test_over_the_character_bound_is_a_context_failure_never_a_truncation() -> None:
    world = World()
    long_text = "x" * 1_000
    world.legacy(*(goal(f"GOAL-{i:03d}", statement=long_text) for i in range(140)))
    context = compile_intent_graph_context(_state(world), scope=SCOPE)
    assert context.request is None
    assert context.context_failure is not None
    assert str(MAX_KNOWN_INTENT_CONTEXT_CHARS) in context.context_failure


def test_character_count_is_measured_on_the_known_objects_rendering() -> None:
    world, _ = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    assert known_graph_context_character_count(request.known_objects) > 0


# --------------------------------------------------------- result validation vs request


def _validate(graph: IntentGraphSynthesisResult, request: IntentGraphSynthesisRequest) -> None:
    validate_graph_result(graph, request, author_is_human=False)


def test_visibility_comes_from_the_request_alone() -> None:
    world, live = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    vis = graph_visibility_from_request(request)
    assert {o.object_id for o in vis.objects} == {o.object_id for o in request.known_objects}
    assert vis.root_intent_ids == request.root_intent_ids
    assert live in vis.basis_claim_ids
    assert vis.run_scope == SCOPE


def test_an_unshown_existing_object_is_never_rescued_from_state() -> None:
    world, live = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-other-scope")), edge("req", D, b(live))),
    )
    with pytest.raises(IntentGraphResultError, match="INVISIBLE_EXISTING_REF"):
        _validate(graph, request)


def test_an_unshown_claim_is_never_rescued_from_state() -> None:
    world, live = _rich_world()
    state = _state(world)
    request = compile_intent_graph_context(state, scope=SCOPE).request
    assert request is not None
    superseded = next(c for c in state.semantic.claims if c != live)
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-live")), edge("req", D, b(superseded))),
    )
    with pytest.raises(IntentGraphResultError, match="INVISIBLE_BASIS_REF"):
        _validate(graph, request)


def test_a_valid_result_passes_against_its_request() -> None:
    world, live = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-live")), edge("req", D, b(live))),
    )
    _validate(graph, request)


def test_result_limits_and_kinds_must_match_the_request() -> None:
    world, live = _rich_world()
    request = compile_intent_graph_context(_state(world), scope=SCOPE).request
    assert request is not None
    narrowed = request.model_copy(update={"allowed_node_kinds": frozenset({K.GOAL})})
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-live")), edge("req", D, b(live))),
    )
    with pytest.raises(IntentGraphResultError, match="not allowed"):
        _validate(graph, narrowed)


# ------------------------------------------------------------------------ R109 origin


KINDS = {
    "C-research-1": (SourceKind.RESEARCH,),
    "C-research-2": (SourceKind.RESEARCH,),
    "C-human": (SourceKind.HUMAN,),
    "C-mixed": (SourceKind.HUMAN, SourceKind.RESEARCH),
}


def _origin(graph: IntentGraphSynthesisResult, *, human: bool = False) -> SynthesisOrigin:
    origins = derive_graph_origins(graph, claim_source_kinds=KINDS, author_is_human=human)
    return origins["req"]


def _req(*relations: tuple[RelationType, object]) -> IntentGraphSynthesisResult:
    return result(
        node(K.REQUIREMENT, "req"),
        node(K.GOAL, "goal"),
        relations=tuple(edge("req", t, target) for t, target in relations),  # type: ignore[arg-type]
    )


def test_r109_human_author_is_always_human_stated() -> None:
    assert _origin(_req((D, b("C-research-1"))), human=True) is SynthesisOrigin.HUMAN_STATED
    assert _origin(_req(), human=True) is SynthesisOrigin.HUMAN_STATED


def test_r109_one_all_research_claim_is_research_derived() -> None:
    assert _origin(_req((D, b("C-research-1")))) is SynthesisOrigin.RESEARCH_DERIVED


def test_r109_several_all_research_claims_are_research_derived() -> None:
    graph = _req((D, b("C-research-1")), (D, b("C-research-2")))
    assert _origin(graph) is SynthesisOrigin.RESEARCH_DERIVED


def test_r109_one_non_research_claim_is_ai_inferred() -> None:
    assert _origin(_req((D, b("C-research-1")), (D, b("C-human")))) is SynthesisOrigin.AI_INFERRED
    assert _origin(_req((D, b("C-mixed")))) is SynthesisOrigin.AI_INFERRED


def test_r109_zero_direct_claims_is_ai_inferred() -> None:
    assert _origin(_req()) is SynthesisOrigin.AI_INFERRED


def test_r109_existing_decision_basis_is_ai_inferred() -> None:
    assert _origin(_req((D, e("DEC-x")))) is SynthesisOrigin.AI_INFERRED


def test_r109_local_node_basis_is_ai_inferred() -> None:
    assert _origin(_req((D, "goal"))) is SynthesisOrigin.AI_INFERRED


def test_r109_serves_to_nothing_research_does_not_count() -> None:
    assert _origin(_req((S, "goal"))) is SynthesisOrigin.AI_INFERRED


def test_r109_every_node_gets_an_origin() -> None:
    graph = _req((D, b("C-research-1")))
    origins = derive_graph_origins(graph, claim_source_kinds=KINDS, author_is_human=False)
    assert origins == {
        "goal": SynthesisOrigin.AI_INFERRED,
        "req": SynthesisOrigin.RESEARCH_DERIVED,
    }


# ------------------------------------------------------------------------- routing


def _routing_world(*, canonical_target: bool = False) -> IntentState:
    world = World()
    old = world.claim("J-old", authority=Authority.CANONICAL)
    world.admit_root()
    world.legacy(
        goal("GOAL-root", authority=Authority.CANONICAL, relations=(rel(S, ROOT_ID),)),
        requirement(
            "REQ-old",
            authority=Authority.CANONICAL if canonical_target else Authority.PROPOSED,
            relations=(rel(S, "GOAL-root"),),
        ),
    )
    world.governor.derive("REQ-old", old)
    world.supersede("J-sup", "J-old")
    return _state(world)


def _route(
    state: IntentState,
    graph: IntentGraphSynthesisResult,
    *,
    author: ReasonerFingerprint = AI,
    human_actor_id: str | None = None,
) -> GraphRoutingOutcome:
    origins = derive_graph_origins(graph, claim_source_kinds={}, author_is_human=author.is_human)
    return route_intent_graph(
        state,
        result=graph,
        origins=origins,
        author=author,
        human_actor_id=human_actor_id,
        run_scope=SCOPE,
    )


GOAL_GRAPH = result(node(K.GOAL, "goal"), relations=(edge("goal", S, e("GOAL-root")),))


def test_human_with_covering_authority_is_canonical_apply() -> None:
    outcome = _route(_routing_world(), GOAL_GRAPH, author=HUMAN_G, human_actor_id=ALICE)
    assert outcome.decision.route is R.APPLY
    assert [(a.local_id, a.authority) for a in outcome.node_assignments] == [
        ("goal", Authority.CANONICAL)
    ]


def test_human_without_authority_requires_a_human() -> None:
    outcome = _route(_routing_world(), GOAL_GRAPH, author=HUMAN_BOB, human_actor_id=BOB)
    assert outcome.decision.route is R.REQUIRE_HUMAN
    assert outcome.decision.reasons == ("AUTHORITY_UNRESOLVED",)
    assert outcome.node_assignments[0].authority is None


def test_non_human_is_proposed_apply() -> None:
    outcome = _route(_routing_world(), GOAL_GRAPH)
    assert outcome.decision.route is R.APPLY
    assert outcome.node_assignments[0].authority is Authority.PROPOSED
    assert outcome.node_assignments[0].origin is SynthesisOrigin.AI_INFERRED


def test_research_origin_is_still_only_proposed() -> None:
    state = _routing_world()
    origins = {"goal": SynthesisOrigin.RESEARCH_DERIVED}
    outcome = route_intent_graph(
        state,
        result=GOAL_GRAPH,
        origins=origins,
        author=RESEARCHER,
        human_actor_id=None,
        run_scope=SCOPE,
    )
    assert outcome.node_assignments[0].authority is Authority.PROPOSED


def test_negative_control_non_human_canonical_is_rejected() -> None:
    decision = route_graph_with_assigned_authority(
        _routing_world(),
        result=GOAL_GRAPH,
        origins={"goal": SynthesisOrigin.AI_INFERRED},
        authorities={"goal": Authority.CANONICAL},
    )
    assert decision.route is R.REJECT
    assert decision.reasons == ("AUTHORITY_INVENTION",)


def _mandate_graph() -> IntentGraphSynthesisResult:
    return result(
        node(K.CONSTRAINT, "con", facet=ConstraintFacet.EXTERNAL_MANDATE),
        relations=(edge("con", S, e("GOAL-root")),),
    )


def test_q4_human_external_mandate_is_deferred_to_a_human() -> None:
    outcome = _route(_routing_world(), _mandate_graph(), author=HUMAN_G, human_actor_id=ALICE)
    assert outcome.decision.route is R.REQUIRE_HUMAN
    assert "EXTERNAL_MANDATE_DEFERRED" in outcome.decision.reasons


def test_q4_non_human_external_mandate_is_proposed() -> None:
    outcome = _route(_routing_world(), _mandate_graph())
    assert outcome.decision.route is R.APPLY
    assert outcome.node_assignments[0].authority is Authority.PROPOSED


def _replacement() -> IntentGraphSynthesisResult:
    return result(
        node(K.REQUIREMENT, "req2", disposition="REPLACES_STALE", replaces=e("REQ-old")),
        relations=(edge("req2", S, e("GOAL-root")),),
    )


def test_c11_canonical_target_with_proposed_replacement_requires_a_human() -> None:
    outcome = _route(_routing_world(canonical_target=True), _replacement())
    assert outcome.decision.route is R.REQUIRE_HUMAN
    assert outcome.decision.reasons == ("CANONICAL_REPLACEMENT_REQUIRED",)


def test_c11_proposed_target_may_be_replaced_by_proposed() -> None:
    assert _route(_routing_world(), _replacement()).decision.route is R.APPLY


def test_blocking_gaps_do_not_force_a_human_route() -> None:
    graph = result(
        node(K.GOAL, "goal"),
        relations=(edge("goal", S, e("GOAL-root")),),
        gaps=(gap("g1", kind=GapKind.MISSING_INFORMATION),),
    )
    outcome = _route(_routing_world(), graph)
    assert outcome.decision.route is R.APPLY


def test_a_gap_only_result_applies_so_the_work_becomes_durable() -> None:
    outcome = _route(_routing_world(), result(gaps=(gap("g1"),)))
    assert outcome.decision.route is R.APPLY
    assert outcome.node_assignments == ()


def test_precedence_reject_over_require_human_over_apply() -> None:
    state = _routing_world(canonical_target=True)
    graph = result(
        node(K.GOAL, "goal"),
        node(K.REQUIREMENT, "req2", disposition="REPLACES_STALE", replaces=e("REQ-old")),
        relations=(edge("goal", S, e("GOAL-root")), edge("req2", S, e("GOAL-root"))),
    )
    both = route_graph_with_assigned_authority(
        state,
        result=graph,
        origins={"goal": SynthesisOrigin.AI_INFERRED, "req2": SynthesisOrigin.AI_INFERRED},
        authorities={"goal": Authority.CANONICAL, "req2": Authority.PROPOSED},
    )
    assert both.route is R.REJECT
    human_only = route_graph_with_assigned_authority(
        state,
        result=graph,
        origins={"goal": SynthesisOrigin.AI_INFERRED, "req2": SynthesisOrigin.AI_INFERRED},
        authorities={"goal": Authority.PROPOSED, "req2": Authority.PROPOSED},
    )
    assert human_only.route is R.REQUIRE_HUMAN


def test_origin_must_follow_the_author() -> None:
    with pytest.raises(ValueError, match="origin"):
        route_intent_graph(
            _routing_world(),
            result=GOAL_GRAPH,
            origins={"goal": SynthesisOrigin.HUMAN_STATED},
            author=AI,
            human_actor_id=None,
            run_scope=SCOPE,
        )


def test_human_authorship_needs_an_authenticated_actor() -> None:
    with pytest.raises(ValueError, match="human_actor_id"):
        _route(_routing_world(), GOAL_GRAPH, author=HUMAN_G, human_actor_id=None)

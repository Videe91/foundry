"""IE3 Slice 1 — structural graph validation against a bounded visibility surface.

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§9-§12, §17, §19;
R100, R101, R104). Every refusal is asserted by its code, so a test cannot pass because the
graph happened to fail for some other reason.
"""

from __future__ import annotations

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.replay import replay
from foundry.domain.common import Authority, RelationType
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import (
    MAX_GRAPH_NODES,
    GraphNodeDisposition,
    GraphNodeProposal,
    GraphRelationProposal,
    IntentGraphSynthesisResult,
)
from foundry.domain.intent_graph_validation import (
    GraphVisibility,
    IntentGraphValidationError,
    graph_visibility,
    validate_intent_graph,
)
from foundry.domain.semantic import ConstraintFacet, SemanticKind
from tests.unit._ie3_fixtures import (
    SCOPE,
    b,
    e,
    edge,
    gap,
    local,
    node,
    result,
    visibility,
    visible,
)
from tests.unit._ie21_fixtures import goal, intent, rel
from tests.unit._ie22b_fixtures import World

K = SemanticKind
R = RelationType
D = R.DERIVED_FROM
S = R.SERVES
X = R.EXCLUDES
A = R.AFFECTS


def refused(
    code: str, graph: IntentGraphSynthesisResult, vis: GraphVisibility, *, human: bool
) -> str:
    with pytest.raises(IntentGraphValidationError) as caught:
        validate_intent_graph(graph, vis, author_is_human=human)
    assert caught.value.code == code, str(caught.value)
    assert str(caught.value).startswith(f"{code}:")
    return str(caught.value)


def accepted(graph: IntentGraphSynthesisResult, vis: GraphVisibility, *, human: bool) -> None:
    validate_intent_graph(graph, vis, author_is_human=human)


# A human-authored spine with no existing intent: Intent <- Goal <- Requirement.
SPINE_NODES: tuple[GraphNodeProposal, ...] = (
    node(K.INTENT, "intent"),
    node(K.GOAL, "goal"),
    node(K.REQUIREMENT, "req"),
)
SPINE_EDGES: tuple[GraphRelationProposal, ...] = (
    edge("goal", S, "intent"),
    edge("req", S, "goal"),
)
EMPTY = visibility()


def spine(
    *extra: GraphNodeProposal,
    relations: tuple[GraphRelationProposal, ...] = (),
    gaps: tuple = (),
) -> IntentGraphSynthesisResult:
    return result(*SPINE_NODES, *extra, relations=(*SPINE_EDGES, *relations), gaps=gaps)


# An existing world a model may build into: a canonical root, a Goal serving it, and a
# canonical Decision serving the Goal. CLAIM-1 is the one visible basis claim.
AI_WORLD = visibility(
    visible("INTENT-root", K.INTENT),
    visible("GOAL-root", K.GOAL, relations=((S, "INTENT-root"),)),
    visible("DEC-x", K.DECISION, relations=((S, "GOAL-root"),)),
    visible("GOAL-grounded", K.GOAL, relations=((S, "INTENT-root"), (D, "CLAIM-1"))),
    visible("REQ-stale", K.REQUIREMENT, is_stale=True, relations=((S, "GOAL-root"),)),
    visible("REQ-fresh", K.REQUIREMENT, relations=((S, "GOAL-root"),)),
    visible("INTENT-dead", K.INTENT, authority=Authority.SUPERSEDED, is_current=False),
)


def ai_req(local_id: str = "req", *relations: GraphRelationProposal) -> IntentGraphSynthesisResult:
    return result(node(K.REQUIREMENT, local_id), relations=relations)


# ---------------------------------------------------------------------- baseline


def test_human_spine_is_valid() -> None:
    accepted(spine(), EMPTY, human=True)


def test_model_requirement_grounded_on_a_claim_serving_an_existing_goal_is_valid() -> None:
    accepted(
        ai_req("req", edge("req", S, e("GOAL-root")), edge("req", D, b("CLAIM-1"))),
        AI_WORLD,
        human=False,
    )


def test_a_graph_at_the_node_cap_validates() -> None:
    goals = [node(K.GOAL, f"g{i}") for i in range(MAX_GRAPH_NODES - 1)]
    graph = result(
        node(K.INTENT, "intent"),
        *goals,
        relations=tuple(edge(f"g{i}", S, "intent") for i in range(MAX_GRAPH_NODES - 1)),
    )
    accepted(graph, EMPTY, human=True)


# --------------------------------------------------------------- reference resolution


def test_unresolved_local_ref_is_refused() -> None:
    refused(
        "UNRESOLVED_LOCAL_REF", spine(relations=(edge("req", S, "nowhere"),)), EMPTY, human=True
    )


def test_unresolved_local_source_is_refused() -> None:
    refused("UNRESOLVED_LOCAL_REF", spine(relations=(edge("ghost", S, "goal"),)), EMPTY, human=True)


def test_invisible_existing_ref_is_refused() -> None:
    refused(
        "INVISIBLE_EXISTING_REF",
        spine(relations=(edge("req", S, e("GOAL-hidden")),)),
        EMPTY,
        human=True,
    )


def test_non_current_existing_ref_is_refused() -> None:
    graph = result(
        node(K.GOAL, "g"), relations=(edge("g", S, e("INTENT-dead")), edge("g", D, b("CLAIM-1")))
    )
    refused("EXISTING_NOT_CURRENT", graph, AI_WORLD, human=False)


def test_invisible_basis_ref_is_refused() -> None:
    refused(
        "INVISIBLE_BASIS_REF",
        spine(relations=(edge("req", D, b("CLAIM-hidden")),)),
        EMPTY,
        human=True,
    )


def test_gap_anchors_must_resolve() -> None:
    refused(
        "UNRESOLVED_LOCAL_REF", spine(gaps=(gap(anchors=(local("nowhere"),)),)), EMPTY, human=True
    )
    refused(
        "INVISIBLE_EXISTING_REF", spine(gaps=(gap(anchors=(e("GOAL-hidden"),)),)), EMPTY, human=True
    )
    refused("INVISIBLE_BASIS_REF", spine(gaps=(gap(anchors=(b("CLAIM-x"),)),)), EMPTY, human=True)
    accepted(spine(gaps=(gap(anchors=(local("req"), b("CLAIM-1"))),)), EMPTY, human=True)


# ------------------------------------------------------------ relation legality (§10)

LEGAL = {
    "goal SERVES intent": ((), ()),
    "req SERVES goal": ((), ()),
    "outcome SERVES goal": ((node(K.OUTCOME, "o"),), (edge("o", S, "goal"),)),
    "constraint SERVES intent": ((node(K.CONSTRAINT, "c"),), (edge("c", S, "intent"),)),
    "preference SERVES goal": ((node(K.PREFERENCE, "p"),), (edge("p", S, "goal"),)),
    "non-goal SERVES goal": ((node(K.NON_GOAL, "n"),), (edge("n", S, "goal"),)),
    "decision SERVES goal": ((node(K.DECISION, "d"),), (edge("d", S, "goal"),)),
    "non-goal EXCLUDES req": (
        (node(K.NON_GOAL, "n"),),
        (edge("n", S, "goal"), edge("n", X, "req")),
    ),
    "assumption AFFECTS req": ((node(K.ASSUMPTION, "a"),), (edge("a", A, "req"),)),
    "req DERIVED_FROM decision": (
        (node(K.DECISION, "d"), node(K.REQUIREMENT, "r2")),
        (edge("d", S, "goal"), edge("r2", S, "goal"), edge("r2", D, "d")),
    ),
    "req DERIVED_FROM claim": ((), (edge("req", D, b("CLAIM-1")),)),
    "req DERIVED_FROM goal": ((), (edge("req", D, "goal"),)),
}


@pytest.mark.parametrize("case", sorted(LEGAL))
def test_legal_relations_are_accepted(case: str) -> None:
    extra_nodes, extra_edges = LEGAL[case]
    accepted(spine(*extra_nodes, relations=extra_edges), EMPTY, human=True)


ILLEGAL = {
    "intent SERVES goal": ((), (edge("intent", S, "goal"),)),
    "req DERIVED_FROM intent": ((), (edge("req", D, "intent"),)),
    "goal SERVES req": ((), (edge("goal", S, "req"),)),
    "req SERVES claim": ((), (edge("req", S, b("CLAIM-1")),)),
    "req EXCLUDES goal": ((), (edge("req", X, "goal"),)),
    "goal EXCLUDES req": ((), (edge("goal", X, "req"),)),
    "non-goal EXCLUDES intent": (
        (node(K.NON_GOAL, "n"),),
        (edge("n", S, "goal"), edge("n", X, "intent")),
    ),
    "assumption DERIVED_FROM claim": (
        (node(K.ASSUMPTION, "a"),),
        (edge("a", A, "req"), edge("a", D, b("CLAIM-1"))),
    ),
    "assumption SERVES goal": (
        (node(K.ASSUMPTION, "a"),),
        (edge("a", A, "req"), edge("a", S, "goal")),
    ),
    "preference AFFECTS req": (
        (node(K.PREFERENCE, "p"),),
        (edge("p", S, "goal"), edge("p", A, "req")),
    ),
    "req AFFECTS goal": ((), (edge("req", A, "goal"),)),
    "req DERIVED_FROM assumption": (
        (node(K.ASSUMPTION, "a"),),
        (edge("a", A, "req"), edge("req", D, "a")),
    ),
    "req DERIVED_FROM preference": (
        (node(K.PREFERENCE, "p"),),
        (edge("p", S, "goal"), edge("req", D, "p")),
    ),
}


@pytest.mark.parametrize("case", sorted(ILLEGAL))
def test_illegal_relations_are_refused(case: str) -> None:
    extra_nodes, extra_edges = ILLEGAL[case]
    refused("ILLEGAL_RELATION", spine(*extra_nodes, relations=extra_edges), EMPTY, human=True)


def test_illegal_relation_to_an_existing_object_is_refused() -> None:
    graph = ai_req("req", edge("req", S, e("REQ-fresh")), edge("req", D, b("CLAIM-1")))
    refused("ILLEGAL_RELATION", graph, AI_WORLD, human=False)


def test_duplicate_edge_is_refused() -> None:
    refused("DUPLICATE_RELATION", spine(relations=(edge("req", S, "goal"),)), EMPTY, human=True)


def test_self_edge_is_refused() -> None:
    refused("SELF_RELATION", spine(relations=(edge("goal", S, "goal"),)), EMPTY, human=True)


# ------------------------------------------------------------------------ cycles


def test_serves_cycle_is_refused() -> None:
    graph = spine(node(K.GOAL, "g2"), relations=(edge("g2", S, "goal"), edge("goal", S, "g2")))
    refused("RELATION_CYCLE", graph, EMPTY, human=True)


def test_derived_from_cycle_is_refused() -> None:
    graph = spine(
        node(K.REQUIREMENT, "r2"),
        relations=(edge("r2", S, "goal"), edge("req", D, "r2"), edge("r2", D, "req")),
    )
    refused("RELATION_CYCLE", graph, EMPTY, human=True)


def test_mixed_axes_do_not_form_a_cycle() -> None:
    # goal SERVES intent and req DERIVED_FROM goal / req SERVES goal: no single-axis cycle.
    accepted(spine(relations=(edge("req", D, "goal"),)), EMPTY, human=True)


def test_historical_cycle_among_existing_objects_terminates_and_grants_no_relevance() -> None:
    historic = visibility(
        visible("GOAL-a", K.GOAL, relations=((S, "GOAL-b"),)),
        visible("GOAL-b", K.GOAL, relations=((S, "GOAL-a"),)),
    )
    graph = ai_req("req", edge("req", S, e("GOAL-a")), edge("req", D, b("CLAIM-1")))
    refused("NO_RELEVANCE", graph, historic, human=False)


# -------------------------------------------------------------- relevance / roots (§12)


def test_relevance_bearing_node_without_serves_is_refused() -> None:
    graph = result(*SPINE_NODES, relations=(edge("goal", S, "intent"),))
    message = refused("NO_RELEVANCE", graph, EMPTY, human=True)
    assert "'req'" in message


def test_serves_chain_that_never_reaches_an_intent_is_refused() -> None:
    graph = result(
        node(K.GOAL, "goal"), node(K.REQUIREMENT, "req"), relations=(edge("req", S, "goal"),)
    )
    refused("NO_RELEVANCE", graph, EMPTY, human=True)


def test_reach_through_local_goal_to_local_intent_is_accepted() -> None:
    accepted(spine(), EMPTY, human=True)


def test_reach_through_existing_goal_to_existing_intent_is_accepted() -> None:
    graph = result(node(K.REQUIREMENT, "req"), relations=(edge("req", S, e("GOAL-root")),))
    accepted(graph, AI_WORLD, human=True)


def test_relevance_is_never_inferred_from_sharing_a_batch() -> None:
    graph = result(node(K.INTENT, "intent"), node(K.REQUIREMENT, "req"))
    refused("NO_RELEVANCE", graph, EMPTY, human=True)


def test_derived_from_never_counts_as_relevance() -> None:
    graph = result(
        node(K.INTENT, "intent"),
        node(K.GOAL, "goal"),
        node(K.REQUIREMENT, "req"),
        relations=(edge("goal", S, "intent"), edge("req", D, "goal")),
    )
    message = refused("NO_RELEVANCE", graph, EMPTY, human=True)
    assert "'req'" in message


def test_two_new_roots_are_refused() -> None:
    graph = result(node(K.INTENT, "i1"), node(K.INTENT, "i2"))
    refused("MULTIPLE_ROOTS", graph, EMPTY, human=True)


def test_new_root_beside_a_visible_current_intent_is_refused() -> None:
    graph = result(node(K.INTENT, "i1"))
    refused("MULTIPLE_ROOTS", graph, AI_WORLD, human=True)


def test_new_root_beside_a_visible_proposed_intent_is_refused() -> None:
    proposed_root = visibility(visible("INTENT-p", K.INTENT, authority=Authority.PROPOSED))
    refused("MULTIPLE_ROOTS", result(node(K.INTENT, "i1")), proposed_root, human=True)


# ---------------------------------------------------------------- assumptions (§6)


def test_assumption_without_affects_is_refused() -> None:
    refused("ASSUMPTION_WITHOUT_AFFECTS", spine(node(K.ASSUMPTION, "a")), EMPTY, human=True)


def test_assumption_affecting_a_new_node_is_accepted() -> None:
    accepted(spine(node(K.ASSUMPTION, "a"), relations=(edge("a", A, "req"),)), EMPTY, human=True)


def test_assumption_affecting_an_existing_node_needs_no_basis_even_from_a_model() -> None:
    graph = result(node(K.ASSUMPTION, "a"), relations=(edge("a", A, e("REQ-fresh")),))
    accepted(graph, AI_WORLD, human=False)


# ------------------------------------------------------------------ grounding (§11)


def test_human_goal_may_be_a_direct_choice() -> None:
    accepted(spine(), EMPTY, human=True)


@pytest.mark.parametrize(
    "facet", [ConstraintFacet.EVIDENCE_BOUND, ConstraintFacet.EXTERNAL_MANDATE]
)
def test_human_evidence_facet_constraint_without_basis_is_refused(facet: ConstraintFacet) -> None:
    graph = spine(node(K.CONSTRAINT, "c", facet=facet), relations=(edge("c", S, "intent"),))
    refused("UNGROUNDED_NODE", graph, EMPTY, human=True)


@pytest.mark.parametrize(
    "facet", [ConstraintFacet.EVIDENCE_BOUND, ConstraintFacet.EXTERNAL_MANDATE]
)
def test_human_evidence_facet_constraint_on_a_claim_is_accepted(facet: ConstraintFacet) -> None:
    graph = spine(
        node(K.CONSTRAINT, "c", facet=facet),
        relations=(edge("c", S, "intent"), edge("c", D, b("CLAIM-1"))),
    )
    accepted(graph, EMPTY, human=True)


def test_evidence_facet_is_not_satisfied_by_a_decision_alone() -> None:
    graph = result(
        node(K.CONSTRAINT, "c", facet=ConstraintFacet.EVIDENCE_BOUND),
        relations=(edge("c", S, e("GOAL-root")), edge("c", D, e("DEC-x"))),
    )
    refused("UNGROUNDED_NODE", graph, AI_WORLD, human=True)


def test_human_project_boundary_constraint_may_be_direct() -> None:
    graph = spine(
        node(K.CONSTRAINT, "c", facet=ConstraintFacet.PROJECT_BOUNDARY),
        relations=(edge("c", S, "intent"),),
    )
    accepted(graph, EMPTY, human=True)


@pytest.mark.parametrize(
    "kind", [K.GOAL, K.OUTCOME, K.NON_GOAL, K.PREFERENCE, K.DECISION, K.REQUIREMENT, K.CONSTRAINT]
)
def test_model_may_not_originate_an_unevidenced_project_choice(kind: SemanticKind) -> None:
    graph = result(node(kind, "n"), relations=(edge("n", S, e("GOAL-root")),))
    refused("UNGROUNDED_NODE", graph, AI_WORLD, human=False)


def test_model_intent_needs_evidence_too() -> None:
    no_root = visibility()
    refused("UNGROUNDED_NODE", result(node(K.INTENT, "i")), no_root, human=False)
    accepted(
        result(node(K.INTENT, "i"), relations=(edge("i", D, b("CLAIM-1")),)), no_root, human=False
    )


def test_model_requirement_on_an_existing_decision_is_grounded() -> None:
    graph = ai_req("req", edge("req", S, e("GOAL-root")), edge("req", D, e("DEC-x")))
    accepted(graph, AI_WORLD, human=False)


def test_model_requirement_through_a_local_goal_to_a_claim_is_grounded() -> None:
    graph = result(
        node(K.GOAL, "goal"),
        node(K.REQUIREMENT, "req"),
        relations=(
            edge("goal", S, e("INTENT-root")),
            edge("goal", D, b("CLAIM-1")),
            edge("req", S, "goal"),
            edge("req", D, "goal"),
        ),
    )
    accepted(graph, AI_WORLD, human=False)


def test_model_requirement_through_an_existing_grounded_goal_is_grounded() -> None:
    graph = ai_req("req", edge("req", S, e("GOAL-root")), edge("req", D, e("GOAL-grounded")))
    accepted(graph, AI_WORLD, human=False)


def test_existing_intermediate_with_no_grounding_does_not_ground_a_model_node() -> None:
    graph = ai_req("req", edge("req", S, e("GOAL-root")), edge("req", D, e("GOAL-root")))
    refused("UNGROUNDED_NODE", graph, AI_WORLD, human=False)


def test_r101_a_same_batch_model_decision_never_grounds_another_new_node() -> None:
    # "a-req" sorts before "z-dec", so the requirement is judged first: it must be refused
    # on its own account, not merely because the decision it leans on is itself ungrounded.
    graph = result(
        node(K.REQUIREMENT, "a-req"),
        node(K.DECISION, "z-dec"),
        relations=(
            edge("a-req", S, e("GOAL-root")),
            edge("a-req", D, "z-dec"),
            edge("z-dec", S, e("GOAL-root")),
        ),
    )
    message = refused("UNGROUNDED_NODE", graph, AI_WORLD, human=False)
    assert "'a-req'" in message


def test_r101_a_grounded_local_decision_is_only_an_intermediate() -> None:
    graph = result(
        node(K.REQUIREMENT, "a-req"),
        node(K.DECISION, "z-dec"),
        relations=(
            edge("a-req", S, e("GOAL-root")),
            edge("a-req", D, "z-dec"),
            edge("z-dec", S, e("GOAL-root")),
            edge("z-dec", D, b("CLAIM-1")),
        ),
    )
    accepted(graph, AI_WORLD, human=False)


def test_serves_never_counts_as_grounding() -> None:
    graph = result(
        node(K.GOAL, "goal"),
        node(K.REQUIREMENT, "req"),
        relations=(
            edge("goal", S, e("INTENT-root")),
            edge("goal", D, b("CLAIM-1")),
            edge("req", S, "goal"),
        ),
    )
    message = refused("UNGROUNDED_NODE", graph, AI_WORLD, human=False)
    assert "'req'" in message


# ------------------------------------------------------------- replacement (§17)


def _replacing(target: str, local_id: str = "req2") -> GraphNodeProposal:
    return node(
        K.REQUIREMENT,
        local_id,
        disposition=GraphNodeDisposition.REPLACES_STALE,
        replaces=e(target),
    )


def test_replacing_a_visible_stale_same_kind_target_is_accepted() -> None:
    graph = result(_replacing("REQ-stale"), relations=(edge("req2", S, e("GOAL-root")),))
    accepted(graph, AI_WORLD, human=True)


def test_replacing_an_invisible_target_is_refused() -> None:
    graph = result(_replacing("REQ-hidden"), relations=(edge("req2", S, e("GOAL-root")),))
    refused("INVISIBLE_EXISTING_REF", graph, AI_WORLD, human=True)


def test_replacing_a_target_that_is_not_stale_is_refused() -> None:
    graph = result(_replacing("REQ-fresh"), relations=(edge("req2", S, e("GOAL-root")),))
    refused("REPLACEMENT_TARGET_NOT_STALE", graph, AI_WORLD, human=True)


def test_replacing_a_different_kind_is_refused() -> None:
    graph = result(
        node(
            K.GOAL, "g2", disposition=GraphNodeDisposition.REPLACES_STALE, replaces=e("REQ-stale")
        ),
        relations=(edge("g2", S, e("INTENT-root")),),
    )
    refused("REPLACEMENT_KIND_MISMATCH", graph, AI_WORLD, human=True)


def test_replacing_a_dead_target_is_refused() -> None:
    dead = visibility(
        visible("INTENT-root", K.INTENT),
        visible("GOAL-root", K.GOAL, relations=((S, "INTENT-root"),)),
        visible(
            "REQ-dead",
            K.REQUIREMENT,
            is_current=False,
            is_stale=True,
            authority=Authority.SUPERSEDED,
        ),
    )
    graph = result(_replacing("REQ-dead"), relations=(edge("req2", S, e("GOAL-root")),))
    refused("EXISTING_NOT_CURRENT", graph, dead, human=True)


def test_one_target_may_not_be_replaced_twice() -> None:
    graph = result(
        _replacing("REQ-stale", "req2"),
        _replacing("REQ-stale", "req3"),
        relations=(edge("req2", S, e("GOAL-root")), edge("req3", S, e("GOAL-root"))),
    )
    refused("DOUBLE_REPLACEMENT", graph, AI_WORLD, human=True)


def test_a_relation_to_a_retiring_target_is_refused() -> None:
    graph = result(
        _replacing("REQ-stale"),
        node(K.ASSUMPTION, "a"),
        relations=(edge("req2", S, e("GOAL-root")), edge("a", A, e("REQ-stale"))),
    )
    refused("RETIRING_TARGET_REFERENCED", graph, AI_WORLD, human=True)


def test_a_gap_anchored_to_a_retiring_target_is_refused() -> None:
    graph = result(
        _replacing("REQ-stale"),
        relations=(edge("req2", S, e("GOAL-root")),),
        gaps=(gap(anchors=(e("REQ-stale"),)),),
    )
    refused("RETIRING_TARGET_REFERENCED", graph, AI_WORLD, human=True)


# --------------------------------------------------------- partial graphs (R104)


def test_partial_graph_with_gaps_is_legal() -> None:
    graph = spine(
        node(K.ASSUMPTION, "a"),
        relations=(edge("a", A, "req"),),
        gaps=(
            gap("g1", kind=GapKind.UNSUPPORTED_ASSUMPTION, anchors=(local("a"),)),
            gap("g2", kind=GapKind.MISSING_INFORMATION, anchors=(local("goal"),)),
        ),
    )
    accepted(graph, EMPTY, human=True)


def test_r104_a_gap_never_substitutes_for_a_missing_node() -> None:
    # The Goal the requirement would serve was left unresolved and only described by a gap.
    graph = result(
        node(K.INTENT, "intent"),
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, "goal"),),
        gaps=(gap("goal-gap", kind=GapKind.MISSING_INFORMATION),),
    )
    refused("UNRESOLVED_LOCAL_REF", graph, EMPTY, human=True)


def test_r104_no_relevance_path_through_an_unresolved_region() -> None:
    graph = result(
        node(K.INTENT, "intent"),
        node(K.REQUIREMENT, "req"),
        gaps=(gap("g1", kind=GapKind.MISSING_INFORMATION, anchors=(local("req"),)),),
    )
    refused("NO_RELEVANCE", graph, EMPTY, human=True)


def test_r104_no_basis_path_through_an_unresolved_region() -> None:
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-root")), edge("req", D, "omitted-goal")),
        gaps=(gap("g1", kind=GapKind.MISSING_INFORMATION),),
    )
    refused("UNRESOLVED_LOCAL_REF", graph, AI_WORLD, human=False)


def test_gap_only_result_validates() -> None:
    accepted(result(gaps=(gap(anchors=(e("GOAL-root"),)),)), AI_WORLD, human=False)


# ------------------------------------------------------------- visibility surface


def test_visibility_rejects_duplicate_objects_and_bad_roots() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        visibility(visible("GOAL-1", K.GOAL), visible("GOAL-1", K.GOAL))
    with pytest.raises(ValueError, match="root"):
        visibility(visible("GOAL-1", K.GOAL), roots=("GOAL-1",))
    with pytest.raises(ValueError, match="IE3"):
        visibility(visible("CLAIM-obj", K.CLAIM))
    with pytest.raises(ValueError, match="both"):
        visibility(visible("GOAL-1", K.GOAL), basis=("GOAL-1",))


def test_visibility_from_state_shows_current_applicable_ie3_objects_only() -> None:
    world = World()
    claim = world.claim("J-claim", authority=Authority.CANONICAL)
    root = world.admit_root()
    world.legacy(
        goal("GOAL-live", scope=(SCOPE,), relations=(rel(S, root),)),
        goal("GOAL-other-scope", scope=("elsewhere",)),
        goal("GOAL-dead", authority=Authority.SUPERSEDED),
        intent("INTENT-project-wide", scope=(), authority=Authority.PROPOSED),
    )
    state = replay(world.governor.project_id, world.store.load(world.governor.project_id))
    vis = graph_visibility(state, SCOPE, basis_claim_ids=(claim,))
    ids = {o.object_id for o in vis.objects}
    assert {"GOAL-live", root, "INTENT-project-wide"} <= ids
    assert "GOAL-other-scope" not in ids
    assert "GOAL-dead" not in ids
    assert all(o.kind is not K.AUTHORITY_RECORD for o in vis.objects)
    assert vis.root_intent_ids == (root,)
    assert vis.basis_claim_ids == frozenset({claim})
    assert vis.run_scope == SCOPE


def test_visibility_from_state_refuses_an_unknown_basis_claim() -> None:
    state = replay("PROJ-IE21", InMemoryEventStore().load("PROJ-IE21"))
    with pytest.raises(ValueError, match="CLAIM-nope"):
        graph_visibility(state, SCOPE, basis_claim_ids=("CLAIM-nope",))

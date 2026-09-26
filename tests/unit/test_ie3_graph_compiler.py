"""IE3 Slice 1 — deterministic compilation and hypothetical post-graph IE2 validation.

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§8, §13, §14, §16,
§17, §25, §26; R100-R104; Q1, Q2, Q5). The compiler writes nothing: these tests prove what it
would hand to a later durable transition, and that the unchanged IE2 laws accept or refuse it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from foundry.application.replay import replay
from foundry.domain.basis import UnlawfulBasisError
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    RelationType,
    RiskLevel,
    SourceKind,
)
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import (
    OBJECT_ID_PREFIX,
    IntentGraphGap,
    IntentGraphIdentity,
    IntentGraphSynthesisResult,
    MissingNeed,
)
from foundry.domain.intent_graph_compiler import (
    CompiledIntentGraph,
    IntentGraphCompilationError,
    NodeAssignment,
    RetirementPlanEntry,
    assert_compiled_graph_lawful,
    compile_intent_graph,
    hypothetical_state,
)
from foundry.domain.intent_graph_validation import (
    GraphVisibility,
    IntentGraphValidationError,
    graph_visibility,
)
from foundry.domain.intent_synthesis import SynthesisIdentity, SynthesisOrigin
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.relation_legality import RelationLegalityError
from foundry.domain.relevance import IrrelevantObjectError
from foundry.domain.semantic import (
    Assumption,
    Constraint,
    ConstraintFacet,
    Goal,
    Intent,
    NonGoal,
    Outcome,
    Preference,
    ProjectDecision,
    Requirement,
    SemanticKind,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.domain.state import IntentState
from tests.unit._ie3_fixtures import (
    ALICE,
    DECIDED_AT,
    DECISION_EVENT_ID,
    HUMAN,
    IDENTITY,
    MODEL,
    PROJECT,
    RUN,
    SCOPE,
    assign,
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
from tests.unit._ie21_fixtures import goal, rel, requirement
from tests.unit._ie22b_fixtures import ROOT_ID, World

K = SemanticKind
D = RelationType.DERIVED_FROM
S = RelationType.SERVES
A = RelationType.AFFECTS
X = RelationType.EXCLUDES
EMPTY = visibility()
RESEARCHER = ReasonerFingerprint(provider="research", model="web-agent", policy_version="p1")


def compile_(
    graph: IntentGraphSynthesisResult,
    vis: GraphVisibility = EMPTY,
    *,
    author: ReasonerFingerprint = HUMAN,
    origin: SynthesisOrigin = SynthesisOrigin.HUMAN_STATED,
    authority: Authority = Authority.CANONICAL,
    assignments: dict[str, NodeAssignment] | None = None,
    identity: IntentGraphIdentity = IDENTITY,
) -> CompiledIntentGraph:
    return compile_intent_graph(
        graph,
        vis,
        identity=identity,
        author=author,
        decided_at=DECIDED_AT,
        decision_event_id=DECISION_EVENT_ID,
        assignments=assignments
        if assignments is not None
        else assign(graph, origin=origin, authority=authority),
    )


def refused(code: str, **kwargs: Any) -> None:
    graph = kwargs.pop("graph")
    with pytest.raises(IntentGraphCompilationError) as caught:
        compile_(graph, **kwargs)
    assert caught.value.code == code, str(caught.value)


def _digest(*parts: str) -> str:
    """An independent second body for the digest, so the golden test checks something."""
    encoded = json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


# Every kind in one human graph, each lawfully placed.
ALL_KINDS = result(
    node(K.INTENT, "intent"),
    node(K.GOAL, "goal"),
    node(K.OUTCOME, "outcome"),
    node(K.REQUIREMENT, "req"),
    node(K.CONSTRAINT, "con", facet=ConstraintFacet.EVIDENCE_BOUND),
    node(K.NON_GOAL, "nongoal"),
    node(K.PREFERENCE, "pref"),
    node(K.DECISION, "dec"),
    node(K.ASSUMPTION, "asm", proposed_risk_level=RiskLevel.LOW),
    relations=(
        edge("goal", S, "intent"),
        edge("outcome", S, "goal"),
        edge("req", S, "goal"),
        edge("req", D, b("CLAIM-1")),
        edge("con", S, "intent"),
        edge("con", D, b("CLAIM-1")),
        edge("nongoal", S, "goal"),
        edge("nongoal", X, "outcome"),
        edge("pref", S, "goal"),
        edge("dec", S, "goal"),
        edge("asm", A, "req"),
    ),
    gaps=(
        gap(
            "g-assume",
            kind=GapKind.UNSUPPORTED_ASSUMPTION,
            anchors=(local("asm"), b("CLAIM-1")),
            missing_need=MissingNeed.EXTERNAL_FACT,
            confidence=0.4,
        ),
    ),
)

AI_WORLD = visibility(
    visible("INTENT-root", K.INTENT),
    visible("GOAL-root", K.GOAL, relations=((S, "INTENT-root"),)),
    visible("REQ-stale", K.REQUIREMENT, is_stale=True, relations=((S, "GOAL-root"),)),
    visible(
        "REQ-stale-proposed",
        K.REQUIREMENT,
        authority=Authority.PROPOSED,
        is_stale=True,
        relations=((S, "GOAL-root"),),
    ),
    visible("REQ-fresh", K.REQUIREMENT, relations=((S, "GOAL-root"),)),
)


def by_local(compiled: CompiledIntentGraph, local_id: str) -> Any:
    object_id = dict(compiled.local_to_object_id)[local_id]
    return next(o for o in compiled.objects if o.id == object_id)


# ------------------------------------------------------------------ identity (§14)


def test_identity_golden_derivation() -> None:
    graph_instance = "GSY-" + _digest("ie3.graph", PROJECT, RUN)
    assert IDENTITY.graph_instance_id == graph_instance
    assert IDENTITY.node_instance_id("goal") == "GSN-" + _digest("ie3.node", graph_instance, "goal")
    assert IDENTITY.object_id(K.GOAL, "goal") == "GOAL-" + _digest(
        "ie3.object", graph_instance, "goal", "GOAL"
    )
    assert IDENTITY.gap_id("g1") == "GAP-" + _digest("ie3.gap", graph_instance, "g1")
    assert IDENTITY.event_id("DECIDED") == "EVT-" + _digest("ie3.event", graph_instance, "DECIDED")


def test_object_id_prefixes_are_the_approved_conventions() -> None:
    assert OBJECT_ID_PREFIX == {
        K.INTENT: "INT",
        K.GOAL: "GOAL",
        K.OUTCOME: "OUT",
        K.REQUIREMENT: "REQ",
        K.CONSTRAINT: "CON",
        K.NON_GOAL: "NG",
        K.PREFERENCE: "PREF",
        K.DECISION: "DEC",
        K.ASSUMPTION: "ASM",
    }


def test_full_width_digest() -> None:
    suffix = IDENTITY.object_id(K.GOAL, "goal").split("-", 1)[1]
    assert len(suffix) == 64
    int(suffix, 16)


def _suffix(object_id: str) -> str:
    return object_id.split("-", 1)[1]


def test_ids_are_sensitive_to_project_run_local_id_and_kind() -> None:
    base = IDENTITY.object_id(K.GOAL, "goal")
    other_run = IntentGraphIdentity(project_id=PROJECT, synthesis_run_id="RUN-2")
    other_project = IntentGraphIdentity(project_id="PROJ-other", synthesis_run_id=RUN)
    assert other_run.object_id(K.GOAL, "goal") != base
    assert other_project.object_id(K.GOAL, "goal") != base
    assert IDENTITY.object_id(K.GOAL, "goal-2") != base
    # Kind must reach the DIGEST, not merely the conventional prefix.
    assert _suffix(IDENTITY.object_id(K.OUTCOME, "goal")) != _suffix(base)
    assert other_run.graph_instance_id != IDENTITY.graph_instance_id
    assert other_project.graph_instance_id != IDENTITY.graph_instance_id


def test_same_inputs_same_ids() -> None:
    again = IntentGraphIdentity(project_id=PROJECT, synthesis_run_id=RUN)
    assert again.object_id(K.GOAL, "goal") == IDENTITY.object_id(K.GOAL, "goal")
    assert again == IDENTITY


def test_ie3_tags_are_separate_from_slice_1_identity() -> None:
    slice1 = SynthesisIdentity(project_id=PROJECT, synthesis_run_id=RUN, model_proposal_id="req")
    ie3_ids = {
        IDENTITY.graph_instance_id,
        IDENTITY.node_instance_id("req"),
        IDENTITY.object_id(K.REQUIREMENT, "req"),
        IDENTITY.event_id("DECIDED"),
    }
    slice1_ids = {slice1.proposal_instance_id, slice1.object_id("REQ"), slice1.event_id("DECIDED")}
    assert ie3_ids.isdisjoint(slice1_ids)
    assert {_suffix(i) for i in ie3_ids}.isdisjoint({_suffix(i) for i in slice1_ids})


def test_identity_requires_runtime_ids() -> None:
    with pytest.raises(ValueError):
        IntentGraphIdentity(project_id="", synthesis_run_id=RUN)
    with pytest.raises(ValueError):
        IntentGraphIdentity(project_id=PROJECT, synthesis_run_id="")


# ------------------------------------------------------------- determinism (§16)


def test_compilation_is_deterministic() -> None:
    assert compile_(ALL_KINDS) == compile_(ALL_KINDS)


def test_compilation_is_independent_of_input_order() -> None:
    shuffled = IntentGraphSynthesisResult(
        nodes=tuple(reversed(ALL_KINDS.nodes)),
        relations=tuple(reversed(ALL_KINDS.relations)),
        gaps=tuple(reversed(ALL_KINDS.gaps)),
    )
    assert compile_(shuffled) == compile_(ALL_KINDS)


def test_compiled_collections_are_canonically_ordered() -> None:
    compiled = compile_(ALL_KINDS)
    ids = [o.id for o in compiled.objects]
    assert ids == sorted(ids)
    assert list(compiled.local_to_object_id) == sorted(compiled.local_to_object_id)
    for obj in compiled.objects:
        pairs = [(r.relation_type.value, r.target_id) for r in obj.relations]
        assert pairs == sorted(pairs)


def test_no_raw_local_id_becomes_a_durable_id() -> None:
    graph = result(
        node(K.INTENT, "intent-alpha"),
        node(K.GOAL, "goal-alpha"),
        relations=(edge("goal-alpha", S, "intent-alpha"),),
        gaps=(gap("gap-alpha"),),
    )
    compiled = compile_(graph)
    durable = [o.id for o in compiled.objects] + [g.id for g in compiled.gaps]
    for text in ("intent-alpha", "goal-alpha", "gap-alpha"):
        assert all(text not in object_id for object_id in durable)


def test_every_node_maps_to_its_identity_derived_id() -> None:
    compiled = compile_(ALL_KINDS)
    for proposal in ALL_KINDS.nodes:
        local_id = proposal.local_id.local_id
        assert dict(compiled.local_to_object_id)[local_id] == IDENTITY.object_id(
            proposal.kind, local_id
        )
    assert len(compiled.objects) == len(ALL_KINDS.nodes)


# -------------------------------------------------------------- ref resolution


def test_refs_resolve_to_durable_existing_and_claim_ids() -> None:
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-root")), edge("req", D, b("CLAIM-1"))),
    )
    compiled = compile_(graph, AI_WORLD)
    req = by_local(compiled, "req")
    assert sorted((r.relation_type, r.target_id) for r in req.relations) == [
        (D, "CLAIM-1"),
        (S, "GOAL-root"),
    ]


def test_local_refs_resolve_to_new_durable_ids() -> None:
    compiled = compile_(ALL_KINDS)
    goal_id = IDENTITY.object_id(K.GOAL, "goal")
    req = by_local(compiled, "req")
    assert (S, goal_id) in {(r.relation_type, r.target_id) for r in req.relations}
    asm = by_local(compiled, "asm")
    assert [(r.relation_type, r.target_id) for r in asm.relations] == [
        (A, IDENTITY.object_id(K.REQUIREMENT, "req"))
    ]


# ---------------------------------------------------------- runtime-owned fields (§8)


def test_every_kind_compiles_to_its_real_domain_class() -> None:
    compiled = compile_(ALL_KINDS)
    expected = {
        "intent": Intent,
        "goal": Goal,
        "outcome": Outcome,
        "req": Requirement,
        "con": Constraint,
        "nongoal": NonGoal,
        "pref": Preference,
        "dec": ProjectDecision,
        "asm": Assumption,
    }
    for local_id, cls in expected.items():
        assert type(by_local(compiled, local_id)) is cls


def test_runtime_owned_fields_for_a_human_author() -> None:
    compiled = compile_(ALL_KINDS)
    for obj in compiled.objects:
        assert obj.project_id == PROJECT
        assert obj.created_at == DECIDED_AT
        assert obj.revision == 1
        assert obj.lifecycle is LifecycleStatus.ACTIVE
        assert obj.authority is Authority.CANONICAL
        assert obj.provenance.source_kind is SourceKind.HUMAN
        assert obj.provenance.source_ref == ALICE
        assert obj.provenance.source_event_ids == (DECISION_EVENT_ID,)


def test_runtime_owned_fields_for_a_model_author() -> None:
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-root")), edge("req", D, b("CLAIM-1"))),
    )
    compiled = compile_(
        graph,
        AI_WORLD,
        author=MODEL,
        origin=SynthesisOrigin.AI_INFERRED,
        authority=Authority.PROPOSED,
    )
    req = by_local(compiled, "req")
    assert req.authority is Authority.PROPOSED
    # Never RESEARCH, even for research-derived work: the author is a system, not the basis.
    assert req.provenance.source_kind is SourceKind.SYSTEM
    assert req.provenance.source_ref == RUN
    assert req.provenance.source_event_ids == (DECISION_EVENT_ID,)


def test_kind_specific_content_is_carried_exactly() -> None:
    compiled = compile_(ALL_KINDS)
    assert by_local(compiled, "intent").mission == "Refunds are predictable."
    assert by_local(compiled, "con").facet is ConstraintFacet.EVIDENCE_BOUND
    assert by_local(compiled, "dec").rationale == "Operational familiarity."
    assert by_local(compiled, "goal").statement == "Refunds settle quickly."


def test_requirement_runtime_pins_inherit_slice_1() -> None:
    req = by_local(compile_(ALL_KINDS), "req")
    assert req.materiality is Materiality.LOW
    assert req.requires_metric is False
    assert req.requires_verification is False
    assert req.metric_exempt_reason is None
    assert req.verification_exempt_reason is None


def test_q1_confidence_is_carried_exactly() -> None:
    graph = result(
        node(K.INTENT, "intent"),
        node(K.GOAL, "g-none"),
        node(K.GOAL, "g-zero", confidence=0.0),
        node(K.GOAL, "g-some", confidence=0.42),
        relations=(
            edge("g-none", S, "intent"),
            edge("g-zero", S, "intent"),
            edge("g-some", S, "intent"),
        ),
    )
    compiled = compile_(graph)
    assert by_local(compiled, "intent").confidence is None
    assert by_local(compiled, "g-none").confidence is None
    assert by_local(compiled, "g-zero").confidence == 0.0
    assert by_local(compiled, "g-some").confidence == 0.42


def test_q2_every_node_scope_is_the_run_scope() -> None:
    compiled = compile_(ALL_KINDS, visibility(run_scope="checkout"))
    assert {tuple(o.scope) for o in compiled.objects} == {("checkout",)}
    assert {tuple(g.scope) for g in compiled.gaps} == {("checkout",)}


def test_q2_run_scope_wins_over_the_basis_claim_address_scope() -> None:
    world = World()
    claim = world.claim("J-claim", authority=Authority.CANONICAL)
    state = replay(PROJECT, world.store.load(PROJECT))
    address_scope = state.semantic.addresses[state.semantic.claims[claim].address_id].scope
    assert tuple(address_scope) == (SCOPE,)
    graph = result(
        node(K.INTENT, "intent"),
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, "intent"), edge("req", D, b(claim))),
    )
    compiled = compile_(graph, graph_visibility(state, "checkout", basis_claim_ids=(claim,)))
    assert tuple(by_local(compiled, "req").scope) == ("checkout",)


def test_q2_scope_does_not_follow_referenced_existing_objects() -> None:
    wide = visibility(
        visible("INTENT-root", K.INTENT, scope=()),
        visible("GOAL-wide", K.GOAL, scope=(), relations=((S, "INTENT-root"),)),
    )
    graph = result(node(K.REQUIREMENT, "req"), relations=(edge("req", S, e("GOAL-wide")),))
    assert tuple(by_local(compile_(graph, wide), "req").scope) == (SCOPE,)


# ------------------------------------------------------------ Assumption risk (Q5)


def _ai_assumption(proposed: RiskLevel | None) -> IntentGraphSynthesisResult:
    return result(
        node(K.ASSUMPTION, "asm", proposed_risk_level=proposed),
        relations=(edge("asm", A, e("REQ-fresh")),),
    )


@pytest.mark.parametrize("proposed", [None, *RiskLevel], ids=str)
@pytest.mark.parametrize(
    ("author", "origin"),
    [(MODEL, SynthesisOrigin.AI_INFERRED), (RESEARCHER, SynthesisOrigin.RESEARCH_DERIVED)],
    ids=["ai", "research"],
)
def test_q5_non_human_assumptions_are_always_high(
    proposed: RiskLevel | None, author: ReasonerFingerprint, origin: SynthesisOrigin
) -> None:
    compiled = compile_(
        _ai_assumption(proposed),
        AI_WORLD,
        author=author,
        origin=origin,
        authority=Authority.PROPOSED,
    )
    assert by_local(compiled, "asm").risk_level is RiskLevel.HIGH


@pytest.mark.parametrize("stated", list(RiskLevel), ids=str)
def test_q5_an_authenticated_human_risk_is_preserved(stated: RiskLevel) -> None:
    compiled = compile_(_ai_assumption(stated), AI_WORLD)
    assert by_local(compiled, "asm").risk_level is stated


def test_q5_a_silent_human_gets_high() -> None:
    compiled = compile_(_ai_assumption(None), AI_WORLD)
    assert by_local(compiled, "asm").risk_level is RiskLevel.HIGH


# ------------------------------------------------------------------- gaps (§19)


def test_gaps_compile_to_durable_blocking_synthesis_gaps() -> None:
    compiled = compile_(ALL_KINDS)
    (compiled_gap,) = compiled.gaps
    assert isinstance(compiled_gap, IntentGraphGap)
    assert isinstance(compiled_gap, IntentSynthesisGap)
    assert compiled_gap.id == IDENTITY.gap_id("g-assume")
    assert compiled_gap.project_id == PROJECT
    assert compiled_gap.kind is GapKind.UNSUPPORTED_ASSUMPTION
    assert compiled_gap.blocking is True
    assert compiled_gap.materiality is None
    assert compiled_gap.risk is None
    assert compiled_gap.scope == (SCOPE,)
    assert compiled_gap.affected_object_ids == (IDENTITY.object_id(K.ASSUMPTION, "asm"),)
    assert compiled_gap.affected_claim_ids == ("CLAIM-1",)
    assert compiled_gap.missing_need is MissingNeed.EXTERNAL_FACT
    assert compiled_gap.confidence == 0.4
    assert compiled_gap.model_gap_proposal_id == "g-assume"


# -------------------------------------------------------------- authority (§13)


def test_assigned_authority_is_carried_exactly_per_node() -> None:
    graph = result(
        node(K.INTENT, "intent"),
        node(K.GOAL, "goal"),
        relations=(edge("goal", S, "intent"),),
    )
    compiled = compile_(
        graph,
        assignments={
            "intent": NodeAssignment(
                origin=SynthesisOrigin.HUMAN_STATED, authority=Authority.CANONICAL
            ),
            "goal": NodeAssignment(
                origin=SynthesisOrigin.HUMAN_STATED, authority=Authority.PROPOSED
            ),
        },
    )
    assert by_local(compiled, "intent").authority is Authority.CANONICAL
    assert by_local(compiled, "goal").authority is Authority.PROPOSED


def test_a_missing_assignment_is_refused() -> None:
    assignments = assign(ALL_KINDS)
    del assignments["req"]
    refused("ASSIGNMENT_MISMATCH", graph=ALL_KINDS, assignments=assignments)


def test_an_extra_assignment_is_refused() -> None:
    assignments = assign(ALL_KINDS)
    assignments["ghost"] = NodeAssignment(
        origin=SynthesisOrigin.HUMAN_STATED, authority=Authority.CANONICAL
    )
    refused("ASSIGNMENT_MISMATCH", graph=ALL_KINDS, assignments=assignments)


@pytest.mark.parametrize(
    ("author", "origin"),
    [
        (MODEL, SynthesisOrigin.HUMAN_STATED),
        (HUMAN, SynthesisOrigin.AI_INFERRED),
        (HUMAN, SynthesisOrigin.RESEARCH_DERIVED),
    ],
    ids=["model-claims-human", "human-as-ai", "human-as-research"],
)
def test_origin_must_follow_the_author(
    author: ReasonerFingerprint, origin: SynthesisOrigin
) -> None:
    graph = _ai_assumption(None)
    refused(
        "ORIGIN_AUTHOR_MISMATCH",
        graph=graph,
        vis=AI_WORLD,
        author=author,
        origin=origin,
        authority=Authority.PROPOSED,
    )


def test_deterministic_normalization_is_unsupported() -> None:
    refused(
        "UNSUPPORTED_ORIGIN",
        graph=_ai_assumption(None),
        vis=AI_WORLD,
        author=MODEL,
        origin=SynthesisOrigin.DETERMINISTIC_NORMALIZATION,
        authority=Authority.PROPOSED,
    )


@pytest.mark.parametrize(
    ("author", "origin"),
    [(MODEL, SynthesisOrigin.AI_INFERRED), (RESEARCHER, SynthesisOrigin.RESEARCH_DERIVED)],
    ids=["ai", "research"],
)
def test_non_human_canonical_assignment_is_refused(
    author: ReasonerFingerprint, origin: SynthesisOrigin
) -> None:
    refused(
        "AUTHORITY_INVENTION",
        graph=_ai_assumption(None),
        vis=AI_WORLD,
        author=author,
        origin=origin,
        authority=Authority.CANONICAL,
    )


@pytest.mark.parametrize(
    "authority",
    [a for a in Authority if a not in (Authority.CANONICAL, Authority.PROPOSED)],
    ids=str,
)
def test_only_canonical_or_proposed_may_be_assigned(authority: Authority) -> None:
    refused("INVALID_ASSIGNED_AUTHORITY", graph=ALL_KINDS, authority=authority)


def test_compilation_validates_the_graph_first() -> None:
    graph = result(node(K.INTENT, "intent"), node(K.REQUIREMENT, "req"))
    with pytest.raises(IntentGraphValidationError, match="NO_RELEVANCE"):
        compile_(graph)


def test_compilation_validates_with_the_authors_grounding_policy() -> None:
    graph = result(node(K.GOAL, "goal"), relations=(edge("goal", S, e("INTENT-root")),))
    compile_(graph, AI_WORLD)  # a human may choose a Goal directly
    with pytest.raises(IntentGraphValidationError, match="UNGROUNDED_NODE"):
        compile_(
            graph,
            AI_WORLD,
            author=MODEL,
            origin=SynthesisOrigin.AI_INFERRED,
            authority=Authority.PROPOSED,
        )


# ---------------------------------------------------------- retirement plan (§17)


def _replace(target: str) -> IntentGraphSynthesisResult:
    return result(
        node(K.REQUIREMENT, "req2", disposition="REPLACES_STALE", replaces=e(target)),
        relations=(edge("req2", S, e("GOAL-root")), edge("req2", D, b("CLAIM-1"))),
    )


def test_retirement_plan_for_a_lawful_replacement() -> None:
    compiled = compile_(_replace("REQ-stale"), AI_WORLD)
    assert compiled.retirements == (
        RetirementPlanEntry(
            retired_object_id="REQ-stale",
            replaced_by_object_id=IDENTITY.object_id(K.REQUIREMENT, "req2"),
            node_instance_id=IDENTITY.node_instance_id("req2"),
        ),
    )


def test_new_nodes_plan_no_retirement() -> None:
    assert compile_(ALL_KINDS).retirements == ()


def test_c11_a_canonical_target_needs_a_canonical_replacement() -> None:
    refused(
        "CANONICAL_REPLACEMENT_REQUIRED",
        graph=_replace("REQ-stale"),
        vis=AI_WORLD,
        author=MODEL,
        origin=SynthesisOrigin.AI_INFERRED,
        authority=Authority.PROPOSED,
    )


def test_c11_a_proposed_target_may_be_replaced_by_proposed_intent() -> None:
    compiled = compile_(
        _replace("REQ-stale-proposed"),
        AI_WORLD,
        author=MODEL,
        origin=SynthesisOrigin.AI_INFERRED,
        authority=Authority.PROPOSED,
    )
    assert compiled.retirements[0].retired_object_id == "REQ-stale-proposed"


@pytest.mark.parametrize("target_scope", [(), ("elsewhere",), (SCOPE, "elsewhere")], ids=str)
def test_replacement_scope_must_cover_the_target(target_scope: tuple[str, ...]) -> None:
    vis = visibility(
        visible("INTENT-root", K.INTENT),
        visible("GOAL-root", K.GOAL, relations=((S, "INTENT-root"),)),
        visible("REQ-stale", K.REQUIREMENT, is_stale=True, scope=target_scope),
    )
    refused("REPLACEMENT_SCOPE_NOT_COVERED", graph=_replace("REQ-stale"), vis=vis)


# ------------------------------------------------------- hypothetical state (§25)


def _world_with_claim(claim_authority: Authority) -> tuple[World, str, IntentState]:
    world = World()
    claim = world.claim("J-basis", authority=claim_authority)
    return world, claim, replay(PROJECT, world.store.load(PROJECT))


def _canonical_spine(claim: str) -> IntentGraphSynthesisResult:
    return result(
        node(K.INTENT, "intent"),
        node(K.GOAL, "goal"),
        node(K.REQUIREMENT, "req"),
        node(K.ASSUMPTION, "asm", proposed_risk_level=RiskLevel.LOW),
        relations=(
            edge("goal", S, "intent"),
            edge("req", S, "goal"),
            edge("req", D, b(claim)),
            edge("asm", A, "req"),
        ),
    )


def test_canonical_human_graph_passes_the_unchanged_ie2_laws() -> None:
    _, claim, state = _world_with_claim(Authority.CANONICAL)
    compiled = compile_(
        _canonical_spine(claim), graph_visibility(state, SCOPE, basis_claim_ids=(claim,))
    )
    assert_compiled_graph_lawful(state, compiled)


def test_ie2_basis_law_refuses_a_canonical_node_on_an_inferred_claim() -> None:
    _, claim, state = _world_with_claim(Authority.INFERRED)
    compiled = compile_(
        _canonical_spine(claim), graph_visibility(state, SCOPE, basis_claim_ids=(claim,))
    )
    with pytest.raises(UnlawfulBasisError, match="UNLAWFUL_BASIS_AUTHORITY"):
        assert_compiled_graph_lawful(state, compiled)


def test_proposed_graph_on_an_inferred_claim_is_not_held_to_canonical_law() -> None:
    _, claim, state = _world_with_claim(Authority.INFERRED)
    compiled = compile_(
        _canonical_spine(claim),
        graph_visibility(state, SCOPE, basis_claim_ids=(claim,)),
        authority=Authority.PROPOSED,
    )
    assert_compiled_graph_lawful(state, compiled)


def test_ie2_relevance_law_refuses_a_canonical_node_serving_a_proposed_goal() -> None:
    world, claim, _ = _world_with_claim(Authority.CANONICAL)
    world.admit_root()
    world.legacy(goal("GOAL-p", authority=Authority.PROPOSED, relations=(rel(S, ROOT_ID),)))
    state = replay(PROJECT, world.store.load(PROJECT))
    graph = result(node(K.GOAL, "goal"), relations=(edge("goal", S, e("GOAL-p")),))
    compiled = compile_(graph, graph_visibility(state, SCOPE, basis_claim_ids=(claim,)))
    with pytest.raises(IrrelevantObjectError, match="ORPHANED_CANONICAL_OBJECT"):
        assert_compiled_graph_lawful(state, compiled)


def test_ie2_legality_refuses_a_target_the_state_does_not_hold() -> None:
    _, claim, state = _world_with_claim(Authority.CANONICAL)
    ghost = visibility(
        visible("INTENT-ghost", K.INTENT),
        visible("GOAL-ghost", K.GOAL, relations=((S, "INTENT-ghost"),)),
        basis=(claim,),
    )
    graph = result(node(K.REQUIREMENT, "req"), relations=(edge("req", S, e("GOAL-ghost")),))
    compiled = compile_(graph, ghost, authority=Authority.PROPOSED)
    with pytest.raises(RelationLegalityError):
        assert_compiled_graph_lawful(state, compiled)


def test_same_batch_references_resolve_only_in_the_hypothetical_state() -> None:
    _, claim, state = _world_with_claim(Authority.CANONICAL)
    compiled = compile_(
        _canonical_spine(claim), graph_visibility(state, SCOPE, basis_claim_ids=(claim,))
    )
    hypothetical = hypothetical_state(state, compiled)
    for obj in compiled.objects:
        assert obj.id not in state.objects
        assert hypothetical.objects[obj.id] == obj
    assert {g.id for g in compiled.gaps} <= set(hypothetical.gaps)


def test_hypothetical_state_never_mutates_its_input() -> None:
    _, claim, state = _world_with_claim(Authority.CANONICAL)
    before = state.model_dump()
    compiled = compile_(
        _canonical_spine(claim), graph_visibility(state, SCOPE, basis_claim_ids=(claim,))
    )
    hypothetical = hypothetical_state(state, compiled)
    assert_compiled_graph_lawful(state, compiled)
    assert state.model_dump() == before
    assert hypothetical is not state
    assert hypothetical.last_sequence == state.last_sequence
    assert hypothetical.source_events == state.source_events


def test_hypothetical_state_applies_the_retirement_plan() -> None:
    world, claim, _ = _world_with_claim(Authority.CANONICAL)
    world.admit_root()
    world.legacy(
        goal("GOAL-root", authority=Authority.PROPOSED, relations=(rel(S, ROOT_ID),)),
        requirement("REQ-stale", authority=Authority.PROPOSED, relations=(rel(S, "GOAL-root"),)),
    )
    state = replay(PROJECT, world.store.load(PROJECT))
    vis = visibility(
        visible(ROOT_ID, K.INTENT),
        visible("GOAL-root", K.GOAL, authority=Authority.PROPOSED, relations=((S, ROOT_ID),)),
        visible("REQ-stale", K.REQUIREMENT, authority=Authority.PROPOSED, is_stale=True),
        basis=(claim,),
        roots=(),
    )
    graph = result(
        node(K.REQUIREMENT, "req2", disposition="REPLACES_STALE", replaces=e("REQ-stale")),
        relations=(edge("req2", S, e("GOAL-root")),),
    )
    compiled = compile_(graph, vis, authority=Authority.PROPOSED)
    hypothetical = hypothetical_state(state, compiled)
    retired = hypothetical.objects["REQ-stale"]
    assert retired.lifecycle is LifecycleStatus.SUPERSEDED
    assert retired.revision == state.objects["REQ-stale"].revision + 1
    assert state.objects["REQ-stale"].lifecycle is LifecycleStatus.ACTIVE


def test_hypothetical_state_refuses_an_object_that_already_exists() -> None:
    _, claim, state = _world_with_claim(Authority.CANONICAL)
    compiled = compile_(
        _canonical_spine(claim), graph_visibility(state, SCOPE, basis_claim_ids=(claim,))
    )
    once = hypothetical_state(state, compiled)
    with pytest.raises(IntentGraphCompilationError, match="OBJECT_ALREADY_EXISTS"):
        hypothetical_state(once, compiled)


def test_hypothetical_state_refuses_another_project() -> None:
    _, claim, state = _world_with_claim(Authority.CANONICAL)
    compiled = compile_(
        _canonical_spine(claim),
        graph_visibility(state, SCOPE, basis_claim_ids=(claim,)),
        identity=IntentGraphIdentity(project_id="PROJ-other", synthesis_run_id=RUN),
    )
    with pytest.raises(IntentGraphCompilationError, match="PROJECT_MISMATCH"):
        hypothetical_state(state, compiled)

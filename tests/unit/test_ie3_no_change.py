"""IE3 Slice 4.1 — explicit NO_CHANGE through ``unchanged_object_refs`` (R111).

A correct "already represented, change nothing" answer must be expressible, routable, durable and
auditable. ``unchanged_object_refs`` are witnesses the model proposes: "this visible, current,
non-stale object already means what was intended; mint nothing for it". They are not relations,
replacements, basis, authority or effects. Deterministic Foundry verifies only that each witness
was genuinely shown and eligible. It never re-judges semantic sameness from text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.application.intent_graph_synthesis import (
    IntentGraphSynthesisSnapshotChanged,
    synthesize_intent_graph,
)
from foundry.application.reducer import reduce_event
from foundry.application.replay import replay
from foundry.domain.common import Authority, LifecycleStatus, RelationType
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    IntentGraphSynthesisDecidedPayload,
    StoredEvent,
)
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import (
    ExistingObjectRef,
    IntentGraphIdentity,
    IntentGraphSynthesisResult,
)
from foundry.domain.intent_graph_compiler import compile_intent_graph
from foundry.domain.intent_graph_routing import derive_graph_origins, route_intent_graph
from foundry.domain.intent_graph_state import (
    GraphNodeAssignment,
    IntentGraphDecision,
    graph_decision_event_id,
)
from foundry.domain.intent_graph_validation import (
    IntentGraphValidationError,
    validate_intent_graph,
)
from foundry.domain.intent_synthesis import IntentSynthesisRoute, SynthesisOrigin
from foundry.domain.semantic import SemanticKind
from foundry.domain.state import IntentState
from tests.unit._ie3_fixtures import (
    DECIDED_AT,
    DECISION_EVENT_ID,
    IDENTITY,
    MODEL,
    assign,
    b,
    e,
    edge,
    gap,
    node,
    result,
    visibility,
    visible,
)
from tests.unit._ie3_s3_fixtures import (
    AI,
    FakeGraphSynthesizer,
    RacingStore,
    clock,
    run_ids,
    unrelated_write,
)
from tests.unit._ie21_fixtures import PROJECT, SCOPE, goal, rel, requirement
from tests.unit._ie22b_fixtures import ROOT_ID, World

K = SemanticKind
S = RelationType.SERVES
D = RelationType.DERIVED_FROM
R = IntentSynthesisRoute
RUN = "RUN-nochange-1"
SAME_THING = "Refund requests are accepted within 30 days of purchase."
AT = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)


def unchanged(*object_ids: str, **extra: Any) -> IntentGraphSynthesisResult:
    return IntentGraphSynthesisResult(
        unchanged_object_refs=tuple(ExistingObjectRef(object_id=i) for i in object_ids), **extra
    )


VIS = visibility(
    visible("INTENT-root", K.INTENT),
    visible("GOAL-root", K.GOAL, relations=((S, "INTENT-root"),)),
    visible("REQ-existing", K.REQUIREMENT, relations=((S, "GOAL-root"),)),
    visible("REQ-stale", K.REQUIREMENT, is_stale=True, relations=((S, "GOAL-root"),)),
    visible("REQ-dead", K.REQUIREMENT, is_current=False, authority=Authority.SUPERSEDED),
)


# ------------------------------------------------------------------- result shape


def test_a_pure_already_represented_answer_is_expressible() -> None:
    graph = unchanged("REQ-existing")
    assert graph.nodes == ()
    assert graph.gaps == ()
    assert graph.unchanged_object_refs == (ExistingObjectRef(object_id="REQ-existing"),)


def test_an_entirely_empty_result_is_still_refused() -> None:
    with pytest.raises(ValidationError, match="empty"):
        IntentGraphSynthesisResult()


def test_relations_alone_never_make_a_result_meaningful() -> None:
    with pytest.raises(ValidationError, match="empty"):
        IntentGraphSynthesisResult(relations=(edge("x", S, e("GOAL-root")),))


def test_duplicate_unchanged_refs_are_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate unchanged"):
        unchanged("REQ-existing", "REQ-existing")


def test_historical_results_parse_without_the_new_field() -> None:
    raw = {"nodes": [], "gaps": [gap().model_dump(mode="json")]}
    assert IntentGraphSynthesisResult.model_validate(raw).unchanged_object_refs == ()


# ------------------------------------------------------------- visibility/staleness


def test_a_visible_current_non_stale_unchanged_ref_validates() -> None:
    validate_intent_graph(unchanged("REQ-existing"), VIS, author_is_human=False)


def test_an_invisible_unchanged_ref_is_refused() -> None:
    with pytest.raises(IntentGraphValidationError, match="INVISIBLE_EXISTING_REF"):
        validate_intent_graph(unchanged("REQ-hidden"), VIS, author_is_human=False)


def test_a_non_current_unchanged_ref_is_refused() -> None:
    with pytest.raises(IntentGraphValidationError, match="EXISTING_NOT_CURRENT"):
        validate_intent_graph(unchanged("REQ-dead"), VIS, author_is_human=False)


def test_a_stale_unchanged_ref_is_refused() -> None:
    with pytest.raises(IntentGraphValidationError, match="UNCHANGED_REF_STALE"):
        validate_intent_graph(unchanged("REQ-stale"), VIS, author_is_human=False)


def test_an_unchanged_ref_may_not_also_be_retired() -> None:
    graph = IntentGraphSynthesisResult(
        nodes=(node(K.REQUIREMENT, "r2", disposition="REPLACES_STALE", replaces=e("REQ-stale")),),
        relations=(edge("r2", S, e("GOAL-root")),),
        unchanged_object_refs=(ExistingObjectRef(object_id="REQ-stale"),),
    )
    with pytest.raises(IntentGraphValidationError, match="UNCHANGED_REF_STALE"):
        validate_intent_graph(graph, VIS, author_is_human=True)


# ------------------------------------------------------------------------- routing


def _route(graph: IntentGraphSynthesisResult, state: IntentState):  # type: ignore[no-untyped-def]
    origins = derive_graph_origins(graph, claim_source_kinds={}, author_is_human=False)
    return route_intent_graph(
        state, result=graph, origins=origins, author=AI, human_actor_id=None, run_scope=SCOPE
    )


EMPTY_STATE = IntentState(project_id=PROJECT)


def test_pure_unchanged_routes_no_change_with_no_assignments() -> None:
    outcome = _route(unchanged("REQ-existing"), EMPTY_STATE)
    assert outcome.decision.route is R.NO_CHANGE
    assert outcome.decision.reasons == ("EXISTING_UNCHANGED",)
    assert outcome.node_assignments == ()


def test_origins_are_derived_only_over_new_nodes() -> None:
    assert (
        derive_graph_origins(
            unchanged("REQ-existing"), claim_source_kinds={}, author_is_human=False
        )
        == {}
    )


def test_unchanged_plus_new_nodes_follows_normal_node_routing() -> None:
    graph = IntentGraphSynthesisResult(
        nodes=(node(K.GOAL, "goal"),),
        relations=(edge("goal", S, e("INTENT-root")),),
        unchanged_object_refs=(ExistingObjectRef(object_id="REQ-existing"),),
    )
    outcome = _route(graph, EMPTY_STATE)
    assert outcome.decision.route is R.APPLY
    assert [a.local_id for a in outcome.node_assignments] == ["goal"]


def test_unchanged_plus_gaps_follows_normal_gap_rules() -> None:
    graph = unchanged("REQ-existing", gaps=(gap("g1", kind=GapKind.MISSING_INFORMATION),))
    outcome = _route(graph, EMPTY_STATE)
    assert outcome.decision.route is R.APPLY
    assert outcome.decision.reasons == ("UNRESOLVED_WORK_RECORDED",)


def test_the_compiler_mints_nothing_for_unchanged_refs() -> None:
    graph = IntentGraphSynthesisResult(
        nodes=(node(K.GOAL, "goal"),),
        relations=(edge("goal", S, e("INTENT-root")), edge("goal", D, b("CLAIM-1"))),
        unchanged_object_refs=(ExistingObjectRef(object_id="REQ-existing"),),
    )
    compiled = compile_intent_graph(
        graph,
        VIS,
        identity=IDENTITY,
        author=MODEL,
        decided_at=DECIDED_AT,
        decision_event_id=DECISION_EVENT_ID,
        assignments=assign(graph, origin=SynthesisOrigin.AI_INFERRED, authority=Authority.PROPOSED),
    )
    goal_id = IDENTITY.object_id(K.GOAL, "goal")
    assert [o.id for o in compiled.objects] == [goal_id]
    assert all("REQ-existing" not in {r.target_id for r in o.relations} for o in compiled.objects)
    assert [(p.object_id, p.parent_ids) for p in compiled.derivation_parents] == [
        (goal_id, ("CLAIM-1",))
    ]
    assert compiled.retirements == ()
    assert compiled.gaps == ()


# ------------------------------------------------------------------ the golden world


def _world() -> tuple[World, str]:
    """A current Requirement and a claim that says the same thing in other words."""
    world = World()
    claim = world.claim(
        "J-same", authority=Authority.CANONICAL, text="refunds may be requested up to 30 days"
    )
    world.admit_root()
    world.legacy(
        goal("GOAL-root", authority=Authority.CANONICAL, relations=(rel(S, ROOT_ID),)),
        requirement(
            "REQ-existing",
            statement=SAME_THING,
            authority=Authority.CANONICAL,
            relations=(rel(S, "GOAL-root"), rel(D, claim)),
        ),
    )
    world.governor.derive("REQ-existing", claim)
    return world, claim


def _state(world: World) -> IntentState:
    return replay(PROJECT, world.store.load(PROJECT))


def _run(store: object, fake: FakeGraphSynthesizer):  # type: ignore[no-untyped-def]
    return synthesize_intent_graph(
        store,  # type: ignore[arg-type]
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=fake,
        clock=clock,
        synthesis_run_id_factory=run_ids(RUN),
    )


def _graph_events(world: World) -> list[EventEnvelope]:
    return [
        s.event
        for s in world.store.load(PROJECT)
        if s.event.event_type is EventType.INTENT_GRAPH_SYNTHESIS_DECIDED
    ]


def test_same_thing_golden_case_is_a_durable_no_change() -> None:
    """The structural prerequisite for the real-model "same thing?" certification exam."""
    world, claim = _world()
    before = _state(world)
    assert before.objects["REQ-existing"].statement == SAME_THING  # type: ignore[union-attr]
    fake = FakeGraphSynthesizer(unchanged("REQ-existing"))
    outcome = _run(world.store, fake)
    assert len(fake.requests) == 1
    assert outcome.decision is not None
    assert outcome.decision.route is R.NO_CHANGE
    assert outcome.decision.reasons == ("EXISTING_UNCHANGED",)
    (event,) = _graph_events(world)
    payload = event.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    assert payload.compiled is None
    assert payload.node_assignments == ()
    after = _state(world)
    assert dict(after.objects) == dict(before.objects)
    assert after.objects["REQ-existing"] == before.objects["REQ-existing"]
    assert after.semantic.derivations == before.semantic.derivations
    assert dict(after.gaps) == dict(before.gaps)
    assert after.intent_synthesis.retirements == before.intent_synthesis.retirements
    record = after.intent_graph_synthesis.decisions[
        IntentGraphIdentity(project_id=PROJECT, synthesis_run_id=RUN).graph_instance_id
    ]
    assert record.result.unchanged_object_refs == (ExistingObjectRef(object_id="REQ-existing"),)
    assert record.decision.route is R.NO_CHANGE


# ------------------------------------------------------------------------ concurrency


def _snapshot_changed(world: World, hook) -> None:  # type: ignore[no-untyped-def]
    fake = FakeGraphSynthesizer(unchanged("REQ-existing"))
    with pytest.raises(IntentGraphSynthesisSnapshotChanged):
        _run(RacingStore(world.store, [hook]), fake)
    assert len(fake.requests) == 1
    assert _graph_events(world) == []


def test_an_unchanged_object_disappearing_before_retry_is_a_snapshot_change() -> None:
    world, claim = _world()
    _snapshot_changed(
        world,
        lambda _: world.legacy(
            requirement("REQ-existing", statement=SAME_THING, authority=Authority.SUPERSEDED)
        ),
    )


def test_an_unchanged_object_going_stale_before_retry_is_a_snapshot_change() -> None:
    world, claim = _world()
    _snapshot_changed(world, lambda _: world.supersede("J-sup", "J-same"))


def test_an_unrelated_race_revalidates_the_same_no_change() -> None:
    world, claim = _world()
    fake = FakeGraphSynthesizer(unchanged("REQ-existing"))
    store = RacingStore(world.store, [unrelated_write(world)])
    outcome = _run(store, fake)
    assert outcome.decision is not None
    assert outcome.decision.route is R.NO_CHANGE
    assert len(fake.requests) == 1
    assert store.append_calls == 2
    assert len(_graph_events(world)) == 1


# ------------------------------------------------------------- reducer tamper controls


def _no_change_payload(state: IntentState, **overrides: Any) -> IntentGraphSynthesisDecidedPayload:
    identity = IntentGraphIdentity(project_id=PROJECT, synthesis_run_id=RUN)
    fields: dict[str, Any] = {
        "identity": identity,
        "author": AI,
        "run_scope": SCOPE,
        "result": unchanged("REQ-existing"),
        "node_assignments": (),
        "decision": IntentGraphDecision(route=R.NO_CHANGE, reasons=("EXISTING_UNCHANGED",)),
        "compiled": None,
    }
    payload = IntentGraphSynthesisDecidedPayload(**fields)
    return payload.model_copy(update=overrides) if overrides else payload


def _reduce(state: IntentState, payload: IntentGraphSynthesisDecidedPayload) -> IntentState:
    envelope = EventEnvelope.model_construct(
        event_id=graph_decision_event_id(payload.identity),
        project_id=PROJECT,
        event_type=EventType.INTENT_GRAPH_SYNTHESIS_DECIDED,
        occurred_at=AT,
        correlation_id=None,
        causation_id=None,
        payload=payload,
    )
    stored = StoredEvent.model_construct(sequence=state.last_sequence + 1, event=envelope)
    return reduce_event(state, stored)


def test_a_lawful_no_change_reduces_to_a_decision_only() -> None:
    world, _ = _world()
    state = _state(world)
    after = _reduce(state, _no_change_payload(state))
    assert dict(after.objects) == dict(state.objects)
    assert after.semantic.derivations == state.semantic.derivations
    assert len(after.intent_graph_synthesis.decisions) == 1


def test_no_change_without_witnesses_is_refused() -> None:
    world, _ = _world()
    state = _state(world)
    empty = unchanged("REQ-existing").model_copy(update={"unchanged_object_refs": ()})
    with pytest.raises(ValueError, match="NO_CHANGE_SHAPE"):
        _reduce(state, _no_change_payload(state, result=empty))


def test_no_change_with_nodes_is_refused() -> None:
    world, _ = _world()
    state = _state(world)
    with_nodes = unchanged("REQ-existing").model_copy(update={"nodes": (node(K.GOAL, "goal"),)})
    payload = _no_change_payload(
        state,
        result=with_nodes,
        node_assignments=(
            GraphNodeAssignment(
                local_id="goal", origin=SynthesisOrigin.AI_INFERRED, authority=Authority.PROPOSED
            ),
        ),
    )
    with pytest.raises(ValueError, match="NO_CHANGE_SHAPE"):
        _reduce(state, payload)


def test_no_change_with_gaps_is_refused() -> None:
    world, _ = _world()
    state = _state(world)
    with_gaps = unchanged("REQ-existing").model_copy(update={"gaps": (gap("g1"),)})
    with pytest.raises(ValueError, match="NO_CHANGE_SHAPE"):
        _reduce(state, _no_change_payload(state, result=with_gaps))


def test_no_change_with_relations_is_refused() -> None:
    world, _ = _world()
    state = _state(world)
    with_rel = unchanged("REQ-existing").model_copy(
        update={"relations": (edge("x", S, e("GOAL-root")),)}
    )
    with pytest.raises(ValueError, match="NO_CHANGE_SHAPE"):
        _reduce(state, _no_change_payload(state, result=with_rel))


def test_no_change_with_a_compiled_graph_is_refused() -> None:
    world, claim = _world()
    state = _state(world)
    apply_graph = result(
        node(K.GOAL, "goal"), relations=(edge("goal", S, e("GOAL-root")), edge("goal", D, b(claim)))
    )
    compiled = compile_intent_graph(
        apply_graph,
        visibility(
            visible(ROOT_ID, K.INTENT),
            visible("GOAL-root", K.GOAL, relations=((S, ROOT_ID),)),
            basis=(claim,),
        ),
        identity=IntentGraphIdentity(project_id=PROJECT, synthesis_run_id=RUN),
        author=AI,
        decided_at=AT,
        decision_event_id="EVT-x",
        assignments=assign(
            apply_graph, origin=SynthesisOrigin.AI_INFERRED, authority=Authority.PROPOSED
        ),
    )
    with pytest.raises(ValueError, match="compiled"):
        _reduce(state, _no_change_payload(state, compiled=compiled))


def test_a_stale_unchanged_witness_is_refused_on_replay() -> None:
    world, _ = _world()
    payload = _no_change_payload(_state(world))
    world.supersede("J-sup", "J-same")
    with pytest.raises(ValueError, match="UNCHANGED_REF"):
        _reduce(_state(world), payload)


def test_a_missing_unchanged_witness_is_refused_on_replay() -> None:
    world, _ = _world()
    state = _state(world)
    with pytest.raises(ValueError, match="UNCHANGED_REF"):
        _reduce(state, _no_change_payload(state, result=unchanged("REQ-ghost")))


def test_a_dead_unchanged_witness_is_refused_on_replay() -> None:
    world, _ = _world()
    payload = _no_change_payload(_state(world))
    world.legacy(requirement("REQ-existing", statement=SAME_THING, authority=Authority.REJECTED))
    with pytest.raises(ValueError, match="UNCHANGED_REF"):
        _reduce(_state(world), payload)


def test_witnesses_beside_an_applied_graph_have_no_effect_but_must_be_valid() -> None:
    world, claim = _world()
    state = _state(world)
    ghost = _no_change_payload(state).model_copy(
        update={
            "decision": IntentGraphDecision(route=R.REQUIRE_HUMAN, reasons=("X",)),
            "result": unchanged("REQ-ghost"),
        }
    )
    with pytest.raises(ValueError, match="UNCHANGED_REF"):
        _reduce(state, ghost)
    assert state.objects["REQ-existing"].lifecycle is LifecycleStatus.ACTIVE

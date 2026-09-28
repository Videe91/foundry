"""IE3 Slice 3 — offline graph synthesis orchestration (R103, R109; design §16).

State N → bounded request → ONE synthesizer call → validate against exactly what was shown →
origins → route → (APPLY: compile + forward IE2 laws) → ONE ``INTENT_GRAPH_SYNTHESIS_DECIDED`` at
``expected_sequence = N``. Retries never call the synthesizer again: the SAME result is
revalidated against a freshly compiled request, or the run fails with ``SnapshotChanged``.
Every synthesizer here is an offline fake.
"""

from __future__ import annotations

import pytest

from foundry.application.intent_graph_synthesis import (
    GRAPH_SYNTHESIS_POLICY_VERSION,
    MAX_GRAPH_SYNTHESIS_ATTEMPTS,
    IntentGraphSynthesisConcurrencyExhausted,
    IntentGraphSynthesisDuplicateConflict,
    IntentGraphSynthesisSnapshotChanged,
    synthesize_intent_graph,
)
from foundry.application.intent_graph_synthesis_context import (
    IntentGraphResultError,
    compile_intent_graph_context,
)
from foundry.application.replay import replay
from foundry.domain.basis import UnlawfulBasisError
from foundry.domain.common import Authority, RelationType
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    GapPayload,
    IntentGraphSynthesisDecidedPayload,
)
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import IntentGraphIdentity, IntentGraphSynthesisResult
from foundry.domain.intent_graph_state import IntentGraphDecision, graph_decision_event_id
from foundry.domain.intent_synthesis import IntentSynthesisRoute, SynthesisOrigin
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.domain.state import IntentState
from tests.unit._ie3_fixtures import b, e, edge, gap, node, result
from tests.unit._ie3_s3_fixtures import (
    BOB,
    CLOCK_AT,
    HUMAN_BOB,
    HUMAN_G,
    FakeGraphSynthesizer,
    RacingStore,
    clock,
    research_claim,
    run_ids,
    unrelated_write,
)
from tests.unit._ie21_fixtures import (
    ALICE,
    PROJECT,
    SCOPE,
    goal,
    intent,
    project_decision,
    rel,
    requirement,
)
from tests.unit._ie22b_fixtures import ROOT_ID, World

K = SemanticKind
S = RelationType.SERVES
D = RelationType.DERIVED_FROM
R = IntentSynthesisRoute
RUN = "RUN-orch-1"


def _state(world: World) -> IntentState:
    return replay(PROJECT, world.store.load(PROJECT))


def _world(*, claim_authority: Authority = Authority.CANONICAL) -> tuple[World, str]:
    world = World()
    claim = world.claim("J-claim", authority=claim_authority)
    world.admit_root()
    world.legacy(goal("GOAL-root", authority=Authority.CANONICAL, relations=(rel(S, ROOT_ID),)))
    return world, claim


def _req_graph(claim: str) -> IntentGraphSynthesisResult:
    return result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-root")), edge("req", D, b(claim))),
    )


def _run(
    store: object,
    synthesizer: FakeGraphSynthesizer,
    *,
    human_actor_id: str | None = None,
    run: str = RUN,
):  # type: ignore[no-untyped-def]
    return synthesize_intent_graph(
        store,  # type: ignore[arg-type]
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=synthesizer,
        clock=clock,
        synthesis_run_id_factory=run_ids(run),
        human_actor_id=human_actor_id,
    )


def _graph_events(world: World) -> list[EventEnvelope]:
    return [
        s.event
        for s in world.store.load(PROJECT)
        if s.event.event_type is EventType.INTENT_GRAPH_SYNTHESIS_DECIDED
    ]


def _identity(run: str = RUN) -> IntentGraphIdentity:
    return IntentGraphIdentity(project_id=PROJECT, synthesis_run_id=run)


# ---------------------------------------------------------------------- the happy path


def test_the_synthesizer_is_called_once_with_exactly_the_compiled_request() -> None:
    world, claim = _world()
    before = _state(world)
    fake = FakeGraphSynthesizer(_req_graph(claim))
    _run(world.store, fake)
    assert len(fake.requests) == 1
    assert fake.requests[0] == compile_intent_graph_context(before, scope=SCOPE).request


def test_a_lawful_model_graph_lands_as_one_atomic_event() -> None:
    world, claim = _world()
    before_count = len(world.store.load(PROJECT))
    outcome = _run(world.store, FakeGraphSynthesizer(_req_graph(claim)))
    events = world.store.load(PROJECT)
    assert len(events) == before_count + 1
    (event,) = _graph_events(world)
    assert event.event_id == graph_decision_event_id(_identity())
    assert event.occurred_at == CLOCK_AT
    assert event.correlation_id == RUN
    payload = event.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    assert payload.decision.route is R.APPLY
    assert payload.compiled is not None
    assert payload.run_scope == SCOPE
    state = _state(world)
    req_id = _identity().object_id(K.REQUIREMENT, "req")
    assert state.objects[req_id].authority is Authority.PROPOSED
    assert outcome.synthesis_run_id == RUN
    assert outcome.graph_instance_id == _identity().graph_instance_id
    assert outcome.decision == payload.decision
    assert outcome.deterministic_runtime_gap_ids == ()
    record = state.intent_graph_synthesis.decisions[_identity().graph_instance_id]
    assert record.decision == outcome.decision


def test_a_lawful_human_graph_is_canonical() -> None:
    world, claim = _world()
    outcome = _run(
        world.store,
        FakeGraphSynthesizer(_req_graph(claim), fingerprint=HUMAN_G),
        human_actor_id=ALICE,
    )
    assert outcome.decision is not None
    assert outcome.decision.route is R.APPLY
    state = _state(world)
    assert (
        state.objects[_identity().object_id(K.REQUIREMENT, "req")].authority is Authority.CANONICAL
    )


def test_require_human_records_one_non_effect_event() -> None:
    world, claim = _world()
    before = _state(world)
    outcome = _run(
        world.store,
        FakeGraphSynthesizer(_req_graph(claim), fingerprint=HUMAN_BOB),
        human_actor_id=BOB,
    )
    assert outcome.decision is not None
    assert outcome.decision.route is R.REQUIRE_HUMAN
    (event,) = _graph_events(world)
    payload = event.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    assert payload.compiled is None
    after = _state(world)
    assert dict(after.objects) == dict(before.objects)


def test_reject_records_one_non_effect_event(monkeypatch: pytest.MonkeyPatch) -> None:
    import foundry.domain.intent_graph_routing as routing

    def invent(*_: object, **kwargs: object) -> dict[str, Authority | None]:
        result_ = kwargs["result"]
        assert isinstance(result_, IntentGraphSynthesisResult)
        return {n.local_id.local_id: Authority.CANONICAL for n in result_.nodes}

    monkeypatch.setattr(routing, "assign_graph_authorities", invent)
    world, claim = _world()
    before = _state(world)
    outcome = _run(world.store, FakeGraphSynthesizer(_req_graph(claim)))
    assert outcome.decision is not None
    assert outcome.decision.route is R.REJECT
    assert outcome.decision.reasons == ("AUTHORITY_INVENTION",)
    assert len(_graph_events(world)) == 1
    assert dict(_state(world).objects) == dict(before.objects)


def test_no_separate_effect_event_is_ever_written() -> None:
    world, claim = _world()
    before = {s.event.event_type for s in world.store.load(PROJECT)}
    _run(world.store, FakeGraphSynthesizer(_req_graph(claim)))
    after = [s.event.event_type for s in world.store.load(PROJECT)]
    new_types = set(after) - before
    assert new_types == {EventType.INTENT_GRAPH_SYNTHESIS_DECIDED}
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in after


def test_partial_graph_with_blocking_gaps_applies_and_the_gaps_block() -> None:
    world, claim = _world()
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-root")), edge("req", D, b(claim))),
        gaps=(gap("g1", kind=GapKind.MISSING_INFORMATION),),
    )
    outcome = _run(world.store, FakeGraphSynthesizer(graph))
    assert outcome.decision is not None
    assert outcome.decision.route is R.APPLY
    gap_id = _identity().gap_id("g1")
    persisted = _state(world).gaps[gap_id]
    assert persisted.blocking is True


def test_r109_research_claim_makes_a_model_node_research_derived() -> None:
    world = World()
    world.admit_root()
    world.legacy(goal("GOAL-root", authority=Authority.CANONICAL, relations=(rel(S, ROOT_ID),)))
    claim = research_claim(world, "J-research", text="thirty days")
    _run(world.store, FakeGraphSynthesizer(_req_graph(claim)))
    (event,) = _graph_events(world)
    payload = event.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    assert [(a.local_id, a.origin, a.authority) for a in payload.node_assignments] == [
        ("req", SynthesisOrigin.RESEARCH_DERIVED, Authority.PROPOSED)
    ]


def test_r109_human_evidence_makes_a_model_node_ai_inferred() -> None:
    world, claim = _world()
    _run(world.store, FakeGraphSynthesizer(_req_graph(claim)))
    payload = _graph_events(world)[0].payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    assert payload.node_assignments[0].origin is SynthesisOrigin.AI_INFERRED


# ------------------------------------------------------------------ fences and refusals


def test_only_the_graph_policy_version_is_accepted() -> None:
    assert GRAPH_SYNTHESIS_POLICY_VERSION == "intent-graph-synthesis-runtime-v4"
    world, claim = _world()
    slice1 = ReasonerFingerprint(
        provider="xai", model="grok-4.7", policy_version="intent-synthesis-runtime-v1"
    )
    fake = FakeGraphSynthesizer(_req_graph(claim), fingerprint=slice1)
    with pytest.raises(ValueError, match="intent-graph-synthesis-runtime-v4"):
        _run(world.store, fake)
    assert fake.requests == []
    assert _graph_events(world) == []


def test_a_result_that_cites_unshown_state_is_refused_before_anything_is_durable() -> None:
    world, claim = _world()
    world.legacy(goal("GOAL-elsewhere", scope=("elsewhere",)))
    before = len(world.store.load(PROJECT))
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-elsewhere")), edge("req", D, b(claim))),
    )
    with pytest.raises(IntentGraphResultError, match="INVISIBLE_EXISTING_REF"):
        _run(world.store, FakeGraphSynthesizer(graph))
    assert len(world.store.load(PROJECT)) == before


def test_an_invalid_result_is_refused_even_when_the_route_would_not_apply() -> None:
    world, claim = _world()
    graph = result(
        node(K.REQUIREMENT, "req"),
        relations=(edge("req", S, e("GOAL-nowhere")), edge("req", D, b(claim))),
    )
    with pytest.raises(IntentGraphResultError):
        _run(world.store, FakeGraphSynthesizer(graph, fingerprint=HUMAN_BOB), human_actor_id=BOB)
    assert _graph_events(world) == []


def test_forward_ie2_laws_refuse_an_unlawful_canonical_graph() -> None:
    world, claim = _world(claim_authority=Authority.INFERRED)
    fake = FakeGraphSynthesizer(_req_graph(claim), fingerprint=HUMAN_G)
    with pytest.raises(UnlawfulBasisError, match="UNLAWFUL_BASIS_AUTHORITY"):
        _run(world.store, fake, human_actor_id=ALICE)
    assert _graph_events(world) == []


# ------------------------------------------------------------------ context blockers


def test_an_oversized_context_records_one_runtime_gap_and_never_calls_the_model() -> None:
    world = World()
    world.legacy(*(goal(f"GOAL-{i:03d}") for i in range(201)))
    fake = FakeGraphSynthesizer(result(gaps=(gap(),)))
    outcome = _run(world.store, fake)
    assert fake.requests == []
    assert outcome.decision is None
    assert outcome.graph_instance_id is None
    (gap_id,) = outcome.deterministic_runtime_gap_ids
    events = world.store.load(PROJECT)
    last = events[-1].event
    assert last.event_type is EventType.GAP_RECORDED
    assert isinstance(last.payload, GapPayload)
    recorded = last.payload.gap
    assert recorded.id == gap_id
    assert recorded.kind is GapKind.CONTEXT_FAILURE
    assert recorded.blocking is True
    assert _state(world).gaps[gap_id].scope == (SCOPE,)  # type: ignore[union-attr]
    assert _graph_events(world) == []


def test_nothing_to_synthesize_is_a_no_op() -> None:
    world = World()
    before = len(world.store.load(PROJECT))
    fake = FakeGraphSynthesizer(result(gaps=(gap(),)))
    outcome = _run(world.store, fake)
    assert fake.requests == []
    assert outcome.decision is None
    assert outcome.deterministic_runtime_gap_ids == ()
    assert len(world.store.load(PROJECT)) == before


# ------------------------------------------------------------------------ concurrency


@pytest.mark.parametrize("conflicts", [1, 2])
def test_conflicts_revalidate_the_same_result_without_a_second_call(conflicts: int) -> None:
    world, claim = _world()
    store = RacingStore(world.store, [unrelated_write(world)] * conflicts)
    fake = FakeGraphSynthesizer(_req_graph(claim))
    outcome = _run(store, fake)
    assert len(fake.requests) == 1
    assert store.append_calls == conflicts + 1
    assert outcome.decision is not None
    assert outcome.decision.route is R.APPLY
    assert len(_graph_events(world)) == 1
    assert _graph_events(world)[0].event_id == graph_decision_event_id(_identity())


def test_three_conflicts_exhaust_and_nothing_is_durable() -> None:
    assert MAX_GRAPH_SYNTHESIS_ATTEMPTS == 3
    world, claim = _world()
    store = RacingStore(world.store, [unrelated_write(world)] * 3)
    fake = FakeGraphSynthesizer(_req_graph(claim))
    with pytest.raises(IntentGraphSynthesisConcurrencyExhausted):
        _run(store, fake)
    assert len(fake.requests) == 1
    assert store.append_calls == 3
    assert _graph_events(world) == []


def _snapshot_changed(world: World, graph: IntentGraphSynthesisResult, hook) -> None:  # type: ignore[no-untyped-def]
    fake = FakeGraphSynthesizer(graph)
    with pytest.raises(IntentGraphSynthesisSnapshotChanged):
        _run(RacingStore(world.store, [hook]), fake)
    assert len(fake.requests) == 1
    assert _graph_events(world) == []


def test_basis_disappearing_during_retry_is_a_snapshot_change() -> None:
    world, claim = _world()
    _snapshot_changed(world, _req_graph(claim), lambda _: world.supersede("J-sup", "J-claim"))


def test_replacement_staleness_flipping_during_retry_is_a_snapshot_change() -> None:
    # One address only: the superseded claim leaves no live basis, so the replacement is
    # grounded on an existing canonical Decision instead.
    world, claim = _world()
    world.legacy(
        requirement("REQ-old", relations=(rel(S, "GOAL-root"),)),
        project_decision("DEC-x", authority=Authority.CANONICAL, relations=(rel(S, "GOAL-root"),)),
    )
    world.governor.derive("REQ-old", claim)
    world.supersede("J-sup", "J-claim")
    graph = result(
        node(K.REQUIREMENT, "req2", disposition="REPLACES_STALE", replaces=e("REQ-old")),
        relations=(edge("req2", S, e("GOAL-root")), edge("req2", D, e("DEC-x"))),
    )
    _snapshot_changed(world, graph, lambda _: world.supersede("J-sup-sup", "J-sup"))


def test_a_visible_target_disappearing_during_retry_is_a_snapshot_change() -> None:
    world, claim = _world()
    _snapshot_changed(
        world,
        _req_graph(claim),
        lambda _: world.legacy(
            goal("GOAL-root", authority=Authority.SUPERSEDED, relations=(rel(S, ROOT_ID),))
        ),
    )


def test_a_new_conflicting_root_during_retry_is_a_snapshot_change() -> None:
    world = World()
    claim = world.claim("J-claim", authority=Authority.CANONICAL)
    graph = result(node(K.INTENT, "intent"), relations=(edge("intent", D, b(claim)),))
    _snapshot_changed(
        world,
        graph,
        lambda _: world.admit_canonical(intent("INTENT-rival", authority=Authority.CANONICAL)),
    )


# -------------------------------------------------------------------- duplicate adoption


def test_an_exact_duplicate_is_adopted() -> None:
    world, claim = _world()

    def same_event_first(event: EventEnvelope) -> None:
        world.store.append(event, expected_sequence=world.store.current_sequence(PROJECT))

    fake = FakeGraphSynthesizer(_req_graph(claim))
    outcome = _run(RacingStore(world.store, [same_event_first]), fake)
    assert outcome.adopted is True
    assert outcome.decision is not None
    assert outcome.decision.route is R.APPLY
    assert len(_graph_events(world)) == 1
    assert len(fake.requests) == 1


def test_a_conflicting_duplicate_fails_closed() -> None:
    world, claim = _world()

    def other_body_first(event: EventEnvelope) -> None:
        payload = event.payload
        assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
        other = IntentGraphSynthesisDecidedPayload(
            identity=payload.identity,
            author=payload.author,
            run_scope=payload.run_scope,
            result=result(gaps=(gap("something-else"),)),
            node_assignments=(),
            decision=IntentGraphDecision(route=R.REQUIRE_HUMAN, reasons=("OTHER_WORKER",)),
            compiled=None,
        )
        world.store.append(
            event.model_copy(update={"payload": other}),
            expected_sequence=world.store.current_sequence(PROJECT),
        )

    fake = FakeGraphSynthesizer(_req_graph(claim))
    with pytest.raises(IntentGraphSynthesisDuplicateConflict):
        _run(RacingStore(world.store, [other_body_first]), fake)
    assert len(fake.requests) == 1


# ------------------------------------------------ a write lands while the model is thinking


def _thinking_then(world: World, graph: IntentGraphSynthesisResult, write) -> FakeGraphSynthesizer:  # type: ignore[no-untyped-def]
    """A synthesizer during whose call someone else writes: the realistic race."""

    def answer(_: object) -> IntentGraphSynthesisResult:
        write()
        return graph

    return FakeGraphSynthesizer(answer)  # type: ignore[arg-type]


def test_a_write_during_synthesis_forces_a_revalidated_retry_at_the_new_sequence() -> None:
    world, claim = _world()
    fake = _thinking_then(world, _req_graph(claim), lambda: unrelated_write(world)(None))  # type: ignore[arg-type]
    store = RacingStore(world.store)
    outcome = _run(store, fake)
    assert outcome.decision is not None
    assert outcome.decision.route is R.APPLY
    # The decision computed against N must not land after N: one conflict, one revalidated retry.
    assert store.append_calls == 2
    assert len(fake.requests) == 1


def test_a_basis_retired_during_synthesis_is_never_applied() -> None:
    world, claim = _world()
    fake = _thinking_then(world, _req_graph(claim), lambda: world.supersede("J-sup", "J-claim"))
    with pytest.raises(IntentGraphSynthesisSnapshotChanged):
        _run(RacingStore(world.store), fake)
    assert _graph_events(world) == []

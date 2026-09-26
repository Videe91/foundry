"""IE3 Slice 2 — the atomic durable Intent Graph transition (R103, R108).

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§14-§17, §19).

One ``INTENT_GRAPH_SYNTHESIS_DECIDED`` event is the decision AND the application: there is no
decided-but-unapplied window. The reducer is an independent second body. It re-derives every
binding from the immutable payload and the state prefix it lands on, and never calls the
compiler, the validator or any forward IE2 governance law.

Worlds are built through the real governed path (``World``); graph events are compiled with the
real Slice-1 compiler, then appended and replayed through the ordinary event store. Tamper tests
hand-alter a valid payload with ``model_copy``, which bypasses construction-time validation, so
the reducer is the only thing that can catch them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.application.reducer import reduce_event
from foundry.application.replay import replay
from foundry.domain.common import Authority, LifecycleStatus, RelationType, RiskLevel, SourceKind
from foundry.domain.events import (
    EVENT_PAYLOAD_TYPES,
    EventEnvelope,
    EventType,
    IntentGraphSynthesisDecidedPayload,
    StoredEvent,
    parse_event,
)
from foundry.domain.gaps import GapKind
from foundry.domain.handoff_v2 import validly_reconciled
from foundry.domain.intent_graph import (
    IntentGraphGap,
    IntentGraphIdentity,
    IntentGraphSynthesisResult,
    MissingNeed,
)
from foundry.domain.intent_graph_compiler import compile_intent_graph
from foundry.domain.intent_graph_state import (
    GRAPH_DECISION_STEP,
    CompiledIntentGraph,
    GraphNodeAssignment,
    IntentGraphDecision,
    IntentGraphDecisionRecord,
    IntentGraphSynthesisState,
    ObjectDerivationParents,
    RetirementPlanEntry,
    graph_decision_event_id,
)
from foundry.domain.intent_graph_validation import graph_visibility
from foundry.domain.intent_synthesis import IntentSynthesisRoute, SynthesisOrigin
from foundry.domain.semantic import ConstraintFacet, SemanticKind
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from tests.unit._ie3_fixtures import b, e, edge, gap, local, node, result
from tests.unit._ie21_fixtures import (
    HUMAN,
    MODEL,
    PROJECT,
    SCOPE,
    goal,
    project_decision,
    rel,
    requirement,
)
from tests.unit._ie22b_fixtures import ROOT_ID, World

K = SemanticKind
D = RelationType.DERIVED_FROM
S = RelationType.SERVES
A = RelationType.AFFECTS
APPLY = IntentSynthesisRoute.APPLY
RUN = "RUN-durable-1"
AT = datetime(2026, 9, 27, 9, 30, tzinfo=UTC)
REASONS = ("HUMAN_AUTHORITY",)


# --------------------------------------------------------------------------- builders


def _state(world: World) -> IntentState:
    return replay(PROJECT, world.store.load(PROJECT))


def _identity(run: str = RUN) -> IntentGraphIdentity:
    return IntentGraphIdentity(project_id=PROJECT, synthesis_run_id=run)


def _assignments(
    graph: IntentGraphSynthesisResult,
    *,
    origin: SynthesisOrigin,
    authority: Authority | None,
) -> tuple[GraphNodeAssignment, ...]:
    return tuple(
        GraphNodeAssignment(local_id=lid, origin=origin, authority=authority)
        for lid in sorted(n.local_id.local_id for n in graph.nodes)
    )


def graph_payload(
    state: IntentState,
    graph: IntentGraphSynthesisResult,
    *,
    basis: tuple[str, ...] = (),
    author: ReasonerFingerprint = HUMAN,
    origin: SynthesisOrigin = SynthesisOrigin.HUMAN_STATED,
    authority: Authority | None = Authority.CANONICAL,
    route: IntentSynthesisRoute = APPLY,
    run: str = RUN,
) -> IntentGraphSynthesisDecidedPayload:
    """A lawful payload exactly as the future runtime would write it."""
    identity = _identity(run)
    vis = graph_visibility(state, SCOPE, basis_claim_ids=basis)
    assignments = _assignments(graph, origin=origin, authority=authority)
    compiled = None
    if route is APPLY:
        from foundry.domain.intent_graph_state import NodeAssignment

        compiled = compile_intent_graph(
            graph,
            vis,
            identity=identity,
            author=author,
            decided_at=AT,
            decision_event_id=graph_decision_event_id(identity),
            assignments={
                a.local_id: NodeAssignment(origin=a.origin, authority=a.authority)
                for a in assignments
                if a.authority is not None
            },
        )
    return IntentGraphSynthesisDecidedPayload(
        identity=identity,
        author=author,
        run_scope=SCOPE,
        result=graph,
        node_assignments=assignments,
        decision=IntentGraphDecision(route=route, reasons=REASONS),
        compiled=compiled,
    )


def envelope(
    payload: IntentGraphSynthesisDecidedPayload,
    *,
    event_id: str | None = None,
    occurred_at: datetime = AT,
    project_id: str = PROJECT,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id or graph_decision_event_id(payload.identity),
        project_id=project_id,
        event_type=EventType.INTENT_GRAPH_SYNTHESIS_DECIDED,
        occurred_at=occurred_at,
        payload=payload,
    )


def raw_envelope(payload: IntentGraphSynthesisDecidedPayload) -> EventEnvelope:
    """An envelope built WITHOUT validation, so a tampered payload reaches the reducer intact.

    Parsing a stored event re-runs every model validator, which is defence in depth. These tests
    remove that layer on purpose: the reducer must refuse on its own.
    """
    return EventEnvelope.model_construct(
        event_id=graph_decision_event_id(payload.identity),
        project_id=PROJECT,
        event_type=EventType.INTENT_GRAPH_SYNTHESIS_DECIDED,
        occurred_at=AT,
        correlation_id=None,
        causation_id=None,
        payload=payload,
    )


def reduce(state: IntentState, env: EventEnvelope) -> IntentState:
    stored = StoredEvent.model_construct(sequence=state.last_sequence + 1, event=env)
    return reduce_event(state, stored)


def append(world: World, env: EventEnvelope) -> IntentState:
    world.store.append(env, expected_sequence=world.store.current_sequence(PROJECT))
    return _state(world)


def refused(state: IntentState, env: EventEnvelope, code: str) -> None:
    with pytest.raises(ValueError, match=code):
        reduce(state, env)


# ------------------------------------------------------------------------ the world


def _world() -> tuple[World, str]:
    """A canonical claim and an existing canonical Decision; no root yet."""
    world = World()
    claim = world.claim("J-claim", authority=Authority.CANONICAL)
    world.legacy(project_decision("DEC-x", authority=Authority.CANONICAL, scope=(SCOPE,)))
    return world, claim


def _graph(claim: str) -> IntentGraphSynthesisResult:
    """Intent <- Goal <- two Requirements; same-batch SERVES and DERIVED_FROM; a premise; a gap."""
    return result(
        node(K.INTENT, "intent"),
        node(K.GOAL, "goal"),
        node(K.REQUIREMENT, "req", confidence=0.8),
        node(K.REQUIREMENT, "req2"),
        node(K.CONSTRAINT, "con", facet=ConstraintFacet.EVIDENCE_BOUND),
        node(K.ASSUMPTION, "asm", proposed_risk_level=RiskLevel.LOW),
        relations=(
            edge("goal", S, "intent"),
            edge("req", S, "goal"),
            edge("req", D, b(claim)),
            edge("req", D, "goal"),
            edge("req2", S, "goal"),
            edge("req2", D, e("DEC-x")),
            edge("con", S, "intent"),
            edge("con", D, b(claim)),
            edge("asm", A, "req"),
        ),
        gaps=(
            gap(
                "g-premise",
                kind=GapKind.UNSUPPORTED_ASSUMPTION,
                anchors=(local("asm"), b(claim)),
                missing_need=MissingNeed.EXTERNAL_FACT,
            ),
        ),
    )


def _applied() -> tuple[World, str, IntentState, EventEnvelope]:
    world, claim = _world()
    before = _state(world)
    env = envelope(graph_payload(before, _graph(claim), basis=(claim,)))
    return world, claim, before, env


def _oid(kind: SemanticKind, local_id: str, run: str = RUN) -> str:
    return _identity(run).object_id(kind, local_id)


# --------------------------------------------------------------------- event contract


def test_the_event_type_exists_with_its_own_payload() -> None:
    assert EventType.INTENT_GRAPH_SYNTHESIS_DECIDED.value == "INTENT_GRAPH_SYNTHESIS_DECIDED"
    assert (
        EVENT_PAYLOAD_TYPES[EventType.INTENT_GRAPH_SYNTHESIS_DECIDED]
        is IntentGraphSynthesisDecidedPayload
    )


def test_existing_event_contracts_are_unchanged() -> None:
    from foundry.domain import events as ev

    assert (
        EVENT_PAYLOAD_TYPES[EventType.INTENT_SYNTHESIS_DECIDED] is ev.IntentSynthesisDecidedPayload
    )
    assert EVENT_PAYLOAD_TYPES[EventType.INTENT_OBJECT_SYNTHESIZED] is ev.IntentObjectPayload
    assert EVENT_PAYLOAD_TYPES[EventType.INTENT_OBJECT_ADMITTED] is ev.IntentObjectAdmissionPayload
    assert (
        EVENT_PAYLOAD_TYPES[EventType.INTENT_SYNTHESIS_INVALIDATED]
        is ev.IntentSynthesisInvalidatedPayload
    )
    assert len(EVENT_PAYLOAD_TYPES) == len(EventType)


def test_the_pinned_decision_step_and_event_id_are_golden() -> None:
    assert GRAPH_DECISION_STEP == "DECIDED"
    identity = _identity()
    assert graph_decision_event_id(identity) == identity.event_id("DECIDED")
    assert graph_decision_event_id(identity).startswith("EVT-")


def test_apply_requires_a_compiled_graph() -> None:
    world, claim, before, env = _applied()
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    with pytest.raises(ValidationError, match="APPLY"):
        IntentGraphSynthesisDecidedPayload.model_validate(
            {**payload.model_dump(), "compiled": None}
        )


@pytest.mark.parametrize(
    "route",
    [
        IntentSynthesisRoute.NO_CHANGE,
        IntentSynthesisRoute.REQUIRE_HUMAN,
        IntentSynthesisRoute.REJECT,
    ],
    ids=str,
)
def test_non_apply_must_not_carry_a_compiled_graph(route: IntentSynthesisRoute) -> None:
    world, claim, before, env = _applied()
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    with pytest.raises(ValidationError, match="compiled"):
        IntentGraphSynthesisDecidedPayload.model_validate(
            {**payload.model_dump(), "decision": {"route": route, "reasons": ["X"]}}
        )


def test_second_lens_is_not_a_graph_route() -> None:
    with pytest.raises(ValidationError, match="REQUIRE_SECOND_LENS"):
        IntentGraphDecision(route=IntentSynthesisRoute.REQUIRE_SECOND_LENS, reasons=("X",))


def test_decision_needs_reasons() -> None:
    with pytest.raises(ValidationError):
        IntentGraphDecision(route=APPLY, reasons=())


def test_assignments_must_name_exactly_the_nodes() -> None:
    world, claim, before, env = _applied()
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    dumped = payload.model_dump()
    with pytest.raises(ValidationError, match="assignments"):
        IntentGraphSynthesisDecidedPayload.model_validate(
            {**dumped, "node_assignments": dumped["node_assignments"][1:]}
        )


def test_envelope_owns_event_id_and_time() -> None:
    world, claim, before, env = _applied()
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    for field in ("event_id", "occurred_at", "decided_at", "decision_event_id", "project_id"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            IntentGraphSynthesisDecidedPayload.model_validate({**payload.model_dump(), field: "x"})


def test_project_mismatch_is_refused_by_the_envelope() -> None:
    world, claim, before, env = _applied()
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    with pytest.raises(ValidationError, match="does not match"):
        envelope(payload, project_id="PROJ-other")


def test_unknown_graph_contract_version_fails_parsing() -> None:
    world, claim, before, env = _applied()
    raw = env.model_dump(mode="json")
    raw["payload"]["graph_contract_version"] = "ie3.graph-v2"
    with pytest.raises(ValidationError):
        parse_event(raw)


def test_event_serialization_round_trips() -> None:
    world, claim, before, env = _applied()
    parsed = parse_event(env.model_dump(mode="json"))
    assert parsed == env
    payload = parsed.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    assert payload.compiled is not None
    assert all(isinstance(g, IntentGraphGap) for g in payload.compiled.gaps)


def test_wrong_event_id_is_refused() -> None:
    world, claim, before, env = _applied()
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    refused(before, envelope(payload, event_id="EVT-chosen-by-someone"), "GRAPH_EVENT_ID")


# ------------------------------------------------------------------------------ state


def test_graph_plane_defaults_empty() -> None:
    assert IntentState(project_id=PROJECT).intent_graph_synthesis == IntentGraphSynthesisState()
    assert dict(IntentGraphSynthesisState().decisions) == {}


def test_historical_streams_replay_with_an_empty_graph_plane() -> None:
    world, claim = _world()
    world.supersede("J-sup", "J-claim")
    state = _state(world)
    assert dict(state.intent_graph_synthesis.decisions) == {}
    assert replay(PROJECT, world.store.load(PROJECT)) == state


def test_decision_mapping_is_frozen_and_keyed_by_graph_instance() -> None:
    world, claim, before, env = _applied()
    after = reduce(before, env)
    decisions = after.intent_graph_synthesis.decisions
    assert list(decisions) == [_identity().graph_instance_id]
    with pytest.raises(TypeError):
        decisions["x"] = decisions[_identity().graph_instance_id]  # type: ignore[index]
    record = decisions[_identity().graph_instance_id]
    assert isinstance(record, IntentGraphDecisionRecord)
    assert record.decision_event_id == env.event_id
    assert record.decided_at == AT
    assert IntentGraphSynthesisState.model_validate(after.intent_graph_synthesis.model_dump()) == (
        after.intent_graph_synthesis
    )


def test_state_refuses_a_record_under_the_wrong_key() -> None:
    world, claim, before, env = _applied()
    record = reduce(before, env).intent_graph_synthesis.decisions[_identity().graph_instance_id]
    with pytest.raises(ValidationError, match="keyed"):
        IntentGraphSynthesisState(decisions={"GSY-other": record})


def test_a_duplicate_graph_decision_is_refused() -> None:
    world, claim, before, env = _applied()
    after = reduce(before, env)
    refused(after, env, "already has a durable decision")


# ----------------------------------------------------------------------- APPLY effects


def test_multi_node_graph_appears_in_one_transition() -> None:
    world, claim, before, env = _applied()
    after = append(world, env)
    ids = {
        _oid(k, lid)
        for k, lid in (
            (K.INTENT, "intent"),
            (K.GOAL, "goal"),
            (K.REQUIREMENT, "req"),
            (K.REQUIREMENT, "req2"),
            (K.CONSTRAINT, "con"),
            (K.ASSUMPTION, "asm"),
        )
    }
    assert ids <= set(after.objects)
    assert ids.isdisjoint(before.objects)
    assert after.last_sequence == before.last_sequence + 1


def test_same_batch_serves_and_derived_from_resolve_to_durable_ids() -> None:
    world, claim, before, env = _applied()
    after = reduce(before, env)
    req = after.objects[_oid(K.REQUIREMENT, "req")]
    pairs = {(r.relation_type, r.target_id) for r in req.relations}
    assert (S, _oid(K.GOAL, "goal")) in pairs
    assert (D, _oid(K.GOAL, "goal")) in pairs
    assert (D, claim) in pairs


def _edges(state: IntentState, event_id: str) -> set[tuple[str, str]]:
    return {
        (e_.child_id, e_.parent_id)
        for e_ in state.semantic.derivations
        if e_.recorded_by_event_id == event_id
    }


def test_r108_derivation_edges_use_the_actual_derived_from_targets() -> None:
    world, claim, before, env = _applied()
    after = reduce(before, env)
    judgment = before.semantic.claims[claim].created_by_judgment_id
    assert _edges(after, env.event_id) == {
        (_oid(K.REQUIREMENT, "req"), claim),
        (_oid(K.REQUIREMENT, "req"), _oid(K.GOAL, "goal")),
        (_oid(K.REQUIREMENT, "req2"), "DEC-x"),
        (_oid(K.CONSTRAINT, "con"), claim),
    }
    assert all(parent != judgment for _, parent in _edges(after, env.event_id))


def test_compiled_derivation_parents_are_canonical_and_exact() -> None:
    world, claim, before, env = _applied()
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    compiled = payload.compiled
    assert compiled is not None
    assert [p.object_id for p in compiled.derivation_parents] == [o.id for o in compiled.objects]
    for entry, obj in zip(compiled.derivation_parents, compiled.objects, strict=True):
        expected = tuple(sorted({r.target_id for r in obj.relations if r.relation_type is D}))
        assert entry.parent_ids == expected
    with pytest.raises(ValidationError):
        ObjectDerivationParents(object_id="X", parent_ids=("b", "a"))
    with pytest.raises(ValidationError):
        ObjectDerivationParents(object_id="X", parent_ids=("a", "a"))


def test_derivation_parents_are_independent_of_input_order() -> None:
    world, claim = _world()
    state = _state(world)
    graph = _graph(claim)
    shuffled = IntentGraphSynthesisResult(
        nodes=tuple(reversed(graph.nodes)),
        relations=tuple(reversed(graph.relations)),
        gaps=graph.gaps,
    )
    assert (
        graph_payload(state, graph, basis=(claim,)).compiled
        == graph_payload(state, shuffled, basis=(claim,)).compiled
    )


def test_graph_gaps_persist_with_their_diagnosis() -> None:
    world, claim, before, env = _applied()
    after = reduce(before, env)
    gap_id = _identity().gap_id("g-premise")
    persisted = after.gaps[gap_id]
    assert isinstance(persisted, IntentGraphGap)
    assert persisted.missing_need is MissingNeed.EXTERNAL_FACT
    assert persisted.blocking is True
    assert persisted.scope == (SCOPE,)
    assert persisted.affected_object_ids == (_oid(K.ASSUMPTION, "asm"),)
    assert persisted.affected_claim_ids == (claim,)


def test_the_decision_record_persists_everything_needed_to_audit_it() -> None:
    world, claim, before, env = _applied()
    after = reduce(before, env)
    record = after.intent_graph_synthesis.decisions[_identity().graph_instance_id]
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    assert record.result == payload.result
    assert record.compiled == payload.compiled
    assert record.node_assignments == payload.node_assignments
    assert record.author == HUMAN
    assert record.decision.route is APPLY


def test_assumption_risk_and_confidence_land_as_compiled() -> None:
    world, claim, before, env = _applied()
    after = reduce(before, env)
    assert after.objects[_oid(K.ASSUMPTION, "asm")].risk_level is RiskLevel.LOW  # type: ignore[union-attr]
    assert after.objects[_oid(K.REQUIREMENT, "req")].confidence == 0.8
    assert after.objects[_oid(K.REQUIREMENT, "req2")].confidence is None


# ------------------------------------------------------------------------ atomicity


def _graph_effects(state: IntentState, env: EventEnvelope) -> dict[str, Any]:
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    assert payload.compiled is not None
    ids = [o.id for o in payload.compiled.objects]
    return {
        "objects": [i for i in ids if i in state.objects],
        "edges": sorted(_edges(state, env.event_id)),
        "gaps": [g.id for g in payload.compiled.gaps if g.id in state.gaps],
        "retirements": [
            r for r in state.intent_synthesis.retirements if r.recorded_by_event_id == env.event_id
        ],
        "decision": payload.identity.graph_instance_id in state.intent_graph_synthesis.decisions,
    }


def test_every_prefix_shows_all_of_the_graph_or_none_of_it() -> None:
    world, claim, before, env = _applied()
    after = append(world, env)
    events = world.store.load(PROJECT)
    for cut in range(len(events) + 1):
        prefix = replay(PROJECT, events[:cut])
        effects = _graph_effects(prefix, env)
        if cut < len(events):
            assert effects == {
                "objects": [],
                "edges": [],
                "gaps": [],
                "retirements": [],
                "decision": False,
            }
        else:
            assert effects == _graph_effects(after, env)
            assert len(effects["objects"]) == 6
            assert effects["edges"]
            assert effects["gaps"]
            assert effects["decision"] is True


def test_a_refused_graph_leaves_the_ledger_and_state_unchanged() -> None:
    world, claim, before, env = _applied()
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    bad = envelope(payload, event_id="EVT-wrong")
    world.store.append(bad, expected_sequence=world.store.current_sequence(PROJECT))
    with pytest.raises(ValueError, match="GRAPH_EVENT_ID"):
        _state(world)
    assert before == replay(PROJECT, world.store.load(PROJECT)[:-1])


# ------------------------------------------------------------- replacement / retirement


def _stale_world(*, target_authority: Authority = Authority.PROPOSED) -> tuple[World, str, str]:
    """A root, a Goal serving it, and REQ-old grounded on a claim that is then superseded."""
    world = World()
    old_claim = world.claim("J-old", authority=Authority.CANONICAL)
    new_claim = world.claim("J-new", authority=Authority.CANONICAL, text="thirty calendar days")
    world.admit_root()
    world.legacy(
        goal("GOAL-root", authority=Authority.CANONICAL, relations=(rel(S, ROOT_ID),)),
        requirement(
            "REQ-old",
            authority=target_authority,
            relations=(rel(S, "GOAL-root"), rel(D, old_claim)),
        ),
    )
    world.governor.derive("REQ-old", old_claim)
    world.supersede("J-sup", "J-old")
    assert "REQ-old" in derive_view(_state(world).semantic).stale_ids
    return world, old_claim, new_claim


def _replacement(new_claim: str) -> IntentGraphSynthesisResult:
    return result(
        node(K.REQUIREMENT, "req-new", disposition="REPLACES_STALE", replaces=e("REQ-old")),
        relations=(edge("req-new", S, e("GOAL-root")), edge("req-new", D, b(new_claim))),
    )


def test_replacement_supersedes_the_target_and_records_retirement() -> None:
    world, old_claim, new_claim = _stale_world()
    before = _state(world)
    env = envelope(
        graph_payload(
            before, _replacement(new_claim), basis=(new_claim,), authority=Authority.PROPOSED
        )
    )
    after = append(world, env)
    retired = after.objects["REQ-old"]
    assert retired.lifecycle is LifecycleStatus.SUPERSEDED
    assert retired.revision == before.objects["REQ-old"].revision + 1
    (record,) = [
        r for r in after.intent_synthesis.retirements if r.recorded_by_event_id == env.event_id
    ]
    assert record.retired_object_id == "REQ-old"
    assert record.replaced_by_object_id == _oid(K.REQUIREMENT, "req-new")
    assert record.proposal_instance_id == _identity().node_instance_id("req-new")
    view = derive_view(after.semantic)
    assert validly_reconciled(after, view, SCOPE, "REQ-old")


def test_replacement_is_refused_when_the_target_is_no_longer_stale() -> None:
    world, old_claim, new_claim = _stale_world()
    before = _state(world)
    env = envelope(
        graph_payload(
            before, _replacement(new_claim), basis=(new_claim,), authority=Authority.PROPOSED
        )
    )
    world.supersede("J-sup-sup", "J-sup")  # the old claim is live again
    restored = _state(world)
    assert "REQ-old" not in derive_view(restored.semantic).stale_ids
    refused(restored, env, "REPLACEMENT_NOT_STALE")


def test_replacement_is_refused_when_the_target_was_already_retired() -> None:
    world, old_claim, new_claim = _stale_world()
    before = _state(world)
    env = envelope(
        graph_payload(
            before, _replacement(new_claim), basis=(new_claim,), authority=Authority.PROPOSED
        )
    )
    other = envelope(
        graph_payload(
            before,
            _replacement(new_claim),
            basis=(new_claim,),
            authority=Authority.PROPOSED,
            run="RUN-2",
        )
    )
    after = reduce(before, env)
    refused(after, other, "REPLACEMENT_TARGET_NOT_CURRENT")


def test_replacement_target_changed_in_the_payload_is_refused() -> None:
    world, old_claim, new_claim = _stale_world()
    before = _state(world)
    payload = graph_payload(
        before, _replacement(new_claim), basis=(new_claim,), authority=Authority.PROPOSED
    )
    assert payload.compiled is not None
    entry = payload.compiled.retirements[0].model_copy(update={"retired_object_id": "GOAL-root"})
    tampered = _with_compiled(payload, retirements=(entry,))
    refused(before, raw_envelope(tampered), "BINDING_RETIREMENT")


def test_c11_is_rechecked_by_the_reducer() -> None:
    world, old_claim, new_claim = _stale_world(target_authority=Authority.CANONICAL)
    before = _state(world)
    payload = graph_payload(before, _replacement(new_claim), basis=(new_claim,))
    assert payload.compiled is not None
    weakened = _with_object(payload, "req-new", authority=Authority.PROPOSED)
    weakened = weakened.model_copy(
        update={
            "node_assignments": _assignments(
                payload.result, origin=SynthesisOrigin.HUMAN_STATED, authority=Authority.PROPOSED
            )
        }
    )
    refused(before, raw_envelope(weakened), "CANONICAL_REPLACEMENT_REQUIRED")


# ----------------------------------------------------------------------- non-APPLY


@pytest.mark.parametrize(
    "route",
    [
        IntentSynthesisRoute.NO_CHANGE,
        IntentSynthesisRoute.REQUIRE_HUMAN,
        IntentSynthesisRoute.REJECT,
    ],
    ids=str,
)
def test_non_apply_records_only_the_decision(route: IntentSynthesisRoute) -> None:
    world, claim = _world()
    before = _state(world)
    authority = Authority.CANONICAL if route is IntentSynthesisRoute.REJECT else None
    env = envelope(
        graph_payload(
            before,
            _graph(claim),
            basis=(claim,),
            route=route,
            authority=authority,
            author=MODEL if route is IntentSynthesisRoute.REJECT else HUMAN,
            origin=(
                SynthesisOrigin.AI_INFERRED
                if route is IntentSynthesisRoute.REJECT
                else SynthesisOrigin.HUMAN_STATED
            ),
        )
    )
    after = append(world, env)
    assert dict(after.objects) == dict(before.objects)
    assert after.semantic.derivations == before.semantic.derivations
    assert dict(after.gaps) == dict(before.gaps)
    assert after.intent_synthesis == before.intent_synthesis
    record = after.intent_graph_synthesis.decisions[_identity().graph_instance_id]
    assert record.decision.route is route
    assert record.compiled is None


# ------------------------------------------------------------ R105-R107 integration


def test_ie3_claim_id_edges_go_stale_when_the_claim_is_superseded() -> None:
    world, claim, before, env = _applied()
    append(world, env)
    req = _oid(K.REQUIREMENT, "req")
    assert req not in derive_view(_state(world).semantic).stale_ids
    world.supersede("J-sup", "J-claim")
    stale = derive_view(_state(world).semantic).stale_ids
    assert req in stale
    assert _oid(K.CONSTRAINT, "con") in stale
    assert claim not in stale


# ------------------------------------------------------------------- tamper resistance


def _payload_of(env: EventEnvelope) -> IntentGraphSynthesisDecidedPayload:
    payload = env.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    return payload


def _with_compiled(
    payload: IntentGraphSynthesisDecidedPayload, **updates: Any
) -> IntentGraphSynthesisDecidedPayload:
    assert payload.compiled is not None
    return payload.model_copy(update={"compiled": payload.compiled.model_copy(update=updates)})


def _with_object(
    payload: IntentGraphSynthesisDecidedPayload, local_id: str, **updates: Any
) -> IntentGraphSynthesisDecidedPayload:
    compiled = payload.compiled
    assert compiled is not None
    target = dict(compiled.local_to_object_id)[local_id]
    objects = tuple(o.model_copy(update=updates) if o.id == target else o for o in compiled.objects)
    return _with_compiled(payload, objects=objects)


def _obj(payload: IntentGraphSynthesisDecidedPayload, local_id: str) -> Any:
    compiled = payload.compiled
    assert compiled is not None
    target = dict(compiled.local_to_object_id)[local_id]
    return next(o for o in compiled.objects if o.id == target)


def _tamper_cases(claim: str) -> dict[str, tuple[Any, str]]:
    from foundry.domain.common import Provenance, Relation

    req = _oid(K.REQUIREMENT, "req")
    return {
        "wrong durable object id": (
            lambda p: _with_object(p, "goal", id="GOAL-chosen"),
            "BINDING_OBJECT_SET",
        ),
        "wrong kind": (lambda p: _with_object(p, "goal", kind=K.OUTCOME), "BINDING_KIND"),
        "changed text": (
            lambda p: _with_object(p, "goal", statement="Something else."),
            "BINDING_TEXT",
        ),
        "changed mission": (
            lambda p: _with_object(p, "intent", mission="Another mission."),
            "BINDING_TEXT",
        ),
        "changed facet": (
            lambda p: _with_object(p, "con", facet=ConstraintFacet.PROJECT_BOUNDARY),
            "BINDING_TEXT",
        ),
        "wrong assumption risk": (
            lambda p: _with_object(p, "asm", risk_level=RiskLevel.CRITICAL),
            "BINDING_RISK",
        ),
        "wrong confidence": (
            lambda p: _with_object(p, "req", confidence=0.1),
            "BINDING_CONFIDENCE",
        ),
        "absent confidence invented": (
            lambda p: _with_object(p, "req2", confidence=1.0),
            "BINDING_CONFIDENCE",
        ),
        "wrong authority": (
            lambda p: _with_object(p, "goal", authority=Authority.PROPOSED),
            "BINDING_AUTHORITY",
        ),
        "wrong scope": (lambda p: _with_object(p, "goal", scope=()), "BINDING_SCOPE"),
        "wrong provenance": (
            lambda p: _with_object(
                p, "goal", provenance=Provenance(source_kind=SourceKind.SYSTEM, source_ref="x")
            ),
            "BINDING_PROVENANCE",
        ),
        "wrong timestamp": (
            lambda p: _with_object(p, "goal", created_at=datetime(2020, 1, 1, tzinfo=UTC)),
            "BINDING_CREATED_AT",
        ),
        "wrong revision": (lambda p: _with_object(p, "goal", revision=2), "BINDING_LIFECYCLE"),
        "wrong lifecycle": (
            lambda p: _with_object(p, "goal", lifecycle=LifecycleStatus.SUPERSEDED),
            "BINDING_LIFECYCLE",
        ),
        "missing relation": (lambda p: _with_object(p, "goal", relations=()), "BINDING_RELATIONS"),
        "extra relation": (
            lambda p: _with_object(
                p,
                "goal",
                relations=(
                    *_obj(p, "goal").relations,
                    Relation(relation_type=S, target_id="DEC-x"),
                ),
            ),
            "BINDING_RELATIONS",
        ),
        "wrong requirement pin": (
            lambda p: _with_object(p, "req", requires_metric=True),
            "BINDING_FIELDS",
        ),
        "wrong local mapping": (
            lambda p: _with_compiled(
                p,
                local_to_object_id=tuple(
                    (lid, "GOAL-other" if lid == "goal" else oid)
                    for lid, oid in p.compiled.local_to_object_id
                ),
            ),
            "BINDING_MAPPING",
        ),
        "duplicate local mapping": (
            lambda p: _with_compiled(
                p,
                local_to_object_id=(*p.compiled.local_to_object_id, ("goal", _oid(K.GOAL, "goal"))),
            ),
            "BINDING_MAPPING",
        ),
        "missing object": (
            lambda p: _with_compiled(p, objects=p.compiled.objects[1:]),
            "BINDING_OBJECT_SET",
        ),
        "extra object": (
            lambda p: _with_compiled(
                p, objects=(*p.compiled.objects, goal("GOAL-extra", scope=(SCOPE,)))
            ),
            "BINDING_OBJECT_SET",
        ),
        "duplicate object id": (
            lambda p: _with_compiled(p, objects=(*p.compiled.objects, p.compiled.objects[0])),
            "BINDING_OBJECT_SET",
        ),
        "wrong derivation parent": (
            lambda p: _with_compiled(
                p,
                derivation_parents=tuple(
                    x.model_copy(update={"parent_ids": ("DEC-x",)}) if x.object_id == req else x
                    for x in p.compiled.derivation_parents
                ),
            ),
            "BINDING_DERIVATION",
        ),
        "missing derivation parent": (
            lambda p: _with_compiled(
                p,
                derivation_parents=tuple(
                    x.model_copy(update={"parent_ids": x.parent_ids[:1]})
                    if x.object_id == req
                    else x
                    for x in p.compiled.derivation_parents
                ),
            ),
            "BINDING_DERIVATION",
        ),
        "extra derivation parent": (
            lambda p: _with_compiled(
                p,
                derivation_parents=tuple(
                    x.model_copy(update={"parent_ids": tuple(sorted({*x.parent_ids, "DEC-x"}))})
                    if x.object_id == req
                    else x
                    for x in p.compiled.derivation_parents
                ),
            ),
            "BINDING_DERIVATION",
        ),
        "missing gap": (lambda p: _with_compiled(p, gaps=()), "BINDING_GAP"),
        "changed gap": (
            lambda p: _with_compiled(
                p, gaps=tuple(g.model_copy(update={"blocking": False}) for g in p.compiled.gaps)
            ),
            "BINDING_GAP",
        ),
        "gap diagnosis changed": (
            lambda p: _with_compiled(
                p,
                gaps=tuple(
                    g.model_copy(update={"missing_need": MissingNeed.PROJECT_CHOICE})
                    for g in p.compiled.gaps
                ),
            ),
            "BINDING_GAP",
        ),
        "invented retirement": (
            lambda p: _with_compiled(
                p,
                retirements=(
                    RetirementPlanEntry(
                        retired_object_id="DEC-x",
                        replaced_by_object_id=req,
                        node_instance_id=_identity().node_instance_id("req"),
                    ),
                ),
            ),
            "BINDING_RETIREMENT",
        ),
        "compiled identity changed": (
            lambda p: _with_compiled(p, identity=_identity("RUN-other")),
            "BINDING_IDENTITY",
        ),
    }


_CASES = sorted(_tamper_cases("CLAIM").keys())


@pytest.mark.parametrize("case", _CASES)
def test_reducer_refuses_tampered_payloads(case: str) -> None:
    world, claim, before, env = _applied()
    mutate, code = _tamper_cases(claim)[case]
    tampered = raw_envelope(mutate(_payload_of(env)))
    with pytest.raises(ValueError, match=code):
        reduce(before, tampered)


def test_authority_invention_is_refused_on_replay() -> None:
    world, claim = _world()
    before = _state(world)
    graph = result(
        node(K.ASSUMPTION, "asm"),
        relations=(edge("asm", A, e("DEC-x")),),
    )
    payload = graph_payload(
        before,
        graph,
        author=MODEL,
        origin=SynthesisOrigin.AI_INFERRED,
        authority=Authority.PROPOSED,
    )
    invented = _with_object(payload, "asm", authority=Authority.CANONICAL).model_copy(
        update={
            "node_assignments": _assignments(
                graph, origin=SynthesisOrigin.AI_INFERRED, authority=Authority.CANONICAL
            )
        }
    )
    refused(before, raw_envelope(invented), "AUTHORITY_INVENTION")


def test_model_assumption_risk_must_be_high_on_replay() -> None:
    world, claim = _world()
    before = _state(world)
    graph = result(
        node(K.ASSUMPTION, "asm", proposed_risk_level=RiskLevel.LOW),
        relations=(edge("asm", A, e("DEC-x")),),
    )
    payload = graph_payload(
        before,
        graph,
        author=MODEL,
        origin=SynthesisOrigin.AI_INFERRED,
        authority=Authority.PROPOSED,
    )
    compiled = payload.compiled
    assert compiled is not None
    assert compiled.objects[0].risk_level is RiskLevel.HIGH  # type: ignore[union-attr]
    lowered = _with_object(payload, "asm", risk_level=RiskLevel.LOW)
    refused(before, raw_envelope(lowered), "BINDING_RISK")


def test_origin_must_follow_the_author_on_replay() -> None:
    world, claim, before, env = _applied()
    payload = _payload_of(env)
    forged = payload.model_copy(
        update={
            "node_assignments": _assignments(
                payload.result, origin=SynthesisOrigin.AI_INFERRED, authority=Authority.CANONICAL
            )
        }
    )
    refused(before, raw_envelope(forged), "ORIGIN_AUTHOR_MISMATCH")


def test_pre_existing_object_id_is_refused() -> None:
    world, claim, before, env = _applied()
    world.legacy(goal(_oid(K.GOAL, "goal"), scope=(SCOPE,)))
    refused(_state(world), env, "OBJECT_ALREADY_EXISTS")


def test_pre_existing_gap_id_is_refused() -> None:
    world, claim, before, env = _applied()
    gap_id = _identity().gap_id("g-premise")
    from foundry.domain.events import GapPayload
    from foundry.domain.gaps import Gap

    world.store.append(
        EventEnvelope(
            event_id="EVT-gap-first",
            project_id=PROJECT,
            event_type=EventType.GAP_RECORDED,
            occurred_at=AT,
            payload=GapPayload(
                gap=Gap(
                    id=gap_id,
                    project_id=PROJECT,
                    kind=GapKind.AMBIGUITY,
                    description="d",
                    materiality="LOW",
                    risk="LOW",
                    affected_object_ids=(),
                    blocking=True,
                )
            ),
        ),
        expected_sequence=world.store.current_sequence(PROJECT),
    )
    refused(_state(world), env, "GAP_ALREADY_EXISTS")


def test_unresolved_existing_or_claim_reference_is_refused() -> None:
    world, claim, before, env = _applied()
    payload = _payload_of(env)
    ghost_graph = result(
        node(K.GOAL, "goal"),
        node(K.INTENT, "intent"),
        relations=(edge("goal", S, "intent"), edge("goal", D, b("CLAIM-ghost"))),
    )
    ghost = payload.model_copy(
        update={
            "result": ghost_graph,
            "node_assignments": _assignments(
                ghost_graph, origin=SynthesisOrigin.HUMAN_STATED, authority=Authority.CANONICAL
            ),
        }
    )
    refused(before, raw_envelope(ghost), "UNRESOLVED_REFERENCE")


@pytest.mark.parametrize("which", ["nodes", "gaps"])
def test_caps_are_rechecked_on_replay(which: str) -> None:
    world, claim, before, env = _applied()
    payload = _payload_of(env)
    if which == "nodes":
        extra = tuple(node(K.GOAL, f"cap{i}") for i in range(33))
        oversized = payload.result.model_copy(update={"nodes": extra})
    else:
        extra_gaps = tuple(gap(f"cap{i}") for i in range(17))
        oversized = payload.result.model_copy(update={"gaps": extra_gaps})
    refused(before, raw_envelope(payload.model_copy(update={"result": oversized})), "MAX_GRAPH")


def test_record_shape_is_shared_with_the_payload() -> None:
    world, claim, before, env = _applied()
    payload = _payload_of(env)
    with pytest.raises(ValidationError, match="APPLY"):
        IntentGraphDecisionRecord(
            identity=payload.identity,
            author=payload.author,
            run_scope=payload.run_scope,
            result=payload.result,
            node_assignments=payload.node_assignments,
            decision=payload.decision,
            compiled=None,
            decision_event_id=env.event_id,
            decided_at=AT,
        )


def test_compiled_graph_requires_covering_derivation_parents() -> None:
    world, claim, before, env = _applied()
    compiled = _payload_of(env).compiled
    assert compiled is not None
    with pytest.raises(ValidationError, match="derivation_parents"):
        CompiledIntentGraph.model_validate(
            {
                **compiled.model_dump(),
                "derivation_parents": compiled.model_dump()["derivation_parents"][1:],
            }
        )

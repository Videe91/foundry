"""Authority routing (design 2026-09-30): pending authority work is discoverable, resolvable at
any time by an authenticated human, never lost, never duplicated, never auto-approved.

Small governed worlds prove the laws; the frozen long-horizon run (``a0ee2f7``, read only)
proves the mechanism on the real history: the checkpoint-free resolution of T8's N:M
correction, the T9 that follows, and the T13 supersessions that 9P3's checkpoint schedule
left pending for good.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.authority_routing import (
    AUTHORITY_ROUTING_VERSION,
    AuthorityWorkNotPending,
    StaleAuthorityDecision,
    agree,
    list_authority_work,
)
from foundry.application.intent_graph_synthesis_context import compile_intent_graph_context
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.authority_work import authority_routing_findings, authority_work
from foundry.domain.common import Authority
from foundry.domain.events import EventEnvelope, EventType, SemanticJudgmentPayload
from foundry.domain.semantic_judgment import (
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_view import derive_view
from tests.unit._ie21_fixtures import ALICE, PROJECT
from tests.unit._ie22b_fixtures import EVIDENCE_ID, World

AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v6")
_IDS = count(1)


def _ids(prefix: str) -> str:
    return f"{prefix}-AR-{next(_IDS):05d}"


def _model_supersede(world: World, target: str, reasoner: ReasonerFingerprint = MODEL) -> str:
    jid = _ids("JDG")
    decision = world.governor.submit(
        SemanticJudgment(
            judgment_id=jid,
            project_id=PROJECT,
            proposal=SupersedeProposal(target_judgment_id=target, reason="corrected"),
            visible_evidence_ids=(EVIDENCE_ID,),
            rationale="the model's correction",
            reasoner=reasoner,
            invocation_id=_ids("INV"),
            proposed_at=AT,
        )
    )
    assert decision.route.value == "REQUIRE_SECOND_LENS", decision
    return jid


def _pending_world() -> tuple[World, str, str]:
    world = World()
    old = world.claim("J-old", authority=Authority.INFERRED, text="thirty days")
    pending = _model_supersede(world, "J-old")
    return world, old, pending


def _agree(
    governor: SemanticGovernor, work: str, *, actor: str = ALICE, seq: int | None = None
) -> Any:
    return agree(
        governor,
        work_id=work,
        human_actor_id=actor,
        expected_sequence=governor.state().last_sequence if seq is None else seq,
        rationale="the correction is right",
        clock=lambda: AT,
        id_factory=_ids,
    )


def _live(governor: SemanticGovernor) -> set[str]:
    return set(derive_view(governor.state().semantic).effective_evidence)


# --------------------------------------------------------------------------- routing


def test_1_a_pending_correction_is_discoverable_authority_work() -> None:
    world, old, pending = _pending_world()
    queue = list_authority_work(world.governor)
    (item,) = queue.items
    assert item.pending_judgment_ids == (pending,)
    assert item.kind == "SUPERSEDE" and item.target_judgment_id == "J-old"
    assert item.target_claim_ids == (old,)
    assert item.required_resolution == "HUMAN_AUTHORITY_OR_INDEPENDENT_LENS"
    assert item.proposed_by == ("xai:grok-4.6@intent-v2-locus-v6",)
    assert item.evidence_ids == (EVIDENCE_ID,)
    assert world.address_id in item.address_ids
    assert queue.as_of_sequence == world.governor.state().last_sequence
    assert authority_routing_findings(world.governor.state(), queue) == ()


def test_listing_writes_nothing() -> None:
    world, _, _ = _pending_world()
    before = world.store.current_sequence(PROJECT)
    list_authority_work(world.governor)
    list_authority_work(world.governor)
    assert world.store.current_sequence(PROJECT) == before


def test_the_work_id_is_stable_across_replay_and_later_writes() -> None:
    world, _, _ = _pending_world()
    first = list_authority_work(world.governor).items[0].work_id
    world.claim("J-other", authority=Authority.INFERRED, text="an unrelated rule")
    again = authority_work(replay(PROJECT, world.store.load(PROJECT)))
    assert [i.work_id for i in again.items] == [first]


def test_a_repeated_proposal_is_one_obligation_and_one_agree_satisfies_both() -> None:
    world, old, first = _pending_world()
    second = _model_supersede(world, "J-old")
    (item,) = list_authority_work(world.governor).items
    assert item.pending_judgment_ids == tuple(sorted((first, second)))
    resolution = _agree(world.governor, item.work_id)
    assert resolution.resolved and list_authority_work(world.governor).items == ()
    assert old not in _live(world.governor)


def test_an_unrouted_judgment_is_reported_as_lost_not_pending() -> None:
    world = World()
    world.claim("J-old", authority=Authority.INFERRED)
    judgment = SemanticJudgment(
        judgment_id="JDG-NEVER-ADMITTED",
        project_id=PROJECT,
        proposal=SupersedeProposal(target_judgment_id="J-old", reason="x"),
        visible_evidence_ids=(),
        rationale="r",
        reasoner=MODEL,
        invocation_id="INV-X",
        proposed_at=AT,
    )
    world.store.append(
        EventEnvelope(
            event_id="judgment-unrouted",
            project_id=PROJECT,
            event_type=EventType.SEMANTIC_JUDGMENT_RECORDED,
            occurred_at=AT,
            payload=SemanticJudgmentPayload(judgment=judgment),
        ),
        expected_sequence=world.store.current_sequence(PROJECT),
    )
    queue = list_authority_work(world.governor)
    assert queue.items == ()
    assert queue.unrouted_judgment_ids == ("JDG-NEVER-ADMITTED",)
    assert authority_routing_findings(world.governor.state(), queue) == ()


# --------------------------------------------------------------------------- decision


def test_4_an_authorized_agree_resolves_it_and_it_leaves_the_queue() -> None:
    world, old, pending = _pending_world()
    (item,) = list_authority_work(world.governor).items
    resolution = _agree(world.governor, item.work_id)
    assert (resolution.route, resolution.reasons, resolution.resolved) == (
        "APPLY",
        ("HUMAN_AUTHORITY",),
        True,
    )
    assert old not in _live(world.governor)
    assert list_authority_work(world.governor).items == ()
    agreed = world.governor.state().semantic.judgments[resolution.agree_judgment_id]
    assert agreed.reasoner == ReasonerFingerprint(
        provider="human", model=ALICE, policy_version=AUTHORITY_ROUTING_VERSION
    )
    assert agreed.proposal == world.governor.state().semantic.judgments[pending].proposal


def test_8_a_duplicate_agree_is_refused_and_writes_nothing() -> None:
    world, _, _ = _pending_world()
    (item,) = list_authority_work(world.governor).items
    _agree(world.governor, item.work_id)
    before = world.store.current_sequence(PROJECT)
    with pytest.raises(AuthorityWorkNotPending):
        _agree(world.governor, item.work_id)
    assert world.store.current_sequence(PROJECT) == before


def test_9_two_decisions_taken_on_one_version_cannot_both_land() -> None:
    world, _, _ = _pending_world()
    queue = list_authority_work(world.governor)
    (item,) = queue.items
    _agree(world.governor, item.work_id, seq=queue.as_of_sequence)
    before = world.store.current_sequence(PROJECT)
    with pytest.raises(StaleAuthorityDecision):
        _agree(world.governor, item.work_id, seq=queue.as_of_sequence)
    assert world.store.current_sequence(PROJECT) == before


def test_a_stale_decision_after_unrelated_progress_is_refused() -> None:
    world, _, _ = _pending_world()
    queue = list_authority_work(world.governor)
    world.claim("J-late", authority=Authority.INFERRED, text="later rule")
    with pytest.raises(StaleAuthorityDecision):
        _agree(world.governor, queue.items[0].work_id, seq=queue.as_of_sequence)
    assert len(list_authority_work(world.governor).items) == 1


def test_an_unknown_work_id_is_refused() -> None:
    world, _, _ = _pending_world()
    with pytest.raises(AuthorityWorkNotPending):
        _agree(world.governor, "AUTH-000000000000000000000000")


@pytest.mark.parametrize("actor", ["xai:grok-4.6", "grok-4.6", "openai/gpt-6-astra", ""])
def test_18_no_model_can_decide_authority(actor: str) -> None:
    world, old, _ = _pending_world()
    (item,) = list_authority_work(world.governor).items
    before = world.store.current_sequence(PROJECT)
    with pytest.raises(ValueError, match="human principal"):
        _agree(world.governor, item.work_id, actor=actor)
    assert world.store.current_sequence(PROJECT) == before and old in _live(world.governor)


def test_18_the_proposing_model_repeating_itself_never_approves() -> None:
    world, old, _ = _pending_world()
    _model_supersede(world, "J-old")  # same fingerprint: never an independent lens
    assert old in _live(world.governor)
    assert len(list_authority_work(world.governor).items) == 1


def test_19_nothing_is_approved_without_a_decision() -> None:
    world, old, _ = _pending_world()
    for _ in range(3):
        n = next(_IDS)
        world.claim(f"J-noise-{n}", authority=Authority.INFERRED, text=f"noise {n}")
        list_authority_work(world.governor)
    assert old in _live(world.governor)
    assert len(list_authority_work(world.governor).items) == 1


def test_5_there_is_no_decline_decision_in_the_domain() -> None:
    import foundry.application.authority_routing as routing

    assert not any(n for n in routing.__all__ if "disagree" in n.lower() or "reject" in n.lower())


def test_6_14_pending_work_survives_unrelated_work_which_proceeds_normally() -> None:
    world, old, _ = _pending_world()
    other = world.claim("J-unrelated", authority=Authority.INFERRED, text="an unrelated rule")
    assert other in _live(world.governor) and old in _live(world.governor)
    assert len(list_authority_work(world.governor).items) == 1


def test_7_20_replay_yields_the_identical_authority_state() -> None:
    world, _, _ = _pending_world()
    live = authority_work(world.governor.state())
    replayed = authority_work(replay(PROJECT, world.store.load(PROJECT)))
    assert live == replayed


def test_a_human_only_hold_is_not_resolved_by_an_unauthorized_human() -> None:
    """Admission decides: a REQUIRE_HUMAN hold (a canonical claim without covering authority)
    stays pending when a human with no AuthorityRecord agrees, and resolves under authority."""
    from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind
    from foundry.domain.semantic_judgment import AssertClaimProposal

    world = World()
    bob = ReasonerFingerprint(provider="human", model="human://bob", policy_version="p1")
    decision = world.governor.submit(
        SemanticJudgment(
            judgment_id="J-bob-canon",
            project_id=PROJECT,
            proposal=AssertClaimProposal(
                address_id=world.address_id,
                predicate="refund_window",
                value=ClaimValue(kind=ClaimValueKind.TEXT, text="fourteen days"),
                evidence_ids=(EVIDENCE_ID,),
                authority=Authority.CANONICAL,
            ),
            visible_evidence_ids=(EVIDENCE_ID,),
            rationale="bob states it",
            reasoner=bob,
            invocation_id="INV-bob",
            proposed_at=AT,
        ),
        human_actor_id="human://bob",
    )
    assert decision.route.value == "REQUIRE_HUMAN"
    (item,) = list_authority_work(world.governor).items
    assert item.required_resolution == "HUMAN_AUTHORITY"
    unresolved = _agree(world.governor, item.work_id, actor="human://carol")
    assert (unresolved.route, unresolved.resolved) == ("REQUIRE_HUMAN", False)
    (still,) = list_authority_work(world.governor).items
    assert still.work_id == item.work_id and len(still.pending_judgment_ids) == 2
    resolved = _agree(world.governor, item.work_id)
    assert resolved.resolved and list_authority_work(world.governor).items == ()


def test_the_invariant_finds_invisible_duplicate_and_orphan_work() -> None:
    world, _, pending = _pending_world()
    state = world.governor.state()
    queue = authority_work(state)
    (item,) = queue.items
    assert any(
        f.startswith("INVISIBLE_PENDING")
        for f in authority_routing_findings(state, queue.model_copy(update={"items": ()}))
    )
    doubled = queue.model_copy(update={"items": (item, item)})
    found = authority_routing_findings(state, doubled)
    assert any(f.startswith("DUPLICATE_WORK:") for f in found)
    assert any(f.startswith("DUPLICATE_WORK_ID") for f in found)
    orphan = item.model_copy(update={"pending_judgment_ids": ("J-old",)})
    found = authority_routing_findings(state, queue.model_copy(update={"items": (orphan,)}))
    assert any(f.startswith("ORPHAN_WORK") for f in found)
    assert any(f.startswith("INVISIBLE_PENDING") and pending in f for f in found)


# --------------------------------------------------------------------------- the frozen run


RUN_PATH = "docs/superpowers/experiments/2026-09-29-ie2-ie3-long-horizon-v1/run.json"
ARCHITECT = "human://architect"


@pytest.fixture(scope="module")
def frozen() -> Any:
    from pathlib import Path

    from foundry.experiments.long_horizon_ie2_ie3.runner import RunRecord

    raw = json.loads(Path(RUN_PATH).read_text())
    raw.pop("started_at", None)
    raw.pop("finished_at", None)
    return RunRecord.model_validate(raw)


def _state_at(run: Any, seq: int) -> Any:
    return replay(run.project_id, [e for e in run.events if e.sequence <= seq])


def _governor_at(run: Any, seq: int) -> SemanticGovernor:
    store = InMemoryEventStore()
    for stored in run.events:
        if stored.sequence <= seq:
            store.append(stored.event, expected_sequence=stored.sequence - 1)
    return SemanticGovernor(
        store=store,
        project_id=run.project_id,
        policy=AdmissionPolicy(canonical_facets=True),
        clock=lambda: AT,
        id_factory=_ids,
    )


def test_12_13_every_frozen_boundary_satisfies_the_routing_invariant(frozen: Any) -> None:
    for turn in frozen.turns:
        for seq in (turn.seq_after_ie2, turn.seq_after_authority, turn.seq_after_ie3):
            state = _state_at(frozen, seq)
            assert authority_routing_findings(state, authority_work(state)) == (), (turn.t, seq)


def test_11_historical_checkpoint_agrees_resolve_the_projected_work(frozen: Any) -> None:
    t3 = frozen.turns[2]
    before = authority_work(_state_at(frozen, t3.seq_after_ie2))
    after = authority_work(_state_at(frozen, t3.seq_after_authority))
    assert len(before.items) == 3 and after.items == ()


def test_16_the_t13_off_checkpoint_supersessions_are_work_and_stay_work(frozen: Any) -> None:
    ids_by_turn = {
        t.t: [i.work_id for i in authority_work(_state_at(frozen, t.seq_after_authority)).items]
        for t in frozen.turns[12:]
    }
    assert len(ids_by_turn[13]) == 4
    assert ids_by_turn[13] == ids_by_turn[14] == ids_by_turn[15] == ids_by_turn[16]


def test_16_17_resolving_the_t13_work_later_frees_the_blocked_concerns(frozen: Any) -> None:
    last = frozen.turns[-1].seq_after_ie3
    governor = _governor_at(frozen, last)
    blocked = compile_intent_graph_context(governor.state(), scope="orion-jobs").request
    assert blocked is not None
    before_addresses = {a for locus in blocked.basis for a in locus.address_ids}
    queue = list_authority_work(governor)
    targets = {c for i in queue.items for c in i.target_claim_ids}
    assert len(queue.items) == 4 and targets & _live(governor) == targets
    assert not targets & {c.claim_id for locus in blocked.basis for c in locus.live_claims}
    for item in queue.items:
        resolution = _agree(governor, item.work_id, actor=ARCHITECT)
        assert resolution.resolved and resolution.reasons == ("HUMAN_AUTHORITY",)
    assert list_authority_work(governor).items == ()
    assert not targets & _live(governor)
    freed = compile_intent_graph_context(governor.state(), scope="orion-jobs").request
    assert freed is not None
    after_addresses = {a for locus in freed.basis for a in locus.address_ids}
    assert before_addresses < after_addresses and len(after_addresses) == 9
    assert not targets & {c.claim_id for locus in freed.basis for c in locus.live_claims}


def test_17_while_work_is_pending_ie3_is_shown_only_settled_concerns(frozen: Any) -> None:
    t13 = frozen.turns[12]
    state = _state_at(frozen, t13.seq_after_authority)
    request = compile_intent_graph_context(state, scope="orion-jobs").request
    assert request is not None
    shown = {a for locus in request.basis for a in locus.address_ids}
    pending_addresses = {a for i in authority_work(state).items for a in i.address_ids}
    assert pending_addresses and not shown & pending_addresses
    assert len(shown) == 6, "three of the nine addresses carry pending work and are withheld"


# ---------------------------------------------------------------- T8 -> T9, checkpoint-free


def test_2_3_15_t8s_nm_correction_resolves_through_generic_routing_and_t9_proceeds() -> None:
    from tests.unit import test_correction_set_policy as cs

    mp = pytest.MonkeyPatch()
    transport = cs._Transport()
    mp.setattr(cs.mod, "Client", transport.client())
    try:
        world = cs._World()
        before = world.live()
        cs._assimilate(world, 8, [world.reply(8, 1), world.reply(8, 2)], transport)
        queue = list_authority_work(world.governor)
        assert {i.target_judgment_id[:12] for i in queue.items} == cs.T8_OBSOLETE
        assert all(i.kind == "SUPERSEDE" for i in queue.items) and len(queue.items) == 3
        wait = next(i for i in queue.items if i.target_judgment_id.startswith("JDG-cf225a3b"))
        cap = next(i for i in queue.items if i.target_judgment_id.startswith("JDG-6dc43a9d"))
        assert cap.pending_judgment_ids[0] in wait.correction_context_judgment_ids
        assert authority_routing_findings(world.governor.state(), queue) == ()
        for item in queue.items:
            assert _agree(world.governor, item.work_id, actor=ARCHITECT).resolved
        after = world.live()
        assert {c.created_by_judgment_id[:12] for cid, c in before.items() if cid not in after} == (
            cs.T8_OBSOLETE
        )
        outcome = cs._assimilate(
            world, 9, [world.reply(9, 1), cs._t9_reply(world, before)], transport
        )
        assert outcome.calls_made == 2 and list_authority_work(world.governor).items == ()
    finally:
        mp.undo()

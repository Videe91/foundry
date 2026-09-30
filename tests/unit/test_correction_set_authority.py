"""Atomic correction-set authority (design 2026-09-30, architecture Option B, protocol
``ie2-authority-routing-v2``).

One response's correction of one address -- every ASSERT at that address and every SUPERSEDE of
a claim there -- is decided as one unit: PENDING (nothing of it current, the pre-correction
state current, discoverable work), AGREED (all members applied in one event) or DECLINED
(nothing applied, durable, no longer blocking). No partial outcome exists.

Small governed worlds prove the laws; the frozen long-horizon run (``a0ee2f7``, read only)
proves them on real history: T8's N:M correction, T13's concern D (whose correcting claims the
v1 law applied beside the rule they contradict) and the T8 -> T9 cascade. No live call is made.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.authority_routing import (
    AUTHORITY_ROUTING_V2,
    AUTHORITY_ROUTING_VERSION,
    AuthorityWorkNotPending,
    DeclineRefused,
    StaleAuthorityDecision,
    UnauthorizedAuthorityDecision,
    agree,
    decide_correction_set,
    decline,
    list_authority_work,
)
from foundry.application.intent_graph_synthesis_context import compile_intent_graph_context
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.authority_work import authority_routing_findings, authority_work
from foundry.domain.common import Authority, SourceKind
from foundry.domain.correction_set import (
    CORRECTION_DECLINED,
    CORRECTION_SET_INVALID,
    CORRECTION_SET_MEMBER,
    CORRECTION_SET_REPEAT,
    correction_set_id,
    equivalence_key,
)
from foundry.domain.events import CorrectionSetDecidedPayload, EventType
from foundry.domain.evidence import evidence_item, sha256_of_content
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_view import derive_view
from foundry.ports.semantic_reasoner import ReasoningRequest
from tests.unit._ie21_fixtures import ALICE, PROJECT, SCOPE
from tests.unit._ie22b_fixtures import EVIDENCE_ID, World

AT = datetime(2026, 9, 30, 15, 0, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v6")
OTHER_MODEL = ReasonerFingerprint(
    provider="openai", model="gpt-6-astra", policy_version="intent-v2-locus-v6"
)
V2 = AdmissionPolicy(correction_sets=True)
_IDS = count(1)


def _ids(prefix: str) -> str:
    return f"{prefix}-CS-{next(_IDS):05d}"


class _Scripted:
    """A non-human reasoner returning one scripted response."""

    def __init__(self, judgments: tuple[SemanticJudgment, ...], fp: ReasonerFingerprint) -> None:
        self.judgments = judgments
        self.fingerprint = fp

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        return self.judgments


class _W:
    """A small governed world: one human-asserted claim at one address, a v2 governor."""

    def __init__(self) -> None:
        self.world = World()
        self.store = self.world.store
        self.old = self.world.claim("J-old", authority=Authority.INFERRED, text="thirty days")
        self.governor = SemanticGovernor(
            store=self.store, project_id=PROJECT, policy=V2, clock=lambda: AT, id_factory=_ids
        )
        self.address = self.world.address_id

    def evidence(self, content: str) -> str:
        eid = _ids("EV")
        self.governor.ingest(
            evidence_item(
                evidence_id=eid,
                project_id=PROJECT,
                source_kind=SourceKind.HUMAN,
                source_ref=ALICE,
                content=content,
                observed_at=AT,
                scope=(SCOPE,),
            )
        )
        return eid

    def judgment(self, proposal: Any, invocation: str, fp: ReasonerFingerprint) -> SemanticJudgment:
        return SemanticJudgment(
            judgment_id=_ids("JDG"),
            project_id=PROJECT,
            proposal=proposal,
            visible_evidence_ids=(EVIDENCE_ID,),
            rationale="the model's correction",
            reasoner=fp,
            invocation_id=invocation,
            proposed_at=AT,
        )

    def assertion(
        self, text: str, evidence: str, predicate: str = "refund_window"
    ) -> AssertClaimProposal:
        return AssertClaimProposal(
            address_id=self.address,
            predicate=predicate,
            value=ClaimValue(kind=ClaimValueKind.TEXT, text=text),
            evidence_ids=(evidence,),
            authority=Authority.INFERRED,
        )

    def respond(self, *proposals: Any, fp: ReasonerFingerprint = MODEL) -> Any:
        invocation = _ids("INV")
        judgments = tuple(self.judgment(p, invocation, fp) for p in proposals)
        decisions = self.governor.propose_and_submit(
            _Scripted(judgments, fp), ReasoningRequest(project_id=PROJECT, evidence=())
        )
        return invocation, judgments, decisions

    def correct(self, text: str = "fourteen days", content: str = "Refunds: fourteen days.") -> Any:
        """The standard 1:1 correction: a new claim and the retirement of the old one."""
        ev = self.evidence(content)
        return self.respond(
            self.assertion(text, ev), SupersedeProposal(target_judgment_id="J-old", reason="x")
        )

    def state(self) -> Any:
        return self.governor.state()

    def live(self) -> set[str]:
        return set(derive_view(self.state().semantic).effective_evidence)

    def pending(self) -> tuple[str, ...]:
        return derive_view(self.state().semantic).pending_judgment_ids

    def seq(self) -> int:
        return self.store.current_sequence(PROJECT)


def _decide(w: Any, work: str, outcome: Any, *, actor: str = ALICE, seq: int | None = None) -> Any:
    return decide_correction_set(
        w.governor,
        work_id=work,
        outcome=outcome,
        human_actor_id=actor,
        expected_sequence=w.governor.state().last_sequence if seq is None else seq,
        rationale="decided on the evidence",
    )


def _only_set(w: Any) -> Any:
    (item,) = list_authority_work(w.governor).correction_sets
    return item


# ------------------------------------------------------------------- 1-4 PENDING


def test_1_a_correction_is_pending_whole_and_nothing_of_it_is_current() -> None:
    w = _W()
    _, judgments, decisions = w.correct()
    assert [d.route for d in decisions] == [AdmissionRoute.REQUIRE_HUMAN] * 2
    assert all(d.reasons[0] == CORRECTION_SET_MEMBER for d in decisions)
    assert w.live() == {w.old}, "the pre-correction state stays current"
    assert set(w.pending()) == {j.judgment_id for j in judgments}


def test_2_the_pending_set_is_one_discoverable_work_item_and_no_edge_item() -> None:
    w = _W()
    invocation, judgments, _ = w.correct()
    queue = list_authority_work(w.governor)
    assert queue.items == (), "no member is decidable as a separate edge"
    (item,) = queue.correction_sets
    assert item.work_id == correction_set_id(PROJECT, invocation, w.address)
    assert item.assertion_judgment_ids == (judgments[0].judgment_id,)
    assert item.supersede_judgment_ids == (judgments[1].judgment_id,)
    assert item.target_judgment_ids == ("J-old",) and item.target_claim_ids == (w.old,)
    assert item.required_resolution == "HUMAN_AUTHORITY" and item.status == "PENDING"
    assert item.proposed_by == "xai:grok-4.6@intent-v2-locus-v6"
    assert item.invocation_id == invocation and item.address_id == w.address
    assert authority_routing_findings(w.state(), queue) == ()


def test_3_listing_writes_nothing_and_replay_reproduces_the_work() -> None:
    w = _W()
    w.correct()
    before = w.seq()
    live = list_authority_work(w.governor)
    list_authority_work(w.governor)
    assert w.seq() == before
    assert authority_work(replay(PROJECT, w.store.load(PROJECT))) == live


def test_4_the_whole_address_is_held_including_a_compatible_assertion() -> None:
    """Judgments carry no proposition id, so a compatible ASSERT at a corrected address cannot
    be told from a correcting one without guessing: it is held with the set."""
    w = _W()
    ev = w.evidence("Refunds: fourteen days; refunds go to the original card.")
    _, judgments, _ = w.respond(
        w.assertion("fourteen days", ev),
        w.assertion("original card", ev, predicate="refund_destination"),
        SupersedeProposal(target_judgment_id="J-old", reason="x"),
    )
    item = _only_set(w)
    assert item.assertion_judgment_ids == (judgments[0].judgment_id, judgments[1].judgment_id)
    assert w.live() == {w.old}


def test_5_ordinary_judgments_of_the_same_response_follow_the_ordinary_law() -> None:
    """A SUPPORT (of the still-current claim) and an ASSERT at an uncorrected address apply."""
    w = _W()
    from foundry.domain.semantic_identity import SemanticCandidate
    from foundry.domain.semantic_judgment import CreateAddressProposal
    from tests.unit._ie21_fixtures import HUMAN

    decision = w.governor.submit(
        SemanticJudgment(
            judgment_id="J-address-2",
            project_id=PROJECT,
            proposal=CreateAddressProposal(
                candidate=SemanticCandidate(
                    candidate_id="CAND-dest",
                    subject="Refund destination",
                    facet="Where does a refund go?",
                    scope=(SCOPE,),
                    evidence_ids=(EVIDENCE_ID,),
                )
            ),
            visible_evidence_ids=(EVIDENCE_ID,),
            rationale="r",
            reasoner=HUMAN,
            invocation_id="INV-address-2",
            proposed_at=AT,
        ),
        human_actor_id=ALICE,
    )
    assert decision.route is AdmissionRoute.APPLY
    from foundry.application.semantic_reducer import address_id_for

    other = address_id_for(PROJECT, "J-address-2")
    ev = w.evidence("Refunds: fourteen days, to the original card.")
    unrelated = AssertClaimProposal(
        address_id=other,
        predicate="refund_destination",
        value=ClaimValue(kind=ClaimValueKind.TEXT, text="original card"),
        evidence_ids=(ev,),
        authority=Authority.INFERRED,
    )
    support = SupportsClaimProposal(claim_id=w.old, evidence_ids=(ev,))
    _, judgments, decisions = w.respond(
        unrelated,
        w.assertion("fourteen days", ev),
        support,
        SupersedeProposal(target_judgment_id="J-old", reason="x"),
    )
    routes = {j.judgment_id: d for j, d in zip(judgments, decisions, strict=True)}
    assert routes[judgments[0].judgment_id].reasons == ("LOW_RISK",)
    assert routes[judgments[2].judgment_id].route is AdmissionRoute.APPLY
    assert claim_id_for(PROJECT, judgments[0].judgment_id) in w.live()
    assert _only_set(w).assertion_judgment_ids == (judgments[1].judgment_id,)


# ------------------------------------------------------------------- 6-9 AGREE / DECLINE


def test_6_agree_applies_every_member_in_one_event() -> None:
    w = _W()
    _, judgments, _ = w.correct()
    item = _only_set(w)
    resolution = _decide(w, item.work_id, "AGREE")
    assert (resolution.status, resolution.applied_judgment_ids) == (
        "AGREED",
        tuple(j.judgment_id for j in judgments),
    )
    new = claim_id_for(PROJECT, judgments[0].judgment_id)
    assert w.live() == {new} and w.pending() == ()
    last = w.store.load(PROJECT)[-1]
    assert last.event.event_type is EventType.CORRECTION_SET_DECIDED
    assert w.seq() == last.sequence, "one event carried the whole transition"
    payload = last.event.payload
    assert isinstance(payload, CorrectionSetDecidedPayload)
    assert payload.authority_protocol == AUTHORITY_ROUTING_V2 == "ie2-authority-routing-v2"
    assert list_authority_work(w.governor).correction_sets == ()
    (resolved,) = list_authority_work(w.governor).resolved_correction_sets
    assert resolved.status == "AGREED" and resolved.decided_by == ALICE


def test_7_agree_mints_one_version_of_the_final_state_and_no_partial_snapshot() -> None:
    w = _W()
    _, judgments, _ = w.correct()
    resolution = _decide(w, _only_set(w).work_id, "AGREE")
    semantic = w.state().semantic
    minted = [
        v
        for v in semantic.issue_versions.values()
        if v.created_by_event_id == resolution.decision_event_id
    ]
    assert len(minted) == 1
    assert minted[0].claim_ids == (claim_id_for(PROJECT, judgments[0].judgment_id),)
    assert semantic.issue_heads[w.address] == minted[0].version_id


def test_8_the_agreed_version_goes_stale_when_any_member_is_later_superseded() -> None:
    w = _W()
    _, judgments, _ = w.correct()
    resolution = _decide(w, _only_set(w).work_id, "AGREE")
    (version,) = [
        v.version_id
        for v in w.state().semantic.issue_versions.values()
        if v.created_by_event_id == resolution.decision_event_id
    ]
    assert version not in derive_view(w.state().semantic).stale_ids
    w.world.supersede(_ids("J-human"), judgments[0].judgment_id)  # the ASSERT, not the creator
    assert version in derive_view(w.state().semantic).stale_ids


def test_9_decline_applies_nothing_is_durable_and_unblocks_the_concern() -> None:
    w = _W()
    w.correct()
    item = _only_set(w)
    resolution = decline(
        w.governor,
        work_id=item.work_id,
        human_actor_id=ALICE,
        expected_sequence=w.seq(),
        rationale="the old window stands",
    )
    assert (resolution.status, resolution.applied_judgment_ids) == ("DECLINED", ())
    assert w.live() == {w.old} and w.pending() == ()
    queue = list_authority_work(w.governor)
    assert queue.correction_sets == () and queue.items == ()
    replayed = replay(PROJECT, w.store.load(PROJECT)).semantic.correction_sets[item.work_id]
    assert replayed.status == "DECLINED" and replayed.rationale == "the old window stands"


# ------------------------------------------------------------------- 10-13 no mixed outcome


@pytest.mark.parametrize(("first", "second"), [("AGREE", "DECLINE"), ("DECLINE", "AGREE")])
def test_10_the_first_terminal_decision_wins_and_the_second_writes_nothing(
    first: Any, second: Any
) -> None:
    w = _W()
    w.correct()
    item = _only_set(w)
    _decide(w, item.work_id, first)
    live, seq = w.live(), w.seq()
    with pytest.raises(AuthorityWorkNotPending):
        _decide(w, item.work_id, second)
    with pytest.raises(ValueError, match="already"):
        w.governor.decide_correction_set(
            item.work_id,
            second,
            human_actor_id=ALICE,
            authority_record_id="AUTH-project",
            rationale="late",
        )
    assert (w.live(), w.seq()) == (live, seq)


def test_11_racing_decisions_on_one_version_cannot_both_land() -> None:
    w = _W()
    w.correct()
    item = _only_set(w)
    seen = w.seq()
    _decide(w, item.work_id, "DECLINE", seq=seen)
    with pytest.raises(StaleAuthorityDecision):
        _decide(w, item.work_id, "AGREE", seq=seen)
    assert w.live() == {w.old}


def test_12_no_edge_of_a_set_can_be_taken_apart() -> None:
    """Legacy AGREE refuses a set; an independent lens never corroborates a member; a human
    re-proposing one member's edge applies it only by ordinary law and the set then cannot
    apply whole (refused, nothing written) -- it can still be declined."""
    w = _W()
    _, judgments, _ = w.correct()
    item = _only_set(w)
    with pytest.raises(AuthorityWorkNotPending, match="decided whole"):
        agree(
            w.governor,
            work_id=item.work_id,
            human_actor_id=ALICE,
            expected_sequence=w.seq(),
            rationale="r",
            clock=lambda: AT,
            id_factory=_ids,
        )
    lens = w.judgment(judgments[1].proposal, _ids("INV"), OTHER_MODEL)
    solo = SemanticGovernor(
        store=w.store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: AT,
        id_factory=_ids,
    )
    assert solo.submit(lens).route is AdmissionRoute.REQUIRE_SECOND_LENS, "members are no lens"
    assert w.live() == {w.old}
    w.world.supersede(_ids("J-human"), "J-old")
    seq = w.seq()
    with pytest.raises(ValueError, match="can no longer apply whole"):
        _decide(w, item.work_id, "AGREE")
    assert w.seq() == seq
    assert _decide(w, item.work_id, "DECLINE").status == "DECLINED"


def test_13_a_member_refused_structurally_refuses_the_whole_set() -> None:
    w = _W()
    ev = w.evidence("Refunds: thirty days.")
    _, _, decisions = w.respond(
        w.assertion("thirty days", ev),  # a duplicate of the live claim: structural refusal
        SupersedeProposal(target_judgment_id="J-old", reason="x"),
    )
    assert [d.route for d in decisions] == [AdmissionRoute.REJECT] * 2
    assert all(d.reasons[0] == CORRECTION_SET_INVALID for d in decisions)
    assert w.state().semantic.correction_sets == {} and w.live() == {w.old}


# ------------------------------------------------------------------- 14-18 identity and repeats


def test_14_the_instance_and_equivalence_identities_are_deterministic() -> None:
    w = _W()
    invocation, _, _ = w.correct(content="Refunds: fourteen days.")
    item = _only_set(w)
    assert item.work_id == correction_set_id(PROJECT, invocation, w.address)
    assert item.basis_content_hashes == (sha256_of_content("Refunds: fourteen days."),)
    assert item.equivalence_key == equivalence_key(
        PROJECT, w.address, ("J-old",), item.basis_content_hashes
    )


def test_15_a_repeat_of_a_pending_set_is_not_a_second_obligation() -> None:
    w = _W()
    w.correct()
    _, _, decisions = w.correct()  # same content, new evidence id, new wording would not matter
    assert all(d.route is AdmissionRoute.REJECT for d in decisions)
    assert all(d.reasons[:2] == (CORRECTION_SET_REPEAT, _only_set(w).work_id) for d in decisions)


def test_16_after_a_decline_the_same_correction_is_suppressed_even_from_new_evidence_ids() -> None:
    w = _W()
    w.correct()
    declined = _only_set(w).work_id
    _decide(w, declined, "DECLINE")
    _, _, decisions = w.correct(text="two weeks")  # same basis content, different wording
    assert all(d.reasons[:2] == (CORRECTION_DECLINED, declined) for d in decisions)
    assert w.pending() == () and list_authority_work(w.governor).correction_sets == ()
    assert w.live() == {w.old}


def test_17_a_changed_basis_or_target_set_reopens_the_question() -> None:
    w = _W()
    w.correct()
    _decide(w, _only_set(w).work_id, "DECLINE")
    w.correct(content="Refunds: fourteen days (policy revised in October).")
    assert _only_set(w).status == "PENDING" and w.live() == {w.old}


def test_17b_the_same_basis_with_a_different_target_set_reopens_the_question() -> None:
    w = _W()
    w.world.claim("J-old-2", authority=Authority.INFERRED, text="thirty calendar days")
    w.correct()
    declined = _only_set(w).work_id
    _decide(w, declined, "DECLINE")
    ev = w.evidence("Refunds: fourteen days.")  # the declined basis, byte-identical
    _, _, decisions = w.respond(
        w.assertion("fourteen days", ev),
        SupersedeProposal(target_judgment_id="J-old", reason="x"),
        SupersedeProposal(target_judgment_id="J-old-2", reason="x"),
    )
    assert all(d.reasons[0] == CORRECTION_SET_MEMBER for d in decisions)
    item = _only_set(w)
    assert item.work_id != declined and item.target_judgment_ids == ("J-old", "J-old-2")


def test_18_a_different_proposer_does_not_escape_a_decline() -> None:
    w = _W()
    w.correct()
    declined = _only_set(w).work_id
    _decide(w, declined, "DECLINE")
    ev = w.evidence("Refunds: fourteen days.")
    _, _, decisions = w.respond(
        w.assertion("fourteen days", ev),
        SupersedeProposal(target_judgment_id="J-old", reason="x"),
        fp=OTHER_MODEL,
    )
    assert all(d.reasons[:2] == (CORRECTION_DECLINED, declined) for d in decisions)


# ------------------------------------------------------------------- 19-22 who may decide


@pytest.mark.parametrize("actor", ["xai:grok-4.6", "grok-4.6", "openai/gpt-6-astra", ""])
def test_19_no_model_can_decide_a_set(actor: str) -> None:
    w = _W()
    w.correct()
    seq = w.seq()
    with pytest.raises(ValueError, match="human principal"):
        _decide(w, _only_set(w).work_id, "AGREE", actor=actor)
    assert w.seq() == seq and w.live() == {w.old}


def test_20_an_unauthorized_human_is_refused_by_the_api_and_by_the_ledger() -> None:
    w = _W()
    w.correct()
    item = _only_set(w)
    seq = w.seq()
    with pytest.raises(UnauthorizedAuthorityDecision):
        _decide(w, item.work_id, "DECLINE", actor="human://mallory")
    with pytest.raises(ValueError, match="no live project-wide authority"):
        w.governor.decide_correction_set(
            item.work_id,
            "AGREE",
            human_actor_id="human://mallory",
            authority_record_id="AUTH-project",
            rationale="borrowed",
        )
    assert w.seq() == seq and w.live() == {w.old}


def test_21_unknown_and_stale_decisions_are_refused_and_write_nothing() -> None:
    w = _W()
    w.correct()
    item = _only_set(w)
    seq = w.seq()
    with pytest.raises(AuthorityWorkNotPending, match="unknown"):
        _decide(w, "CSET-000000000000000000000000", "AGREE")
    with pytest.raises(StaleAuthorityDecision):
        _decide(w, item.work_id, "AGREE", seq=seq - 1)
    with pytest.raises(ValueError, match="rationale"):
        decide_correction_set(
            w.governor,
            work_id=item.work_id,
            outcome="AGREE",
            human_actor_id=ALICE,
            expected_sequence=seq,
            rationale="  ",
        )
    assert w.seq() == seq


def test_22_only_a_correction_set_can_be_declined() -> None:
    w = _W()
    legacy = SemanticGovernor(
        store=w.store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: AT,
        id_factory=_ids,
    )
    decision = legacy.submit(
        w.judgment(SupersedeProposal(target_judgment_id="J-old", reason="x"), _ids("INV"), MODEL)
    )
    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS
    (item,) = list_authority_work(w.governor).items
    with pytest.raises(DeclineRefused):
        decline(
            w.governor,
            work_id=item.work_id,
            human_actor_id=ALICE,
            expected_sequence=w.seq(),
            rationale="no",
        )
    resolution = agree(
        w.governor,
        work_id=item.work_id,
        human_actor_id=ALICE,
        expected_sequence=w.seq(),
        rationale="v1 edge agree is unchanged",
        clock=lambda: AT,
        id_factory=_ids,
    )
    agreed = w.state().semantic.judgments[resolution.agree_judgment_id]
    assert agreed.reasoner.policy_version == AUTHORITY_ROUTING_VERSION == "ie2-authority-routing-v1"
    assert resolution.resolved


# ------------------------------------------------------------------- 23-24 history


def test_23_the_policy_is_off_by_default_so_history_admits_exactly_as_recorded() -> None:
    assert AdmissionPolicy().correction_sets is False
    w = _W()
    legacy = SemanticGovernor(
        store=w.store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: AT,
        id_factory=_ids,
    )
    ev = w.evidence("Refunds: fourteen days.")
    invocation = _ids("INV")
    judgments = (
        w.judgment(w.assertion("fourteen days", ev), invocation, MODEL),
        w.judgment(SupersedeProposal(target_judgment_id="J-old", reason="x"), invocation, MODEL),
    )
    decisions = legacy.propose_and_submit(
        _Scripted(judgments, MODEL), ReasoningRequest(project_id=PROJECT, evidence=())
    )
    assert [d.reasons for d in decisions] == [("LOW_RISK",), ("MATERIAL_REQUIRES_SECOND_LENS",)]
    assert w.state().semantic.correction_sets == {}


def test_24_a_v2_ledger_replays_to_the_identical_state() -> None:
    w = _W()
    w.correct()
    _decide(w, _only_set(w).work_id, "AGREE")
    w.correct(text="ten days", content="Refunds: ten days.")
    assert replay(PROJECT, w.store.load(PROJECT)) == w.state()


# ------------------------------------------------------------------- the frozen run


def _clone(store: InMemoryEventStore, project_id: str, prefix: str) -> SemanticGovernor:
    fresh = InMemoryEventStore()
    for stored in store.load(project_id):
        fresh.append(stored.event, expected_sequence=stored.sequence - 1)
    ids = count(1)
    return SemanticGovernor(
        store=fresh,
        project_id=project_id,
        policy=AdmissionPolicy(canonical_facets=True, correction_sets=True),
        clock=lambda: AT,
        id_factory=lambda p: f"{p}-{prefix}-{next(ids):05d}",
    )


def _frozen_world(t: int, prefix: str) -> Any:
    """The frozen ledger up to the start of turn ``t``, under a v2 governor."""
    from tests.unit import test_correction_set_policy as cs

    world = cs._World()
    turn = world.run.turns[t - 1]
    store = InMemoryEventStore()
    for stored in world.run.events:
        if stored.sequence <= turn.seq_start:
            store.append(stored.event, expected_sequence=stored.sequence - 1)
    world.store = store
    world.governor = _clone(store, world.run.project_id, prefix)
    world.store = world.governor._store  # noqa: SLF001 - the clone's own store
    return world


def _rebind(world: Any, governor: SemanticGovernor) -> Any:
    from tests.unit import test_correction_set_policy as cs

    copy = object.__new__(cs._World)
    copy.raw, copy.run = world.raw, world.run
    copy.governor = governor
    copy.store = governor._store  # noqa: SLF001
    return copy


def _live_claims(governor: SemanticGovernor) -> dict[str, Any]:
    state = governor.state()
    return {c: state.semantic.claims[c] for c in derive_view(state.semantic).effective_evidence}


def _decide_frozen(governor: SemanticGovernor, work: str, outcome: Any) -> Any:
    return decide_correction_set(
        governor,
        work_id=work,
        outcome=outcome,
        human_actor_id="human://architect",
        expected_sequence=governor.state().last_sequence,
        rationale="decided on the Orion text",
    )


def _shown(governor: SemanticGovernor) -> tuple[set[str], set[str]]:
    request = compile_intent_graph_context(governor.state(), scope="orion-jobs").request
    assert request is not None
    return (
        {a for locus in request.basis for a in locus.address_ids},
        {c.claim_id for locus in request.basis for c in locus.live_claims},
    )


@pytest.fixture(scope="module")
def transport() -> Iterator[Any]:
    from tests.unit import test_correction_set_policy as cs

    mp = pytest.MonkeyPatch()
    t = cs._Transport()
    mp.setattr(cs.mod, "Client", t.client())
    yield t
    mp.undo()


@pytest.fixture(scope="module")
def t8(transport: Any) -> dict[str, Any]:
    from tests.unit import test_correction_set_policy as cs

    world = _frozen_world(8, "T8")
    before = _live_claims(world.governor)
    cs._assimilate(world, 8, [world.reply(8, 1), world.reply(8, 2)], transport)
    return {"world": world, "before": before}


@pytest.fixture(scope="module")
def t13(transport: Any) -> dict[str, Any]:
    from tests.unit import test_correction_set_policy as cs

    world = _frozen_world(13, "T13")
    before = _live_claims(world.governor)
    cs._assimilate(world, 13, [world.reply(13, 1), world.reply(13, 2)], transport)
    d = world.run.designations["D"].address_id
    (item,) = [s for s in list_authority_work(world.governor).correction_sets if s.address_id == d]
    return {"world": world, "before": before, "d": d, "item": item}


def test_25_t8_is_one_pending_set_that_retires_nothing_until_decided(t8: dict[str, Any]) -> None:
    from tests.unit import test_correction_set_policy as cs

    governor = t8["world"].governor
    queue = list_authority_work(governor)
    (item,) = queue.correction_sets
    assert queue.items == () and authority_routing_findings(governor.state(), queue) == ()
    assert {t[:12] for t in item.target_judgment_ids} == cs.T8_OBSOLETE
    assert len(item.assertion_judgment_ids) == 2 and len(item.supersede_judgment_ids) == 3
    assert _live_claims(governor).keys() == t8["before"].keys()


@pytest.mark.parametrize("outcome", ["AGREE", "DECLINE"])
def test_26_t8_then_t9_under_agree_and_under_decline(
    t8: dict[str, Any], transport: Any, outcome: Any
) -> None:
    from tests.unit import test_correction_set_policy as cs

    governor = _clone(t8["world"].store, t8["world"].run.project_id, f"T8{outcome}")
    world = _rebind(t8["world"], governor)
    before = t8["before"]
    (item,) = list_authority_work(governor).correction_sets
    _decide_frozen(governor, item.work_id, outcome)
    mid = _live_claims(governor)
    retired = {c.created_by_judgment_id[:12] for cid, c in before.items() if cid not in mid}
    added = set(mid) - set(before)
    if outcome == "AGREE":
        assert retired == cs.T8_OBSOLETE
        assert added == {claim_id_for(world.run.project_id, j) for j in item.assertion_judgment_ids}
        reply = cs._t9_reply(world, before)
    else:
        assert retired == set() and added == set()
        reply = world.reply(9, 2)  # the model's own T9 reply, unchanged
    outcome_9 = cs._assimilate(world, 9, [world.reply(9, 1), reply], transport)
    assert outcome_9.calls_made == 2
    after = _live_claims(governor)
    h = world.run.designations["H"].address_id
    assert [c.address_id for cid, c in after.items() if cid not in mid] == [h]
    queue = list_authority_work(governor)
    assert queue.correction_sets == () and queue.items == ()
    assert authority_routing_findings(governor.state(), queue) == ()
    if outcome == "DECLINE":
        suppressed = [
            a
            for a in governor.state().semantic.admissions.values()
            if a.reasons[:2] == (CORRECTION_DECLINED, item.work_id)
        ]
        assert suppressed, "T9's re-proposal of the declined correction is suppressed"


def _d_claims(t13: dict[str, Any], governor: SemanticGovernor) -> tuple[set[str], set[str]]:
    semantic = governor.state().semantic
    live = set(derive_view(semantic).effective_evidence)
    item = t13["item"]
    old = {
        c
        for c, x in semantic.claims.items()
        if x.created_by_judgment_id in item.target_judgment_ids
    }
    new = {claim_id_for(governor.project_id, j) for j in item.assertion_judgment_ids}
    return old & live, new & live


def test_27_t13_d_pending_the_contradiction_never_leaks(t13: dict[str, Any]) -> None:
    governor = t13["world"].governor
    item = t13["item"]
    assert [t[:12] for t in item.target_judgment_ids] == ["JDG-2a3581f5"]
    assert len(item.assertion_judgment_ids) == 2
    old, new = _d_claims(t13, governor)
    assert old and not new, "the v1 contradiction (old rule and its corrections live) is gone"
    shown_addresses, _ = _shown(governor)
    assert t13["d"] not in shown_addresses, "IE3 sees only settled concerns"
    queue = list_authority_work(governor)
    assert queue.items == () and len(queue.correction_sets) == 3
    assert authority_routing_findings(governor.state(), queue) == ()


@pytest.mark.parametrize("outcome", ["AGREE", "DECLINE"])
def test_28_t13_d_decided_either_way_is_coherent_and_visible_to_ie3(
    t13: dict[str, Any], outcome: Any
) -> None:
    governor = _clone(t13["world"].store, t13["world"].run.project_id, f"T13{outcome}")
    _decide_frozen(governor, t13["item"].work_id, outcome)
    old, new = _d_claims(t13, governor)
    assert not (old and new), "never both the old rule and its correction"
    assert (bool(new), bool(old)) == ((True, False) if outcome == "AGREE" else (False, True))
    shown_addresses, shown_claims = _shown(governor)
    assert t13["d"] in shown_addresses
    assert shown_claims >= (new if outcome == "AGREE" else old)
    assert not shown_claims & (old if outcome == "AGREE" else new)
    queue = list_authority_work(governor)
    assert len(queue.correction_sets) == 2 and len(queue.resolved_correction_sets) == 1
    assert authority_routing_findings(governor.state(), queue) == ()
    assert replay(governor.project_id, governor._store.load(governor.project_id)) == (  # noqa: SLF001
        governor.state()
    )


def test_historical_frozen_ledger_has_no_correction_sets_and_replays_unchanged() -> None:
    from pathlib import Path

    from foundry.experiments.long_horizon_ie2_ie3.runner import RunRecord

    raw = json.loads(
        Path("docs/superpowers/experiments/2026-09-29-ie2-ie3-long-horizon-v1/run.json").read_text()
    )
    raw.pop("started_at", None)
    raw.pop("finished_at", None)
    run = RunRecord.model_validate(raw)
    state = replay(run.project_id, run.events)
    assert state.semantic.correction_sets == {}
    assert not any(
        e.event.event_type in (EventType.CORRECTION_SET_PROPOSED, EventType.CORRECTION_SET_DECIDED)
        for e in run.events
    )

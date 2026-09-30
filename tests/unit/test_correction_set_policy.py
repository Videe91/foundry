"""The correction-set policy ``intent-v2-locus-v6`` at the adapter, pipeline and authority.

No live call: the xAI SDK is replaced by a transport that returns scripted reply text, so the
real adapter parses, accounts and wraps every answer, and the real governor, admission,
reducer and 9P3 authority protocol act on it. The frozen long-horizon run (``a0ee2f7``) is
read, never written: its pre-T8 ledger is rebuilt in a fresh store and the model's own T8 and
T9 replies are replayed through v6.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics import xai_reasoner as mod
from foundry.adapters.semantics.xai_reasoner import (
    ACCOUNTED_OUTPUT_SCHEMA_SHA256,
    CORRECTION_SET_POLICY_VERSION,
    CORRECTION_SET_SYSTEM_INSTRUCTION,
    CORRECTION_SET_SYSTEM_INSTRUCTION_SHA256,
    REPROPOSAL_SYSTEM_INSTRUCTION,
    REPROPOSAL_SYSTEM_INSTRUCTION_SHA256,
    PropositionAccountingError,
    SemanticOutputError,
    XAICorrectionSetSemanticReasoner,
    XAIReproposingSemanticReasoner,
    accounted_output_schema_sha256,
)
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticAddress,
    SemanticClaim,
    canonical_facet,
)
from foundry.domain.semantic_judgment import JudgmentKind, SupersedeProposal
from foundry.domain.semantic_view import derive_view
from foundry.domain.structural_refusal import ExecutionMode
from foundry.ports.semantic_reasoner import ReasoningRequest

AT = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
PROJECT = "PROJ-CARD"
RUN = Path("docs/superpowers/experiments/2026-09-29-ie2-ie3-long-horizon-v1/run.json")


class _Transport:
    """The xAI ``Client`` stand-in: each ``sample()`` returns the next scripted reply."""

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.systems: list[str] = []

    def client(self) -> type[object]:
        transport = self

        class Chat:
            def __init__(self, **_: object) -> None:
                self.messages: list[Any] = []

            def append(self, message: object) -> Chat:
                self.messages.append(message)
                return self

            def sample(self) -> object:
                return SimpleNamespace(
                    content=transport.replies.pop(0),
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                    cost_usd=0.0,
                )

        class Chats:
            def create(self, **_: object) -> Chat:
                return Chat()

        class Client:
            def __init__(self, **_: object) -> None:
                self.chat = Chats()

        return Client


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Transport]:
    t = _Transport()
    monkeypatch.setattr(mod, "Client", t.client())
    yield t


_TICKS = count(1)


def _reasoner(cls: type = XAICorrectionSetSemanticReasoner) -> Any:
    return cls(api_key="k", clock=lambda: AT, id_factory=lambda p: f"{p}-{next(_TICKS):05d}")


# --------------------------------------------------------------------------- identity


def test_v6_is_a_new_identity_and_every_earlier_identity_is_unchanged() -> None:
    assert CORRECTION_SET_POLICY_VERSION == "intent-v2-locus-v6"
    digest = hashlib.sha256(CORRECTION_SET_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == CORRECTION_SET_SYSTEM_INSTRUCTION_SHA256
    assert CORRECTION_SET_SYSTEM_INSTRUCTION.startswith(REPROPOSAL_SYSTEM_INSTRUCTION + "\n")
    v5 = hashlib.sha256(REPROPOSAL_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert v5 == REPROPOSAL_SYSTEM_INSTRUCTION_SHA256
    assert v5 == "cc913e3d7aee49e13e2e40745ddc791df0dee0e663893f42be39a475e16a09dc"
    assert XAICorrectionSetSemanticReasoner.draft_payload.__name__ == "AccountedDraftPayload"
    assert accounted_output_schema_sha256() == ACCOUNTED_OUTPUT_SCHEMA_SHA256
    assert ACCOUNTED_OUTPUT_SCHEMA_SHA256 == (
        "921171df25bbf4c64f3a2570ea64dc0b29d6618cf0c8c56f79e01abf1d34a142"
    )
    assert XAIReproposingSemanticReasoner.correction_law == "ONE_TARGET"
    assert XAICorrectionSetSemanticReasoner.correction_law == "TARGET_SET"
    assert XAICorrectionSetSemanticReasoner.accepts_reproposal is True


def test_the_prompt_states_both_sides_of_a_correction() -> None:
    text = " ".join(CORRECTION_SET_SYSTEM_INSTRUCTION.split())
    assert "one SUPERSEDE for EACH current claim it makes obsolete" in text
    assert "each current claim is superseded at most once in the whole response" in text
    assert "at the same address as the ASSERT_CLAIM of that proposition" in text
    assert "every proposition still receives exactly one disposition" in text


# --------------------------------------------------------------------------- the adapter


def _claim(cid: str, jid: str, address: str, text: str) -> SemanticClaim:
    return SemanticClaim(
        claim_id=cid,
        project_id=PROJECT,
        address_id=address,
        predicate=f"p-{cid}",
        value=ClaimValue(kind=ClaimValueKind.TEXT, text=text),
        evidence_ids=("EV-0",),
        authority=Authority.INFERRED,
        provenance=Provenance(source_kind=SourceKind.DOCUMENT, source_ref="doc://0"),
        created_by_judgment_id=jid,
    )


def _address(aid: str, subject: str) -> SemanticAddress:
    return SemanticAddress(
        address_id=aid,
        project_id=PROJECT,
        subject=subject,
        facet=canonical_facet(subject),
        scope=("s",),
        created_by_judgment_id=f"J-{aid}",
    )


def _request() -> ReasoningRequest:
    evidence = evidence_item(
        evidence_id="EV-1",
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref="doc://1",
        content="The wait is five seconds. The wait never varies.",
        observed_at=AT,
        scope=("s",),
    )
    return ReasoningRequest(
        project_id=PROJECT,
        evidence=(evidence,),
        known_addresses=(_address("ADDR-B", "Retry delay"), _address("ADDR-X", "Other")),
        known_claims=(
            _claim("C-2S", "J-2S", "ADDR-B", "2 seconds first"),
            _claim("C-CAP", "J-CAP", "ADDR-B", "30 seconds cap"),
            _claim("C-DBL", "J-DBL", "ADDR-B", "doubling"),
            _claim("C-KEEP", "J-KEEP", "ADDR-B", "measured from end"),
            _claim("C-X", "J-X", "ADDR-X", "elsewhere"),
        ),
        allowed_judgment_kinds=frozenset(
            {JudgmentKind.SUPPORTS_CLAIM, JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPERSEDE}
        ),
        accountable_evidence_ids=("EV-1",),
    )


def _assert(pid: str, text: str, address: str = "ADDR-B") -> dict[str, Any]:
    return {
        "kind": "ASSERT_CLAIM",
        "proposition_id": pid,
        "address_id": address,
        "predicate": f"pred-{pid}",
        "value": {"kind": "TEXT", "text": text},
        "evidence_ids": ["EV-1"],
        "rationale": "r",
    }


def _sup(pid: str, target: str) -> dict[str, Any]:
    return {"kind": "SUPERSEDE", "proposition_id": pid, "target_judgment_id": target, "reason": "r"}


def _reply(drafts: list[dict[str, Any]], pids: tuple[str, ...] = ("P1", "P2")) -> str:
    props = [
        {"proposition_id": p, "sentence_ids": [f"EV-1#S{i}"], "statement": p}
        for i, p in enumerate(pids, 1)
    ]
    return json.dumps({"propositions": props, "non_operative": [], "drafts": drafts})


def _supersede_targets(judgments: tuple[Any, ...]) -> list[str]:
    return sorted(
        j.proposal.target_judgment_id
        for j in judgments
        if isinstance(j.proposal, SupersedeProposal)
    )


T8_SHAPE = [
    _assert("P1", "five seconds"),
    _sup("P1", "J-2S"),
    _sup("P1", "J-CAP"),
    _assert("P2", "never varies"),
    _sup("P2", "J-DBL"),
]


def test_v6_accepts_many_to_many_and_emits_one_supersede_per_target(transport: _Transport) -> None:
    transport.replies.append(_reply(T8_SHAPE))
    judgments = _reasoner().propose(_request())
    assert _supersede_targets(judgments) == ["J-2S", "J-CAP", "J-DBL"]
    assert "J-KEEP" not in _supersede_targets(judgments) and "J-X" not in _supersede_targets(
        judgments
    )
    asserts = [j for j in judgments if j.proposal.kind is JudgmentKind.ASSERT_CLAIM]
    assert len(asserts) == 2


@pytest.mark.parametrize(
    "drafts",
    [
        [_assert("P1", "a"), _sup("P1", "J-2S"), _assert("P2", "b")],
        [_assert("P1", "a"), _sup("P1", "J-2S"), _sup("P1", "J-CAP"), _assert("P2", "b")],
        [_assert("P1", "a"), _sup("P1", "J-2S"), _assert("P2", "b"), _sup("P2", "J-CAP")],
    ],
    ids=["one-to-many", "many-to-one", "one-to-one-twice"],
)
def test_v6_accepts_every_lawful_shape(transport: _Transport, drafts: list[dict[str, Any]]) -> None:
    transport.replies.append(_reply(drafts))
    _reasoner().propose(_request())


@pytest.mark.parametrize(
    ("drafts", "code"),
    [
        (T8_SHAPE[:2] + [_sup("P1", "J-2S"), *T8_SHAPE[3:]], "DUPLICATE_SUPERSEDE_TARGET"),
        ([_assert("P1", "a"), _sup("P1", "J-2S"), _assert("P2", "b"), _sup("P2", "J-2S")],
         "DUPLICATE_SUPERSEDE_TARGET"),
        ([_assert("P1", "a"), _sup("P1", "J-X"), _assert("P2", "b")], "CROSS_ADDRESS_SUPERSEDE"),
        ([_assert("P1", "a"), _sup("P1", "J-GHOST"), _assert("P2", "b")],
         "UNKNOWN_SUPERSEDE_TARGET"),
        ([_sup("P1", "J-2S"), _assert("P2", "b")], "CONFLICTING_DISPOSITION"),
        ([_assert("P1", "a"), _sup("P1", "J-2S")], "UNACCOUNTED_PROPOSITION"),
        ([_assert("P1", "a"), _assert("P1", "a2"), _assert("P2", "b")], "CONFLICTING_DISPOSITION"),
    ],
    ids=["duplicate-on-one", "duplicate-across", "cross-address", "unknown-target",
         "supersede-without-assert", "omitted-proposition", "two-asserts"],
)  # fmt: skip
def test_v6_refuses_every_unlawful_correction(
    transport: _Transport, drafts: list[dict[str, Any]], code: str
) -> None:
    transport.replies.append(_reply(drafts))
    with pytest.raises(PropositionAccountingError) as refused:
        _reasoner().propose(_request())
    assert any(f.startswith(code) for f in refused.value.findings), refused.value.findings


def test_a_supersede_with_no_target_is_refused_by_the_output_contract(
    transport: _Transport,
) -> None:
    drafts = [
        _assert("P1", "a"),
        {**_sup("P1", "J-2S"), "target_judgment_id": ""},
        _assert("P2", "b"),
    ]
    transport.replies.append(_reply(drafts))
    with pytest.raises(SemanticOutputError):
        _reasoner().propose(_request())


def test_v5_keeps_refusing_the_many_target_correction(transport: _Transport) -> None:
    transport.replies.append(_reply(T8_SHAPE))
    with pytest.raises(PropositionAccountingError) as refused:
        _reasoner(XAIReproposingSemanticReasoner).propose(_request())
    assert refused.value.findings == (
        "CONFLICTING_DISPOSITION: P1 (ASSERT_CLAIM, SUPERSEDE, SUPERSEDE)",
    )


def test_v5_and_v6_accept_the_same_one_to_one_correction(transport: _Transport) -> None:
    drafts = [_assert("P1", "a"), _sup("P1", "J-2S"), _assert("P2", "b")]
    for cls in (XAIReproposingSemanticReasoner, XAICorrectionSetSemanticReasoner):
        transport.replies.append(_reply(drafts))
        assert _supersede_targets(_reasoner(cls).propose(_request())) == ["J-2S"]


# --------------------------------------------------------------------------- the frozen T8 world


def _frozen() -> tuple[dict[str, Any], Any]:
    from foundry.experiments.long_horizon_ie2_ie3.runner import RunRecord

    raw = json.loads(RUN.read_text())
    raw.pop("started_at", None)
    raw.pop("finished_at", None)
    return raw, RunRecord.model_validate(raw)


class _World:
    """The frozen pre-T8 ledger rebuilt in a fresh store, and a v6 governor on it."""

    def __init__(self) -> None:
        self.raw, self.run = _frozen()
        self.store = InMemoryEventStore()
        t8 = self.run.turns[7]
        for stored in self.run.events:
            if stored.sequence <= t8.seq_start:
                self.store.append(stored.event, expected_sequence=stored.sequence - 1)
        ids = count(1)
        self.governor = SemanticGovernor(
            store=self.store,
            project_id=self.run.project_id,
            policy=AdmissionPolicy(canonical_facets=True),
            clock=lambda: AT,
            id_factory=lambda prefix: f"{prefix}-OFFLINE-{next(ids):05d}",
        )

    def reply(self, t: int, call: int) -> str:
        return json.dumps(self.raw["turns"][t - 1]["ie2"]["calls"][call - 1]["model_payload"])

    def live(self) -> dict[str, Any]:
        state = self.governor.state()
        live = set(derive_view(state.semantic).effective_evidence)
        return {c: state.semantic.claims[c] for c in live}


def _assimilate(world: _World, t: int, replies: list[str], transport: _Transport) -> Any:
    from foundry.experiments.long_horizon_bounded.timeline import persistent_delta

    transport.replies.extend(replies)
    return assimilate_delta(
        governor=world.governor,
        reasoner=_reasoner(),
        delta=persistent_delta(t, project_id=world.run.project_id),
        scope="orion-jobs",
        mode=ExecutionMode.EXPERIMENT,
    )


_AUTH_IDS = count(1)


class _Budget:
    human_authorizations = 0


def _authorize(world: _World, t: int, eligible: Any) -> Any:
    from foundry.experiments.long_horizon_bounded.authority import authorize_eligible_supersessions

    return authorize_eligible_supersessions(
        governor=world.governor,
        eligible=eligible,
        pending_judgment_ids=tuple(
            derive_view(world.governor.state().semantic).pending_judgment_ids
        ),
        budget=_Budget(),
        clock=lambda: AT,
        id_factory=lambda prefix: f"{prefix}-AUTH-{t}-{next(_AUTH_IDS):03d}",
    )


T8_OBSOLETE = {"JDG-cf225a3b", "JDG-6dc43a9d", "JDG-e1da6031"}


@pytest.fixture(scope="module")
def t8() -> Iterator[dict[str, Any]]:
    """T8 of the frozen run, replayed through v6: the model's own Call 1 and Call 2 replies."""
    from foundry.experiments.long_horizon_bounded.authority import snapshot_eligible_targets

    mp = pytest.MonkeyPatch()
    transport = _Transport()
    mp.setattr(mod, "Client", transport.client())
    try:
        world = _World()
        b = world.run.designations["B"].address_id
        before = world.live()
        seq = world.store.current_sequence(world.run.project_id)
        eligible = snapshot_eligible_targets(
            world.governor.state(),
            arm="F",
            t=8,
            target_locus="B",
            designated_address_id=b,
            ledger_length=seq,
        )
        seq_before = world.store.current_sequence(world.run.project_id)
        outcome = _assimilate(world, 8, [world.reply(8, 1), world.reply(8, 2)], transport)
        pending_after_ie2 = tuple(outcome.pending_supersede_judgment_ids)
        records = _authorize(world, 8, eligible)
        yield {
            "world": world,
            "transport": transport,
            "b": b,
            "before": before,
            "after": world.live(),
            "outcome": outcome,
            "pending": pending_after_ie2,
            "records": records,
            "seq_before": seq_before,
        }
    finally:
        mp.undo()


def test_t8_the_frozen_answer_is_accounted_for_under_v6(t8: dict[str, Any]) -> None:
    outcome = t8["outcome"]
    assert outcome.calls_made == 2
    kinds = [
        t8["world"].governor.state().semantic.judgments[d.judgment_id].proposal.kind
        for d in outcome.stage_decisions[1]
    ]
    assert kinds.count(JudgmentKind.SUPERSEDE) == 3


def test_t8_exactly_the_three_obsolete_b_claims_are_targeted_and_nothing_else(
    t8: dict[str, Any],
) -> None:
    state = t8["world"].governor.state()
    targets = {state.semantic.judgments[p].proposal.target_judgment_id[:12] for p in t8["pending"]}
    assert targets == T8_OBSOLETE


def test_t8_authority_agrees_each_target_once_and_nothing_is_ambiguous(t8: dict[str, Any]) -> None:
    outcomes = sorted(r.outcome.value for r in t8["records"])
    agreed = [r for r in t8["records"] if r.outcome.value == "AGREED"]
    assert len(agreed) == 3, outcomes
    assert {r.target_judgment_id[:12] for r in agreed} == T8_OBSOLETE
    assert not [
        r
        for r in t8["records"]
        if r.outcome.value in ("AMBIGUOUS_PROPOSALS", "NOT_ELIGIBLE_NOT_AUTHORIZED")
    ]
    assert derive_view(t8["world"].governor.state().semantic).pending_judgment_ids == ()


def test_t8_the_resulting_b_state_is_exactly_the_correction(t8: dict[str, Any]) -> None:
    before, after, b = t8["before"], t8["after"], t8["b"]
    gone = {c.created_by_judgment_id[:12] for cid, c in before.items() if cid not in after}
    assert gone == T8_OBSOLETE, "no unrelated claim is retired"
    new = [c for cid, c in after.items() if cid not in before]
    assert {c.address_id for c in new} == {b}, "no other concern is touched"
    texts = " | ".join(str(c.value.quantity or c.value.text) for c in new)
    assert "5" in texts and "shortened or lengthened" in texts
    kept = {c.predicate for cid, c in after.items() if c.address_id == b}
    assert "measurement start of wait before first retry" in kept
    assert all(cid in after for cid, c in before.items() if c.address_id != b)


def test_t8_replay_reproduces_the_exact_correction(t8: dict[str, Any]) -> None:
    world = t8["world"]
    events = world.store.load(world.run.project_id)
    assert replay(world.run.project_id, events) == world.governor.state()
    replayed = replay(world.run.project_id, events).semantic.supersessions
    assert {r.target_judgment_id[:12] for r in replayed[-3:]} == T8_OBSOLETE


def test_t8_an_already_superseded_target_is_refused_by_admission(t8: dict[str, Any]) -> None:
    """A retired claim is not shown to a later response (only live claims are), and admission
    independently refuses a SUPERSEDE of an already superseded judgment."""
    from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment

    world = t8["world"]
    state = world.governor.state()
    target = next(j for j in state.semantic.judgments if j.startswith("JDG-cf225a3b"))
    judgment = SemanticJudgment(
        judgment_id="JDG-LATE-SUPERSEDE",
        project_id=world.run.project_id,
        proposal=SupersedeProposal(target_judgment_id=target, reason="again"),
        visible_evidence_ids=(),
        rationale="r",
        reasoner=ReasonerFingerprint(
            provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v6"
        ),
        invocation_id="INV-LATE",
        proposed_at=AT,
    )
    decision = world.governor.submit(judgment)
    assert decision.route.value == "REJECT"
    assert any("already superseded" in r for r in decision.reasons)


def test_t8_under_v5_is_still_refused_exactly_as_recorded(t8: dict[str, Any]) -> None:
    frozen = t8["world"].raw["turns"][7]["ie2"]["calls"][1]["refusal_findings"]
    assert frozen == ["CONFLICTING_DISPOSITION: P-B-wait (ASSERT_CLAIM, SUPERSEDE, SUPERSEDE)"]


# --------------------------------------------------------------------------- the T8 -> T9 cascade


def _t9_reply(world: _World, t8_live_before: dict[str, Any]) -> str:
    """The model's own T9 reply with its B propositions rewritten as what a correct T9 answer is
    once T8 has been assimilated: SUPPORTS of the two B claims T8 asserted (the same predicates),
    since no B claim is obsolete any more. Every other draft is the frozen reply, unchanged."""
    payload = json.loads(world.reply(9, 2))
    after = world.live()
    new_b = {c.predicate: cid for cid, c in after.items() if cid not in t8_live_before}
    b_props = {
        p["proposition_id"]
        for p in payload["propositions"]
        if any("B09" in s for s in p["sentence_ids"])
    }
    drafts = []
    for d in payload["drafts"]:
        if d.get("proposition_id") not in b_props or d["kind"] == "SUPPORTS_CLAIM":
            drafts.append(d)
        elif d["kind"] == "ASSERT_CLAIM":
            drafts.append(
                {
                    "kind": "SUPPORTS_CLAIM",
                    "proposition_id": d["proposition_id"],
                    "claim_id": new_b[d["predicate"]],
                    "evidence_ids": d["evidence_ids"],
                    "rationale": "restates the claim T8 asserted",
                }
            )
    payload["drafts"] = drafts
    return json.dumps(payload)


def test_t9_is_no_longer_refused_once_t8_is_representable(t8: dict[str, Any]) -> None:
    """The refusal cascade is gone: T9 assimilates, and the repeated-cancellation proposition the
    model stated in its frozen T9 reply becomes a live claim at the cancellation address. This
    proves the mechanism only; it does not validate C09 or the long horizon."""
    world, transport = t8["world"], t8["transport"]
    reply_2 = _t9_reply(world, t8["before"])
    live_before = world.live()
    outcome = _assimilate(world, 9, [world.reply(9, 1), reply_2], transport)
    assert outcome.calls_made == 2
    after = world.live()
    h = world.run.designations["H"].address_id
    added = [c for cid, c in after.items() if cid not in live_before]
    assert [c.address_id for c in added] == [h]
    assert "repeated cancellation" in added[0].predicate
    assert all(cid in after for cid in live_before), "T9 retires nothing"
    assert outcome.pending_supersede_judgment_ids == ()


def test_a_refused_correction_changes_no_state(transport: _Transport) -> None:
    """Refused whole before any judgment exists: the ledger after Call 1 is the ledger after the
    refused Call 2."""
    world = _World()
    call_1, call_2 = world.reply(8, 1), world.reply(8, 2)
    payload = json.loads(call_2)
    for d in payload["drafts"]:
        if d["kind"] == "SUPERSEDE" and d["target_judgment_id"].startswith("JDG-6dc43a9d"):
            d["target_judgment_id"] = "JDG-e1da6031-a254-4a10-9edf-d90434c0d088"  # a duplicate
    transport.replies.extend([call_1, json.dumps(payload)])
    from foundry.experiments.long_horizon_bounded.timeline import persistent_delta

    before = world.governor.state().semantic
    with pytest.raises(PropositionAccountingError) as refused:
        assimilate_delta(
            governor=world.governor,
            reasoner=_reasoner(),
            delta=persistent_delta(8, project_id=world.run.project_id),
            scope="orion-jobs",
            mode=ExecutionMode.EXPERIMENT,
        )
    assert any(f.startswith("DUPLICATE_SUPERSEDE_TARGET") for f in refused.value.findings)
    after = world.governor.state().semantic
    assert after.claims == before.claims
    assert after.claim_supports == before.claim_supports
    assert after.supersessions == before.supersessions
    new = set(after.judgments) - set(before.judgments)
    assert all(
        after.judgments[j].proposal.kind
        in (JudgmentKind.CREATE_ADDRESS, JudgmentKind.BIND_TO_ADDRESS)
        for j in new
    ), "only Call 1 reached state"
    assert derive_view(after).pending_judgment_ids == ()

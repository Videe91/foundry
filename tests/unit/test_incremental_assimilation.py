"""Incremental assimilation orchestrator (9P Task 8; spec §6, §26).

One delta, exactly two frontier calls, no reconciliation, no retry, no authority. Call 1
may only bind or create; Call 2 may only support, assert, supersede or dispute. A pending
``SUPERSEDE`` is surfaced, never resolved. Every ledger here is the real
``SemanticGovernor`` over an ``InMemoryEventStore``; the only reasoner is a scripted fake
that records the requests it received. ZERO live calls.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from pathlib import Path

import pytest

import foundry.application.incremental_assimilation as incremental_assimilation_module
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.incremental_assimilation import DeltaOutcome, assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionDecision, AdmissionPolicy
from foundry.domain.common import Authority, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

PROJECT = "PROJ-9P"
SCOPE = "A"
T0 = datetime(2026, 9, 11, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="9p-v1")
HUMAN = ReasonerFingerprint(provider="human", model="human://alice", policy_version="n/a")
ARTIFACT = "docs/retention.md"

ADDR_1 = address_id_for(PROJECT, "J-c1")
ADDR_2 = address_id_for(PROJECT, "J-c2")
CLAIM_1 = claim_id_for(PROJECT, "J-cl1")
CLAIM_2 = claim_id_for(PROJECT, "J-cl2")
CLAIM_NEW = claim_id_for(PROJECT, "J-cl-new")

CALL1_KINDS = frozenset({JudgmentKind.BIND_TO_ADDRESS, JudgmentKind.CREATE_ADDRESS})
CALL2_KINDS = frozenset(
    {
        JudgmentKind.SUPPORTS_CLAIM,
        JudgmentKind.ASSERT_CLAIM,
        JudgmentKind.SUPERSEDE,
        JudgmentKind.CONFLICTS_WITH,
    }
)

type Batch = (
    list[SemanticJudgment] | Callable[[ReasoningRequest], list[SemanticJudgment]] | BaseException
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- fakes ------------------------------------------------------------------------


class ScriptedReasoner:
    """Returns one scripted batch per call, records every request, refuses extra calls."""

    def __init__(self, batches: list[Batch], fingerprint: ReasonerFingerprint = MODEL) -> None:
        self._batches = batches
        self._fingerprint = fingerprint
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        batch = self._batches[index]
        if isinstance(batch, BaseException):
            raise batch
        if callable(batch):
            return tuple(batch(request))
        return tuple(batch)


# --- builders ---------------------------------------------------------------------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0.replace(minute=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _governor() -> SemanticGovernor:
    clock = _clock()
    return SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )


def _evidence(
    evidence_id: str, *, artifact_ref: str = ARTIFACT, supersedes: str | None = None
) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=f"Evidence body {evidence_id}.",
        observed_at=T0,
        scope=(SCOPE,),
        artifact_ref=artifact_ref,
        supersedes_evidence_id=supersedes,
    )


def _candidate(candidate_id: str, evidence_id: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject=f"subject {candidate_id}",
        facet="retention",
        scope=(SCOPE,),
        evidence_ids=(evidence_id,),
    )


def _judgment(
    judgment_id: str,
    proposal: JudgmentProposal,
    *,
    evidence_id: str,
    reasoner: ReasonerFingerprint = MODEL,
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Rationale for {judgment_id}.",
        reasoner=reasoner,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _create(judgment_id: str, evidence_id: str, **kw: ReasonerFingerprint) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(candidate=_candidate(f"CAND-{judgment_id}", evidence_id)),
        evidence_id=evidence_id,
        **kw,
    )


def _bind(judgment_id: str, address_id: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        BindToAddressProposal(
            candidate=_candidate(f"CAND-{judgment_id}", evidence_id), address_id=address_id
        ),
        evidence_id=evidence_id,
    )


def _claim(judgment_id: str, address_id: str, evidence_id: str, quantity: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="day"),
            evidence_ids=(evidence_id,),
            authority=Authority.OBSERVED,
        ),
        evidence_id=evidence_id,
    )


def _support(judgment_id: str, claim_id: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupportsClaimProposal(claim_id=claim_id, evidence_ids=(evidence_id,)),
        evidence_id=evidence_id,
    )


def _supersede(judgment_id: str, target: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupersedeProposal(target_judgment_id=target, reason="The older record is corrected."),
        evidence_id=evidence_id,
    )


def _conflict(judgment_id: str, claim_a: str, claim_b: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        ConflictsWithProposal(claim_a=claim_a, claim_b=claim_b),
        evidence_id=evidence_id,
    )


def _seed_address(governor: SemanticGovernor) -> None:
    """EV-1 ingested; ``ADDR_1`` created from it (applied)."""
    governor.ingest(_evidence("EV-1"))
    assert governor.submit(_create("J-c1", "EV-1")).route is AdmissionRoute.APPLY


def _seed_address_and_claim(governor: SemanticGovernor) -> None:
    """``ADDR_1`` with one live claim ``CLAIM_1`` (7 days) citing EV-1."""
    _seed_address(governor)
    assert governor.submit(_claim("J-cl1", ADDR_1, "EV-1", "7")).route is AdmissionRoute.APPLY


def _delta_v2() -> tuple[EvidenceItem, ...]:
    return (_evidence("EV-2", supersedes="EV-1"),)


def _live_claim_ids(governor: SemanticGovernor) -> frozenset[str]:
    return frozenset(claim_id for locus in governor.view().loci for claim_id in locus.claim_ids)


def _routes(decisions: tuple[AdmissionDecision, ...]) -> list[AdmissionRoute]:
    return [decision.route for decision in decisions]


# --- two calls, in order ------------------------------------------------------------


def test_delta_makes_exactly_two_reasoner_calls_in_order() -> None:
    governor = _governor()
    delta = (_evidence("EV-1"),)
    reasoner = ScriptedReasoner(
        [
            [_create("J-c1", "EV-1")],
            lambda request: [_claim("J-cl1", request.known_addresses[0].address_id, "EV-1", "7")],
        ]
    )

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE)

    assert isinstance(outcome, DeltaOutcome)
    assert outcome.calls_made == 2
    assert len(reasoner.requests) == 2
    call1, call2 = reasoner.requests
    # Call 1: the delta, no known state at T1, bind-or-create only.
    assert call1.project_id == PROJECT
    assert call1.evidence == delta
    assert call1.known_addresses == ()
    assert call1.known_claims == ()
    assert call1.allowed_judgment_kinds == CALL1_KINDS
    # Call 2: the delta, the neighbourhood minted by call 1, claim kinds only.
    assert call2.project_id == PROJECT
    assert call2.evidence == delta
    assert tuple(address.address_id for address in call2.known_addresses) == (ADDR_1,)
    assert call2.known_claims == ()
    assert call2.allowed_judgment_kinds == CALL2_KINDS
    # Outcome mirrors the two admissions, in order.
    d1, d2 = outcome.stage_decisions
    assert [decision.judgment_id for decision in d1] == ["J-c1"]
    assert [decision.judgment_id for decision in d2] == ["J-cl1"]
    assert _routes(d1) == [AdmissionRoute.APPLY]
    assert _routes(d2) == [AdmissionRoute.APPLY]
    assert outcome.neighborhood == (ADDR_1,)
    assert outcome.pending_supersede_judgment_ids == ()
    assert set(governor.state().semantic.addresses) == {ADDR_1}
    assert set(governor.state().semantic.claims) == {CLAIM_1}


# --- call 1 outcomes ------------------------------------------------------------------


def test_bind_lands_evidence_on_existing_address_without_new_identity() -> None:
    governor = _governor()
    _seed_address(governor)
    reasoner = ScriptedReasoner([[_bind("J-b2", ADDR_1, "EV-2")], []])

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    # Lineage was validated on ingest and is visible as data, not authority.
    state = governor.state()
    assert state.semantic.evidence["EV-2"].supersedes_evidence_id == "EV-1"
    view = governor.view()
    assert view.current_evidence_ids == ("EV-2",)
    assert view.superseded_evidence_ids == ("EV-1",)
    # The model saw the existing descriptor and bound to it: no new identity.
    assert [address.address_id for address in reasoner.requests[0].known_addresses] == [ADDR_1]
    assert set(state.semantic.addresses) == {ADDR_1}
    assert _routes(outcome.stage_decisions[0]) == [AdmissionRoute.APPLY]
    assert view.active_bindings["CAND-J-b2"] == ADDR_1
    assert outcome.neighborhood == (ADDR_1,)
    assert outcome.stage_decisions[1] == ()
    assert outcome.pending_supersede_judgment_ids == ()
    assert outcome.calls_made == 2

    # A delta with broken lineage is refused by the reducer dry-run before any call.
    broken = ScriptedReasoner([[], []])
    with pytest.raises(ValueError, match="supersedes unknown evidence"):
        assimilate_delta(
            governor=governor,
            reasoner=broken,
            delta=(_evidence("EV-3", supersedes="EV-missing"),),
            scope=SCOPE,
        )
    assert broken.requests == []


def test_create_is_legitimate_when_model_reports_no_match() -> None:
    governor = _governor()
    _seed_address(governor)
    delta = (_evidence("EV-9", artifact_ref="docs/other.md"),)
    reasoner = ScriptedReasoner([[_create("J-c2", "EV-9")], []])

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE)

    # The candidate address was offered; the model reported no match and created.
    assert [address.address_id for address in reasoner.requests[0].known_addresses] == [ADDR_1]
    assert _routes(outcome.stage_decisions[0]) == [AdmissionRoute.APPLY]
    assert set(governor.state().semantic.addresses) == {ADDR_1, ADDR_2}
    # Only the touched address forms the neighbourhood; the untouched one is not sent.
    assert outcome.neighborhood == (ADDR_2,)
    assert [address.address_id for address in reasoner.requests[1].known_addresses] == [ADDR_2]
    assert reasoner.requests[1].known_claims == ()
    assert outcome.pending_supersede_judgment_ids == ()


# --- call 2 outcomes ------------------------------------------------------------------


def test_support_adds_evidence_without_new_claim() -> None:
    governor = _governor()
    _seed_address_and_claim(governor)
    reasoner = ScriptedReasoner(
        [[_bind("J-b2", ADDR_1, "EV-2")], [_support("J-s2", CLAIM_1, "EV-2")]]
    )

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    call2 = reasoner.requests[1]
    assert [claim.claim_id for claim in call2.known_claims] == [CLAIM_1]
    # Call 2 is the same delta only (spec §19): EV-1 is cited by the known claim's
    # ``evidence_ids`` and named by EV-2's ``supersedes_evidence_id``, never resent.
    assert call2.evidence == _delta_v2()
    assert [item.evidence_id for item in call2.evidence] == ["EV-2"]
    assert call2.evidence[0].supersedes_evidence_id == "EV-1"
    assert call2.known_claims[0].evidence_ids == ("EV-1",)
    assert _routes(outcome.stage_decisions[1]) == [AdmissionRoute.APPLY]
    state = governor.state()
    view = governor.view()
    assert set(state.semantic.claims) == {CLAIM_1}
    assert state.semantic.claims[CLAIM_1].evidence_ids == ("EV-1",)
    assert view.effective_evidence[CLAIM_1] == ("EV-1", "EV-2")
    assert view.active_support_judgment_ids == ("J-s2",)
    assert outcome.pending_supersede_judgment_ids == ()


def test_correction_asserts_new_claim_and_leaves_supersede_pending() -> None:
    governor = _governor()
    _seed_address_and_claim(governor)
    assert governor.submit(_claim("J-cl2", ADDR_1, "EV-1", "9")).route is AdmissionRoute.APPLY
    reasoner = ScriptedReasoner(
        [
            [_bind("J-b2", ADDR_1, "EV-2")],
            [
                _claim("J-cl-new", ADDR_1, "EV-2", "30"),
                _supersede("J-sup", "J-cl1", "EV-2"),
                _conflict("J-conf", CLAIM_1, CLAIM_2, "EV-2"),
            ],
        ]
    )

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    d2 = outcome.stage_decisions[1]
    assert [decision.judgment_id for decision in d2] == ["J-cl-new", "J-sup", "J-conf"]
    assert _routes(d2) == [
        AdmissionRoute.APPLY,
        AdmissionRoute.REQUIRE_SECOND_LENS,
        AdmissionRoute.REQUIRE_SECOND_LENS,
    ]
    # Both the old and the new claim are live: nothing was resolved here.
    assert _live_claim_ids(governor) == {CLAIM_1, CLAIM_2, CLAIM_NEW}
    view = governor.view()
    assert view.pending_judgment_ids == ("J-conf", "J-sup")
    assert view.active_conflict_judgment_ids == ()
    # Only the SUPERSEDE is surfaced; the pending CONFLICTS_WITH is not a supersession.
    assert outcome.pending_supersede_judgment_ids == ("J-sup",)
    assert "J-sup" not in governor.state().semantic.applied_judgment_ids
    assert outcome.calls_made == 2
    assert len(reasoner.requests) == 2


# --- layer rules ----------------------------------------------------------------------


def test_orchestrator_never_submits_a_human_judgment() -> None:
    source = Path(incremental_assimilation_module.__file__).read_text(encoding="utf-8")
    assert "human_actor_id" not in source
    assert "record_authority" not in source
    assert ".submit(" not in source
    assert source.count("propose_and_submit(") == 2
    assert "retry" not in source.lower()
    assert "SemanticJudgment(" not in source
    assert "confidence" not in source

    governor = _governor()
    human = ScriptedReasoner([[_create("J-h1", "EV-1", reasoner=HUMAN)], []], fingerprint=HUMAN)

    with pytest.raises(ValueError, match="non-human reasoners only"):
        assimilate_delta(governor=governor, reasoner=human, delta=(_evidence("EV-1"),), scope=SCOPE)

    assert human.requests == []
    state = governor.state()
    assert state.semantic.judgments == {}
    assert state.semantic.addresses == {}


def test_failure_in_call_two_propagates_after_call_one_state_is_kept() -> None:
    governor = _governor()
    delta = (_evidence("EV-1"),)
    reasoner = ScriptedReasoner([[_create("J-c1", "EV-1")], RuntimeError("provider failure")])

    with pytest.raises(RuntimeError, match="provider failure"):
        assimilate_delta(governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE)

    # Call 2 was attempted exactly once and never retried.
    assert len(reasoner.requests) == 2
    assert reasoner.requests[1].allowed_judgment_kinds == CALL2_KINDS
    # Call-1 state is kept: nothing is rolled back.
    state = governor.state()
    assert set(state.semantic.addresses) == {ADDR_1}
    assert state.semantic.applied_judgment_ids == ("J-c1",)
    assert set(state.semantic.judgments) == {"J-c1"}
    assert state.semantic.claims == {}
    assert "EV-1" in state.semantic.evidence

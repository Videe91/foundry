"""Incremental assimilation orchestrator (9P Task 8 -> 9P2 Task T4; spec §6, §11, §12, §18).

One delta, exactly two frontier calls, no reconciliation, no retry, no authority. Call 1
may only bind or create; Call 2 may only support, assert, supersede or dispute. Call 2's
claim neighbourhood is the union of the addresses Call 1 applied and the addresses the
comparison context structurally touched; ``neighborhood`` keeps its 9P meaning. Current
citable evidence remains delta-only; structurally selected predecessor material may appear
only in the non-citable comparison context. A pending ``SUPERSEDE`` is surfaced, never
resolved. Every ledger here is the real ``SemanticGovernor`` over an
``InMemoryEventStore``; the only reasoner is a scripted fake that records the requests it
received. ZERO live calls.
"""

from __future__ import annotations

import re
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from pathlib import Path

import pytest

import foundry.application.contrastive_context as contrastive_context_module
import foundry.application.incremental_assimilation as incremental_assimilation_module
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application import claim_reproposal as claim_reproposal_module
from foundry.application.context_errors import ContextUnsupported
from foundry.application.incremental_assimilation import (
    CALLS_PER_DELTA,
    DeltaOutcome,
    assimilate_delta,
)
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
from foundry.ports.semantic_reasoner import ComparisonContext, ContextRelation, ReasoningRequest

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


def _evidence_ids(request: ReasoningRequest) -> list[str]:
    return [item.evidence_id for item in request.evidence]


def _address_ids(request: ReasoningRequest) -> list[str]:
    return [address.address_id for address in request.known_addresses]


def _claim_ids(request: ReasoningRequest) -> list[str]:
    return [claim.claim_id for claim in request.known_claims]


def _assert_v2_transition_touches_claim_1(request: ReasoningRequest) -> None:
    """EV-2 supersedes EV-1; EV-1 is effective evidence of live CLAIM_1 at ADDR_1."""
    context = request.comparison_context
    assert len(context.transitions) == 1
    transition = context.transitions[0]
    assert transition.current_evidence_id == "EV-2"
    assert transition.predecessor_evidence_id == "EV-1"
    assert transition.touched_claim_ids == (CLAIM_1,)
    assert transition.touched_address_ids == (ADDR_1,)
    assert [(e.source_id, e.relation, e.target_id) for e in transition.inclusion_edges] == [
        ("EV-2", ContextRelation.SUPERSEDES, "EV-1"),
        ("EV-1", ContextRelation.EFFECTIVE_EVIDENCE_OF, CLAIM_1),
        (CLAIM_1, ContextRelation.CLAIM_AT_ADDRESS, ADDR_1),
    ]
    assert "--- evidence:EV-1\n" in transition.historical_diff
    assert "+++ evidence:EV-2\n" in transition.historical_diff
    assert "-Evidence body EV-1." in transition.historical_diff
    assert "+Evidence body EV-2." in transition.historical_diff
    # The predecessor is comparison material only; it is never citable evidence.
    assert _evidence_ids(request) == ["EV-2"]


# --- two calls, in order ------------------------------------------------------------


def test_delta_makes_exactly_two_reasoner_calls_in_order() -> None:
    assert CALLS_PER_DELTA == 2
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
    # Call 1: the delta, no known state at T1, bind-or-create only, nothing to compare.
    assert call1.project_id == PROJECT
    assert call1.evidence == delta
    assert call1.known_addresses == ()
    assert call1.known_claims == ()
    assert call1.allowed_judgment_kinds == CALL1_KINDS
    assert call1.comparison_context == ComparisonContext()
    # Call 2: the delta, the neighbourhood minted by call 1, claim kinds only.
    assert call2.project_id == PROJECT
    assert call2.evidence == delta
    assert _address_ids(call2) == [ADDR_1]
    assert call2.known_claims == ()
    assert call2.allowed_judgment_kinds == CALL2_KINDS
    assert call2.comparison_context == ComparisonContext()
    # Outcome mirrors the two admissions, in order.
    d1, d2 = outcome.stage_decisions
    assert [decision.judgment_id for decision in d1] == ["J-c1"]
    assert [decision.judgment_id for decision in d2] == ["J-cl1"]
    assert _routes(d1) == [AdmissionRoute.APPLY]
    assert _routes(d2) == [AdmissionRoute.APPLY]
    assert outcome.neighborhood == (ADDR_1,)
    assert outcome.claim_neighborhood == (ADDR_1,)
    assert outcome.pending_supersede_judgment_ids == ()
    assert set(governor.state().semantic.addresses) == {ADDR_1}
    assert set(governor.state().semantic.claims) == {CLAIM_1}


def test_delta_outcome_carries_exactly_the_claim_neighborhood_extension() -> None:
    assert set(DeltaOutcome.model_fields) == {
        "stage_decisions",
        "neighborhood",
        "claim_neighborhood",
        "pending_supersede_judgment_ids",
        "calls_made",
        "refused_attempts",  # 2026-09-29: the recorded refusal a production re-proposal replaced
    }


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
    call1 = reasoner.requests[0]
    assert _address_ids(call1) == [ADDR_1]
    assert call1.known_claims == ()
    assert call1.allowed_judgment_kinds == CALL1_KINDS
    # No live claim cites EV-1, so the transition touches nothing; lineage is still shown.
    assert [t.predecessor_evidence_id for t in call1.comparison_context.transitions] == ["EV-1"]
    assert call1.comparison_context.transitions[0].touched_claim_ids == ()
    assert _evidence_ids(call1) == ["EV-2"]
    assert set(state.semantic.addresses) == {ADDR_1}
    assert _routes(outcome.stage_decisions[0]) == [AdmissionRoute.APPLY]
    assert view.active_bindings["CAND-J-b2"] == ADDR_1
    # BIND to existing A: both neighbourhoods are exactly (A,).
    assert outcome.neighborhood == (ADDR_1,)
    assert outcome.claim_neighborhood == (ADDR_1,)
    assert outcome.neighborhood == outcome.claim_neighborhood
    assert _address_ids(reasoner.requests[1]) == [ADDR_1]
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


def test_bind_with_live_claim_keeps_both_neighbourhoods_at_the_bound_address() -> None:
    governor = _governor()
    _seed_address_and_claim(governor)
    reasoner = ScriptedReasoner([[_bind("J-b2", ADDR_1, "EV-2")], []])

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    # Call 1 sees the live claim profile and the transition but stays bind-or-create.
    call1 = reasoner.requests[0]
    assert _claim_ids(call1) == [CLAIM_1]
    assert call1.allowed_judgment_kinds == CALL1_KINDS
    _assert_v2_transition_touches_claim_1(call1)
    assert [
        (e.source_id, e.target_id) for e in call1.comparison_context.active_claim_profile_edges
    ] == [(ADDR_1, CLAIM_1)]
    # Decision touched A and the contrast touched A: the union is still (A,).
    assert outcome.neighborhood == (ADDR_1,)
    assert outcome.claim_neighborhood == (ADDR_1,)
    assert _address_ids(reasoner.requests[1]) == [ADDR_1]
    assert _claim_ids(reasoner.requests[1]) == [CLAIM_1]


def test_create_is_legitimate_when_model_reports_no_match() -> None:
    governor = _governor()
    _seed_address_and_claim(governor)
    delta = (_evidence("EV-9", artifact_ref="docs/other.md"),)
    reasoner = ScriptedReasoner([[_create("J-c2", "EV-9")], []])

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE)

    # The candidate address and its claim profile were offered; the model reported no
    # match and created. An unrelated artifact has no predecessor: no transition.
    call1 = reasoner.requests[0]
    assert _address_ids(call1) == [ADDR_1]
    assert _claim_ids(call1) == [CLAIM_1]
    assert call1.comparison_context.transitions == ()
    assert _routes(outcome.stage_decisions[0]) == [AdmissionRoute.APPLY]
    assert set(governor.state().semantic.addresses) == {ADDR_1, ADDR_2}
    # Only the touched address forms the neighbourhood; nothing structural widens it.
    assert outcome.neighborhood == (ADDR_2,)
    assert outcome.claim_neighborhood == (ADDR_2,)
    call2 = reasoner.requests[1]
    assert _address_ids(call2) == [ADDR_2]
    assert call2.known_claims == ()
    assert call2.comparison_context == ComparisonContext()
    assert outcome.pending_supersede_judgment_ids == ()


def test_deliberate_create_while_old_address_is_structurally_touched_widens_call_two() -> None:
    """Call 1 CREATEs a new address for EV-2 although EV-2 supersedes evidence of the
    live claim at ``ADDR_1``. ``neighborhood`` keeps its 9P meaning (the new address
    only); ``claim_neighborhood`` adds the structurally touched ``ADDR_1`` so Call 2
    still sees the old current claim. Nothing is auto-repaired: the CREATE stands.
    """
    governor = _governor()
    _seed_address_and_claim(governor)
    reasoner = ScriptedReasoner([[_create("J-c2", "EV-2")], []])

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    assert set(governor.state().semantic.addresses) == {ADDR_1, ADDR_2}
    assert outcome.neighborhood == (ADDR_2,)
    assert outcome.claim_neighborhood == tuple(sorted((ADDR_1, ADDR_2)))
    call2 = reasoner.requests[1]
    assert _address_ids(call2) == sorted((ADDR_1, ADDR_2))
    assert _claim_ids(call2) == [CLAIM_1]
    assert call2.known_claims[0].address_id == ADDR_1
    assert call2.allowed_judgment_kinds == CALL2_KINDS
    _assert_v2_transition_touches_claim_1(call2)
    assert [
        (e.source_id, e.target_id) for e in call2.comparison_context.active_claim_profile_edges
    ] == [(ADDR_1, CLAIM_1)]
    assert call2.evidence == _delta_v2()
    assert outcome.calls_made == 2
    assert len(reasoner.requests) == 2


# --- call 2 outcomes ------------------------------------------------------------------


def test_support_adds_evidence_without_new_claim() -> None:
    governor = _governor()
    _seed_address_and_claim(governor)
    reasoner = ScriptedReasoner(
        [[_bind("J-b2", ADDR_1, "EV-2")], [_support("J-s2", CLAIM_1, "EV-2")]]
    )

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    call2 = reasoner.requests[1]
    assert _claim_ids(call2) == [CLAIM_1]
    # Call 2's EVIDENCE is the delta only: EV-1 is cited by the known claim's
    # ``evidence_ids``, named by EV-2's ``supersedes_evidence_id`` and shown as a
    # non-citable transition in the comparison context — never inserted as evidence.
    assert call2.evidence == _delta_v2()
    assert _evidence_ids(call2) == ["EV-2"]
    assert call2.evidence[0].supersedes_evidence_id == "EV-1"
    assert call2.known_claims[0].evidence_ids == ("EV-1",)
    _assert_v2_transition_touches_claim_1(call2)
    assert outcome.neighborhood == (ADDR_1,)
    assert outcome.claim_neighborhood == (ADDR_1,)
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

    # Both old current claims were visible to Call 2 as known claims and as touched claims.
    call2 = reasoner.requests[1]
    assert _claim_ids(call2) == sorted((CLAIM_1, CLAIM_2))
    assert call2.comparison_context.transitions[0].touched_claim_ids == tuple(
        sorted((CLAIM_1, CLAIM_2))
    )
    assert _evidence_ids(call2) == ["EV-2"]
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
    assert outcome.neighborhood == (ADDR_1,)
    assert outcome.claim_neighborhood == (ADDR_1,)
    assert outcome.calls_made == 2
    assert len(reasoner.requests) == 2


# --- context-limit refusals -----------------------------------------------------------


def test_call_one_context_limit_refusal_happens_before_any_reasoner_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governor = _governor()
    _seed_address_and_claim(governor)
    reasoner = ScriptedReasoner([[_bind("J-b2", ADDR_1, "EV-2")], []])
    monkeypatch.setattr(contrastive_context_module, "MAX_COMPARISON_CONTEXT_CHARS", 0)

    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_COMPARISON_CONTEXT"):
        assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    # No reasoner call was made and nothing was retried or narrowed.
    assert reasoner.requests == []
    state = governor.state()
    assert set(state.semantic.judgments) == {"J-c1", "J-cl1"}
    # The delta was ingested before the refusal (an appended event, never rolled back).
    assert "EV-2" in state.semantic.evidence


def test_call_two_context_limit_refusal_happens_after_call_one_with_no_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governor = _governor()
    _seed_address_and_claim(governor)
    reasoner = ScriptedReasoner([[_bind("J-b2", ADDR_1, "EV-2")], []])
    real_render = contrastive_context_module.render_unified_diff
    renders: list[tuple[str, str]] = []

    def _second_render_is_oversized(predecessor: EvidenceItem, current: EvidenceItem) -> str:
        renders.append((predecessor.evidence_id, current.evidence_id))
        if len(renders) == 2:
            raise ContextUnsupported("UNSUPPORTED_TRANSITION_DIFF: forced by test")
        return real_render(predecessor, current)

    monkeypatch.setattr(
        contrastive_context_module, "render_unified_diff", _second_render_is_oversized
    )

    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_TRANSITION_DIFF"):
        assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    # Call 1 ran once (its context compiled); Call 2's context was refused before the
    # reasoner saw it, and nothing was retried.
    assert renders == [("EV-1", "EV-2"), ("EV-1", "EV-2")]
    assert len(reasoner.requests) == 1
    assert reasoner.requests[0].allowed_judgment_kinds == CALL1_KINDS
    # Call-1 state is kept: the binding was applied and nothing is rolled back.
    state = governor.state()
    assert "J-b2" in state.semantic.applied_judgment_ids
    assert governor.view().active_bindings["CAND-J-b2"] == ADDR_1


# --- layer rules ----------------------------------------------------------------------


def test_orchestrator_never_submits_a_human_judgment() -> None:
    source = Path(incremental_assimilation_module.__file__).read_text(encoding="utf-8")
    assert "human_actor_id" not in source
    assert "record_authority" not in source
    assert ".submit(" not in source
    # Call 1 here; Call 2 through ``claim_call`` (2026-09-29), which alone owns the one
    # production re-proposal. This module still never retries, catches or rolls back.
    assert source.count("propose_and_submit(") == 1
    assert source.count("claim_call(") == 1
    assert "retry" not in source.lower()
    assert re.search(r"^\s*try:", source, re.MULTILINE) is None
    assert re.search(r"^\s*except\b", source, re.MULTILINE) is None
    assert "SemanticJudgment(" not in source
    assert "confidence" not in source
    assert "CALLS_PER_DELTA: Final[int] = 2" in source
    assert "contrastive_address_ids(" in source

    governor = _governor()
    human = ScriptedReasoner([[_create("J-h1", "EV-1", reasoner=HUMAN)], []], fingerprint=HUMAN)

    with pytest.raises(ValueError, match="non-human reasoners only"):
        assimilate_delta(governor=governor, reasoner=human, delta=(_evidence("EV-1"),), scope=SCOPE)

    assert human.requests == []
    state = governor.state()
    assert state.semantic.judgments == {}
    assert state.semantic.addresses == {}


def test_the_claim_call_makes_at_most_one_production_reproposal_and_no_human_judgment() -> None:
    source = Path(claim_reproposal_module.__file__).read_text(encoding="utf-8")
    assert "human_actor_id" not in source
    assert "record_authority" not in source
    assert ".submit(" not in source
    assert source.count("propose_and_submit(") == 2  # attempt 1, and the single re-proposal
    assert len(re.findall(r"^\s*try:", source, re.MULTILINE)) == 2  # attempt 1, attempt 2
    assert "while " not in source and "for " not in source.split('"""', 2)[2]
    assert "if mode not in REPROPOSE_MODES:" in source


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


# --- scope closure (2026-09-12 pre-experiment amendment, Ruling A) ----------------

SCOPE_B = "B"
ADDR_B = address_id_for(PROJECT, "J-cB")
CLAIM_B = claim_id_for(PROJECT, "J-clB")
ADDR_PW = address_id_for(PROJECT, "J-cPW")
CLAIM_PW = claim_id_for(PROJECT, "J-clPW")


def _create_in(judgment_id: str, evidence_id: str, scope: tuple[str, ...]) -> SemanticJudgment:
    candidate = SemanticCandidate(
        candidate_id=f"CAND-{judgment_id}",
        subject=f"subject {judgment_id}",
        facet="retention",
        scope=scope,
        evidence_ids=(evidence_id,),
    )
    return _judgment(
        judgment_id, CreateAddressProposal(candidate=candidate), evidence_id=evidence_id
    )


def _context_json(request: ReasoningRequest) -> str:
    return contrastive_context_module.comparison_context_json(request.comparison_context)


def test_shared_predecessor_never_widens_call_two_into_another_scope() -> None:
    """EV-1 is effective evidence of live CLAIM_1 (ADDR_1, scope A) AND of live CLAIM_B
    (ADDR_B, scope B). Assimilating EV-2 (supersedes EV-1) for scope A may expose, and
    widen Call 2 to, ADDR_1 only: scope B stays invisible to both calls and to the
    claim neighbourhood, even though the same predecessor structurally supports it.
    """
    governor = _governor()
    _seed_address_and_claim(governor)
    assert governor.submit(_create_in("J-cB", "EV-1", (SCOPE_B,))).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-clB", ADDR_B, "EV-1", "30")).route is AdmissionRoute.APPLY
    assert governor.state().semantic.addresses[ADDR_B].scope == (SCOPE_B,)
    assert governor.state().semantic.claims[CLAIM_B].evidence_ids == ("EV-1",)
    reasoner = ScriptedReasoner(
        [[_bind("J-b1", ADDR_1, "EV-2")], [_support("J-s1", CLAIM_1, "EV-2")]]
    )

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    call1, call2 = reasoner.requests
    assert _address_ids(call1) == [ADDR_1]
    assert _claim_ids(call1) == [CLAIM_1]
    _assert_v2_transition_touches_claim_1(call1)
    assert outcome.neighborhood == (ADDR_1,)
    assert outcome.claim_neighborhood == (ADDR_1,)
    assert _address_ids(call2) == [ADDR_1]
    assert _claim_ids(call2) == [CLAIM_1]
    _assert_v2_transition_touches_claim_1(call2)
    for request in (call1, call2):
        assert ADDR_B not in _context_json(request)
        assert CLAIM_B not in _context_json(request)
    assert outcome.calls_made == 2
    assert len(reasoner.requests) == 2


def test_project_wide_address_remains_eligible_for_a_scoped_delta() -> None:
    """Control: an active address with ``scope == ()`` is in Call 1's in-scope set for
    scope A, so its live claim may be structurally touched and widen Call 2 exactly
    like a scope-A address. The eligibility boundary is the profile set, not the
    scope literal.
    """
    governor = _governor()
    _seed_address(governor)  # ADDR_1 (scope A), no claim
    assert governor.submit(_create_in("J-cPW", "EV-1", ())).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-clPW", ADDR_PW, "EV-1", "9")).route is AdmissionRoute.APPLY
    assert governor.state().semantic.addresses[ADDR_PW].scope == ()
    reasoner = ScriptedReasoner([[_bind("J-b1", ADDR_1, "EV-2")], []])

    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    call1, call2 = reasoner.requests
    assert _address_ids(call1) == sorted((ADDR_1, ADDR_PW))
    assert _claim_ids(call1) == [CLAIM_PW]
    (transition,) = call1.comparison_context.transitions
    assert transition.touched_claim_ids == (CLAIM_PW,)
    assert transition.touched_address_ids == (ADDR_PW,)
    assert outcome.neighborhood == (ADDR_1,)
    assert outcome.claim_neighborhood == tuple(sorted((ADDR_1, ADDR_PW)))
    assert _address_ids(call2) == sorted((ADDR_1, ADDR_PW))
    assert _claim_ids(call2) == [CLAIM_PW]
    (transition_2,) = call2.comparison_context.transitions
    assert transition_2.touched_claim_ids == (CLAIM_PW,)
    assert transition_2.touched_address_ids == (ADDR_PW,)
    assert outcome.calls_made == 2
    assert len(reasoner.requests) == 2

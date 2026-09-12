"""Bounded assimilation context assembly (9P Task 7 -> 9P2 Task T4; spec §11, §12, §18).

Two frontier calls per delta. Call 1 sees the delta, descriptors of every active in-scope
address (hard threshold, never a fallback), the LIVE claims at those addresses and the
structurally compiled comparison context for the delta. Call 2 sees the SAME delta ONLY,
the already-widened neighbourhood addresses, the LIVE claims at them and a call-specific
comparison context.

9P2 rule (supersedes the 9P "zero historical reread" wording): current citable evidence
remains delta-only; structurally selected predecessor material may appear only in the
non-citable comparison context. Selection never decides meaning: no ranking, no
similarity, no top-K, no judgment construction.

Every ledger here is driven through the real ``SemanticGovernor`` over an
``InMemoryEventStore`` so admissions, minted ids and supersessions are the reducer's own;
the threshold test hand-builds a large ``SemanticState`` directly.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from pathlib import Path

import pytest

import foundry.application.assimilation_context as assimilation_context_module
import foundry.application.context_errors as context_errors_module
import foundry.application.contrastive_context as contrastive_context_module
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.assimilation_context import (
    CANDIDATE_ADDRESS_THRESHOLD,
    ContextUnsupported,
    active_in_scope_addresses,
    assemble_assimilation_request,
    assemble_claim_request,
    live_claims_at,
    neighborhood_from_decisions,
)
from foundry.application.contrastive_context import (
    compile_comparison_context,
    contrastive_address_ids,
    historical_evidence_ids,
)
from foundry.application.contrastive_diff import render_unified_diff
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionDecision, AdmissionPolicy
from foundry.domain.common import Authority, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticAddress,
    SemanticCandidate,
)
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_state import SemanticState
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.ports.semantic_reasoner import (
    ComparisonContext,
    ContextInclusionEdge,
    ContextRelation,
    ReasoningRequest,
)

PROJECT = "PROJ-CTX"
T0 = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="p1")
MODEL_B = ReasonerFingerprint(provider="anthropic", model="claude-opus-5", policy_version="p1")

SCOPE_A = "A"
SCOPE_B = "B"

ADDR_A = address_id_for(PROJECT, "J-cA")
ADDR_B = address_id_for(PROJECT, "J-cB")
ADDR_C = address_id_for(PROJECT, "J-cC")
ADDR_D = address_id_for(PROJECT, "J-cD")
ADDR_N = address_id_for(PROJECT, "J-cN")
CLAIM_A = claim_id_for(PROJECT, "J-clA")
CLAIM_A_OLD = claim_id_for(PROJECT, "J-clA-old")
CLAIM_B = claim_id_for(PROJECT, "J-clB")
CLAIM_C = claim_id_for(PROJECT, "J-clC")

CALL1_KINDS = frozenset({JudgmentKind.BIND_TO_ADDRESS, JudgmentKind.CREATE_ADDRESS})
CALL2_KINDS = frozenset(
    {
        JudgmentKind.SUPPORTS_CLAIM,
        JudgmentKind.ASSERT_CLAIM,
        JudgmentKind.SUPERSEDE,
        JudgmentKind.CONFLICTS_WITH,
    }
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- builders ---------------------------------------------------------------------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0.replace(minute=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _governor(store: InMemoryEventStore) -> SemanticGovernor:
    clock = _clock()
    return SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )


def _evidence(
    evidence_id: str,
    scope: tuple[str, ...],
    *,
    artifact_ref: str | None = None,
    supersedes: str | None = None,
) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=f"Evidence body {evidence_id}.",
        observed_at=T0,
        scope=scope,
        artifact_ref=artifact_ref,
        supersedes_evidence_id=supersedes,
    )


def _candidate(candidate_id: str, scope: tuple[str, ...], evidence_id: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject=f"subject {candidate_id}",
        facet="retention",
        scope=scope,
        evidence_ids=(evidence_id,),
    )


def _judgment(
    judgment_id: str,
    proposal: JudgmentProposal,
    *,
    evidence_id: str,
    reasoner: ReasonerFingerprint = MODEL_A,
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


def _create(judgment_id: str, scope: tuple[str, ...], evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(candidate=_candidate(f"CAND-{judgment_id}", scope, evidence_id)),
        evidence_id=evidence_id,
    )


def _bind(
    judgment_id: str, candidate_id: str, address_id: str, evidence_id: str
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        BindToAddressProposal(
            candidate=_candidate(candidate_id, (SCOPE_A,), evidence_id), address_id=address_id
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


def _supersede(
    judgment_id: str, target: str, evidence_id: str, *, reasoner: ReasonerFingerprint
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupersedeProposal(target_judgment_id=target, reason="The older record is corrected."),
        evidence_id=evidence_id,
        reasoner=reasoner,
    )


def _apply_supersede(governor: SemanticGovernor, tag: str, target: str, evidence_id: str) -> None:
    """Supersede ``target`` and get it APPLIED via independent corroboration."""
    first = governor.submit(_supersede(f"J-sup-{tag}-a", target, evidence_id, reasoner=MODEL_A))
    assert first.route is AdmissionRoute.REQUIRE_SECOND_LENS
    second = governor.submit(_supersede(f"J-sup-{tag}-b", target, evidence_id, reasoner=MODEL_B))
    assert second.route is AdmissionRoute.APPLY


def _story() -> SemanticGovernor:
    """Scope A: ``ADDR_A`` (claim citing EV-A, supported by EV-S, one superseded old claim
    citing EV-OLD) and ``ADDR_C`` (claim citing EV-C). Scope B: ``ADDR_B`` (claim citing
    EV-B). ``ADDR_D`` (scope A) has a superseded CREATE and is not active. EV-U is
    ingested in scope A and cited by nothing.
    """
    governor = _governor(InMemoryEventStore())
    for evidence_id, scope, artifact in (
        ("EV-A", (SCOPE_A,), "docs/a.md"),
        ("EV-OLD", (SCOPE_A,), "docs/old.md"),
        ("EV-S", (SCOPE_A,), "docs/s.md"),
        ("EV-C", (SCOPE_A,), "docs/c.md"),
        ("EV-U", (SCOPE_A,), "docs/u.md"),
        ("EV-D", (SCOPE_A,), "docs/d.md"),
        ("EV-B", (SCOPE_B,), "docs/b.md"),
    ):
        governor.ingest(_evidence(evidence_id, scope, artifact_ref=artifact))
    assert governor.submit(_create("J-cA", (SCOPE_A,), "EV-A")).route is AdmissionRoute.APPLY
    assert governor.submit(_create("J-cB", (SCOPE_B,), "EV-B")).route is AdmissionRoute.APPLY
    assert governor.submit(_create("J-cC", (SCOPE_A,), "EV-C")).route is AdmissionRoute.APPLY
    assert governor.submit(_create("J-cD", (SCOPE_A,), "EV-D")).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-clA-old", ADDR_A, "EV-OLD", "3")).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-clA", ADDR_A, "EV-A", "7")).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-clB", ADDR_B, "EV-B", "30")).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-clC", ADDR_C, "EV-C", "14")).route is AdmissionRoute.APPLY
    assert governor.submit(_support("J-sA", CLAIM_A, "EV-S")).route is AdmissionRoute.APPLY
    _apply_supersede(governor, "old", "J-clA-old", "EV-A")
    _apply_supersede(governor, "cD", "J-cD", "EV-D")
    return governor


def _delta_a2() -> EvidenceItem:
    return _evidence("EV-A2", (SCOPE_A,), artifact_ref="docs/a.md", supersedes="EV-A")


def _evidence_ids(request: ReasoningRequest) -> tuple[str, ...]:
    return tuple(item.evidence_id for item in request.evidence)


def _claim_ids(request: ReasoningRequest) -> tuple[str, ...]:
    return tuple(claim.claim_id for claim in request.known_claims)


def _profile_pairs(context: ComparisonContext) -> tuple[tuple[str, str], ...]:
    return tuple((edge.source_id, edge.target_id) for edge in context.active_claim_profile_edges)


def _large_state(address_count: int) -> IntentState:
    judgment_ids = tuple(f"J-{index}" for index in range(address_count))
    addresses = {
        address_id_for(PROJECT, judgment_id): SemanticAddress(
            address_id=address_id_for(PROJECT, judgment_id),
            project_id=PROJECT,
            subject=f"subject {judgment_id}",
            facet="retention",
            scope=(SCOPE_A,),
            created_by_judgment_id=judgment_id,
        )
        for judgment_id in judgment_ids
    }
    return IntentState(
        project_id=PROJECT,
        semantic=SemanticState(addresses=addresses, applied_judgment_ids=judgment_ids),
    )


def _assert_a2_transition_touches_claim_a(context: ComparisonContext, state: IntentState) -> None:
    """EV-A2 supersedes EV-A; EV-A is effective evidence of live CLAIM_A at ADDR_A."""
    assert len(context.transitions) == 1
    transition = context.transitions[0]
    assert transition.current_evidence_id == "EV-A2"
    assert transition.predecessor_evidence_id == "EV-A"
    assert transition.artifact_ref == "docs/a.md"
    assert transition.touched_claim_ids == (CLAIM_A,)
    assert transition.touched_address_ids == (ADDR_A,)
    assert transition.inclusion_edges == (
        ContextInclusionEdge(
            source_id="EV-A2", relation=ContextRelation.SUPERSEDES, target_id="EV-A"
        ),
        ContextInclusionEdge(
            source_id="EV-A", relation=ContextRelation.EFFECTIVE_EVIDENCE_OF, target_id=CLAIM_A
        ),
        ContextInclusionEdge(
            source_id=CLAIM_A, relation=ContextRelation.CLAIM_AT_ADDRESS, target_id=ADDR_A
        ),
    )
    assert transition.historical_diff == render_unified_diff(
        state.semantic.evidence["EV-A"], _delta_a2()
    )
    assert "--- evidence:EV-A\n" in transition.historical_diff
    assert "+++ evidence:EV-A2\n" in transition.historical_diff
    assert "-Evidence body EV-A." in transition.historical_diff
    assert "+Evidence body EV-A2." in transition.historical_diff


# --- ContextUnsupported identity ---------------------------------------------------


def test_context_unsupported_is_the_shared_context_error() -> None:
    assert ContextUnsupported is context_errors_module.ContextUnsupported
    assert (
        assimilation_context_module.ContextUnsupported is context_errors_module.ContextUnsupported
    )
    assert issubclass(ContextUnsupported, RuntimeError)


# --- live claims ------------------------------------------------------------------


def test_live_claims_at_returns_active_assert_claims_sorted_by_id() -> None:
    state = _story().state()

    as_tuple = live_claims_at(state, (ADDR_C, ADDR_A, ADDR_B))
    as_frozenset = live_claims_at(state, frozenset((ADDR_C, ADDR_A, ADDR_B)))

    assert as_tuple == as_frozenset
    assert tuple(claim.claim_id for claim in as_tuple) == tuple(sorted((CLAIM_A, CLAIM_B, CLAIM_C)))
    assert as_tuple == tuple(
        state.semantic.claims[claim_id] for claim_id in sorted((CLAIM_A, CLAIM_B, CLAIM_C))
    )
    # The superseded claim at ADDR_A is not live; nothing was ever asserted at ADDR_D.
    assert CLAIM_A_OLD not in {claim.claim_id for claim in as_tuple}
    assert live_claims_at(state, (ADDR_D,)) == ()
    assert live_claims_at(state, ()) == ()


# --- call 1 -------------------------------------------------------------------------


def test_call1_sends_descriptors_with_live_claim_profiles_and_bind_create_only() -> None:
    """9P2 spec §11: Call 1 sees active claim profiles but may still only bind or create."""
    governor = _story()
    governor.ingest(_delta_a2())
    state = governor.state()
    delta = (_delta_a2(),)

    in_scope = active_in_scope_addresses(state, SCOPE_A)
    request = assemble_assimilation_request(
        project_id=PROJECT, delta=delta, state=state, scope=SCOPE_A
    )

    assert tuple(address.address_id for address in in_scope) == tuple(sorted((ADDR_A, ADDR_C)))
    assert request.project_id == PROJECT
    assert request.evidence == delta
    assert request.focus_object_ids == ()
    assert all(isinstance(address, SemanticAddress) for address in request.known_addresses)
    assert request.known_addresses == in_scope
    assert request.known_addresses == tuple(
        state.semantic.addresses[address_id] for address_id in sorted((ADDR_A, ADDR_C))
    )
    # Every LIVE claim at the visible addresses, sorted by claim id...
    assert _claim_ids(request) == tuple(sorted((CLAIM_A, CLAIM_C)))
    assert request.known_claims == live_claims_at(state, (ADDR_A, ADDR_C))
    # ...while the task stays identity resolution only.
    assert request.allowed_judgment_kinds == CALL1_KINDS
    # The comparison context is the T3 compiler's output over the visible addresses.
    assert request.comparison_context == compile_comparison_context(
        delta=delta, state=state, profile_address_ids=(ADDR_A, ADDR_C)
    )
    assert request.comparison_context.active_claim_profile_edges == tuple(
        ContextInclusionEdge(
            source_id=address_id,
            relation=ContextRelation.ACTIVE_CLAIM_PROFILE,
            target_id=claim_id,
        )
        for address_id, claim_id in sorted(((ADDR_A, CLAIM_A), (ADDR_C, CLAIM_C)))
    )


def test_call1_contains_transition_when_delta_supersedes_effective_evidence_of_live_claim() -> None:
    governor = _story()
    governor.ingest(_delta_a2())
    state = governor.state()
    delta = (_delta_a2(),)
    assert derive_view(state.semantic).effective_evidence[CLAIM_A] == ("EV-A", "EV-S")

    request = assemble_assimilation_request(
        project_id=PROJECT, delta=delta, state=state, scope=SCOPE_A
    )

    _assert_a2_transition_touches_claim_a(request.comparison_context, state)
    assert contrastive_address_ids(request.comparison_context) == (ADDR_A,)
    # Citable evidence is the delta only; the predecessor is comparison material.
    assert _evidence_ids(request) == ("EV-A2",)
    assert historical_evidence_ids(request.comparison_context) == ("EV-A",)
    assert "EV-A" not in _evidence_ids(request)
    assert "EV-S" not in _evidence_ids(request)


def test_call1_without_lineage_has_no_transition_but_keeps_claim_profiles() -> None:
    governor = _story()
    fresh = _evidence("EV-F", (SCOPE_A,), artifact_ref="docs/f.md")
    governor.ingest(fresh)
    state = governor.state()

    request = assemble_assimilation_request(
        project_id=PROJECT, delta=(fresh,), state=state, scope=SCOPE_A
    )

    assert request.evidence == (fresh,)
    assert request.comparison_context.transitions == ()
    assert _claim_ids(request) == tuple(sorted((CLAIM_A, CLAIM_C)))
    assert _profile_pairs(request.comparison_context) == tuple(
        sorted(((ADDR_A, CLAIM_A), (ADDR_C, CLAIM_C)))
    )
    assert request.allowed_judgment_kinds == CALL1_KINDS


def test_call1_excludes_other_scope_and_inactive_claims_and_addresses() -> None:
    governor = _story()
    governor.ingest(_delta_a2())
    state = governor.state()

    request = assemble_assimilation_request(
        project_id=PROJECT, delta=(_delta_a2(),), state=state, scope=SCOPE_A
    )

    visible_addresses = {address.address_id for address in request.known_addresses}
    visible_claims = set(_claim_ids(request))
    # scope B is invisible to a scope-A call; the superseded CREATE is not active.
    assert ADDR_B not in visible_addresses
    assert ADDR_D not in visible_addresses
    assert CLAIM_B not in visible_claims
    # the superseded claim at ADDR_A is not live and is never profiled.
    assert CLAIM_A_OLD not in visible_claims
    profiled = set(_profile_pairs(request.comparison_context))
    assert (ADDR_B, CLAIM_B) not in profiled
    assert (ADDR_A, CLAIM_A_OLD) not in profiled
    assert {source for source, _ in profiled} <= visible_addresses
    assert {target for _, target in profiled} == visible_claims
    # the superseded claim is not structurally touched either (not in effective evidence).
    for transition in request.comparison_context.transitions:
        assert CLAIM_A_OLD not in transition.touched_claim_ids
        assert CLAIM_B not in transition.touched_claim_ids


def test_call1_above_threshold_raises_context_unsupported_before_compile_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert CANDIDATE_ADDRESS_THRESHOLD == 200
    fresh = _evidence("EV-F", (SCOPE_A,), artifact_ref="docs/f.md")
    delta = (fresh,)

    at_threshold = assemble_assimilation_request(
        project_id=PROJECT, delta=delta, state=_large_state(200), scope=SCOPE_A
    )
    assert len(at_threshold.known_addresses) == 200
    assert at_threshold.known_claims == ()
    assert at_threshold.comparison_context == ComparisonContext()
    assert at_threshold.allowed_judgment_kinds == CALL1_KINDS

    compile_calls: list[object] = []

    def _record(**kwargs: object) -> ComparisonContext:
        compile_calls.append(kwargs)
        raise AssertionError("compile_comparison_context must not run above the threshold")

    monkeypatch.setattr(assimilation_context_module, "compile_comparison_context", _record)
    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_ABOVE_THRESHOLD") as raised:
        assemble_assimilation_request(
            project_id=PROJECT, delta=delta, state=_large_state(201), scope=SCOPE_A
        )
    assert "201" in str(raised.value)
    assert "200" in str(raised.value)
    assert compile_calls == []


def test_call1_context_limit_refusal_propagates_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governor = _story()
    governor.ingest(_delta_a2())
    state = governor.state()

    monkeypatch.setattr(contrastive_context_module, "MAX_COMPARISON_CONTEXT_CHARS", 0)
    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_COMPARISON_CONTEXT"):
        assemble_assimilation_request(
            project_id=PROJECT, delta=(_delta_a2(),), state=state, scope=SCOPE_A
        )

    monkeypatch.undo()

    def _oversized(*_args: object) -> str:
        raise ContextUnsupported("UNSUPPORTED_TRANSITION_DIFF: forced by test")

    monkeypatch.setattr(contrastive_context_module, "render_unified_diff", _oversized)
    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_TRANSITION_DIFF"):
        assemble_assimilation_request(
            project_id=PROJECT, delta=(_delta_a2(),), state=state, scope=SCOPE_A
        )


# --- neighbourhood ------------------------------------------------------------------


def test_neighborhood_is_only_addresses_touched_by_applied_bindings_and_creations() -> None:
    governor = _story()
    governor.ingest(_delta_a2())

    decisions: list[AdmissionDecision] = []
    decisions.append(governor.submit(_create("J-cN", (SCOPE_A,), "EV-A2")))
    decisions.append(governor.submit(_bind("J-bA", "CAND-new", ADDR_A, "EV-A2")))
    # A candidate already bound by an active judgment: structurally REJECTed.
    decisions.append(governor.submit(_bind("J-bC", "CAND-J-cC", ADDR_C, "EV-A2")))
    # An applied claim is not a binding or a creation; it touches nothing here.
    decisions.append(governor.submit(_claim("J-clB2", ADDR_B, "EV-A2", "9")))
    assert [decision.route for decision in decisions] == [
        AdmissionRoute.APPLY,
        AdmissionRoute.APPLY,
        AdmissionRoute.REJECT,
        AdmissionRoute.APPLY,
    ]

    neighborhood = neighborhood_from_decisions(governor.state(), tuple(decisions))

    assert neighborhood == tuple(sorted((ADDR_A, ADDR_N)))
    assert ADDR_C not in neighborhood
    assert ADDR_B not in neighborhood
    assert neighborhood_from_decisions(governor.state(), ()) == ()
    reversed_order = neighborhood_from_decisions(governor.state(), tuple(reversed(decisions)))
    assert reversed_order == neighborhood


# --- call 2 ---------------------------------------------------------------------------


def test_call2_evidence_is_delta_only_and_predecessor_appears_only_in_comparison_context() -> None:
    """9P2 rule: citable evidence stays delta-only; the predecessor is non-citable context.

    T1: EV-A supports CLAIM_A at ADDR_A (own evidence) and EV-S supports it through an
    active SUPPORTS_CLAIM record. T2: the delta EV-A2 supersedes EV-A. Call 2 receives
    the delta ONLY as evidence, the neighbourhood address, its live (old current) claim
    and the compiled transition EV-A -> EV-A2 with its diff in ``comparison_context``.
    """
    governor = _story()
    governor.ingest(_delta_a2())
    state = governor.state()
    delta = (_delta_a2(),)
    assert delta[0].supersedes_evidence_id == "EV-A"
    assert state.semantic.claims[CLAIM_A].evidence_ids == ("EV-A",)
    # An active SUPPORTS_CLAIM record makes EV-S effective evidence for CLAIM_A (view rule).
    assert derive_view(state.semantic).effective_evidence[CLAIM_A] == ("EV-A", "EV-S")

    request = assemble_claim_request(
        project_id=PROJECT, delta=delta, state=state, neighborhood=(ADDR_A,)
    )

    assert request.project_id == PROJECT
    assert request.known_addresses == (state.semantic.addresses[ADDR_A],)
    # The old current claim is visible as a known claim...
    assert _claim_ids(request) == (CLAIM_A,)
    assert request.known_claims[0].created_by_judgment_id == "J-clA"
    assert request.known_claims == (state.semantic.claims[CLAIM_A],)
    assert request.known_claims == live_claims_at(state, (ADDR_A,))
    # ...it still cites its historical evidence by id (never mutated)...
    assert request.known_claims[0].evidence_ids == ("EV-A",)
    # ...but the request's evidence is THE DELTA ONLY: EV-A and EV-S are never resent.
    assert request.evidence == delta
    assert _evidence_ids(request) == ("EV-A2",)
    assert "EV-A" not in _evidence_ids(request)
    assert "EV-S" not in _evidence_ids(request)
    assert request.evidence[0].artifact_ref == "docs/a.md"
    assert request.evidence[0].supersedes_evidence_id == "EV-A"
    assert request.allowed_judgment_kinds == CALL2_KINDS
    assert request.focus_object_ids == ()
    # The predecessor id and diff appear ONLY in the non-citable comparison context.
    assert request.comparison_context == compile_comparison_context(
        delta=delta, state=state, profile_address_ids=(ADDR_A,)
    )
    _assert_a2_transition_touches_claim_a(request.comparison_context, state)
    assert historical_evidence_ids(request.comparison_context) == ("EV-A",)
    assert request.comparison_context.active_claim_profile_edges == (
        ContextInclusionEdge(
            source_id=ADDR_A, relation=ContextRelation.ACTIVE_CLAIM_PROFILE, target_id=CLAIM_A
        ),
    )
    # claims at untouched addresses are absent.
    assert CLAIM_C not in set(_claim_ids(request))
    assert CLAIM_B not in set(_claim_ids(request))
    # Durable state is untouched: historical evidence and the support record persist.
    assert "EV-A" in state.semantic.evidence
    assert "EV-S" in state.semantic.evidence
    assert state.semantic.claims[CLAIM_A].evidence_ids == ("EV-A",)


def test_call2_evidence_is_exactly_the_delta_for_any_neighbourhood() -> None:
    governor = _story()
    governor.ingest(_delta_a2())
    state = governor.state()
    delta = (_delta_a2(),)

    request = assemble_claim_request(
        project_id=PROJECT, delta=delta, state=state, neighborhood=(ADDR_A, ADDR_C)
    )

    assert _claim_ids(request) == tuple(sorted((CLAIM_A, CLAIM_C)))
    assert request.evidence == delta
    assert _evidence_ids(request) == ("EV-A2",)
    # Nothing historical is ever sent AS EVIDENCE: own evidence of live claims (EV-A,
    # EV-C), active support evidence (EV-S), uncited in-scope evidence (EV-U), evidence
    # of a superseded claim (EV-OLD) and evidence of an inactive address (EV-D).
    for evidence_id in ("EV-A", "EV-C", "EV-S", "EV-U", "EV-OLD", "EV-D", "EV-B"):
        assert evidence_id not in _evidence_ids(request)
    assert CLAIM_A_OLD not in set(_claim_ids(request))
    # Only the structurally reached predecessor is shown as history, nothing else.
    assert historical_evidence_ids(request.comparison_context) == ("EV-A",)
    assert _profile_pairs(request.comparison_context) == tuple(
        sorted(((ADDR_A, CLAIM_A), (ADDR_C, CLAIM_C)))
    )

    # A multi-item delta is passed through in the caller's order, never re-sorted; an
    # item without lineage contributes no transition.
    ev_z = _evidence("EV-Z", (SCOPE_A,), artifact_ref="docs/z.md")
    two = assemble_claim_request(
        project_id=PROJECT, delta=(_delta_a2(), ev_z), state=state, neighborhood=(ADDR_A,)
    )
    assert two.evidence == (_delta_a2(), ev_z)
    assert [t.current_evidence_id for t in two.comparison_context.transitions] == ["EV-A2"]

    # An empty neighbourhood profiles nothing; the explicit lineage transition remains.
    empty = assemble_claim_request(project_id=PROJECT, delta=delta, state=state, neighborhood=())
    assert empty.known_addresses == ()
    assert empty.known_claims == ()
    assert empty.evidence == delta
    assert empty.comparison_context.active_claim_profile_edges == ()
    assert empty.comparison_context == compile_comparison_context(
        delta=delta, state=state, profile_address_ids=()
    )


def test_call2_context_limit_refusal_propagates_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governor = _story()
    governor.ingest(_delta_a2())
    state = governor.state()

    monkeypatch.setattr(contrastive_context_module, "MAX_COMPARISON_CONTEXT_CHARS", 0)
    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_COMPARISON_CONTEXT"):
        assemble_claim_request(
            project_id=PROJECT, delta=(_delta_a2(),), state=state, neighborhood=(ADDR_A,)
        )


# --- layer rules --------------------------------------------------------------------


def test_assembly_emits_no_judgment_and_reads_no_confidence() -> None:
    source = Path(assimilation_context_module.__file__).read_text(encoding="utf-8")

    assert "SemanticJudgment(" not in source
    assert "confidence" not in source
    assert "Context Compiler" in source
    assert "difflib" not in source
    # The refusal type is shared with the compiler, not redefined here.
    assert "class ContextUnsupported" not in source
    assert "from foundry.application.context_errors import ContextUnsupported" in source
    # The 9P wording that historical material is never shown is superseded.
    assert "zero historical reread" not in source.lower()
    assert "never resent" not in source.lower()
    assert "non-citable" in source


def test_assembly_is_pure() -> None:
    governor = _story()
    governor.ingest(_delta_a2())
    state = governor.state()
    before = state.model_dump(mode="json")
    delta = (_delta_a2(),)
    decisions = (
        AdmissionDecision(judgment_id="J-cA", route=AdmissionRoute.APPLY, reasons=("LOW_RISK",)),
    )

    first_call1 = assemble_assimilation_request(
        project_id=PROJECT, delta=delta, state=state, scope=SCOPE_A
    )
    neighborhood = neighborhood_from_decisions(state, decisions)
    first_call2 = assemble_claim_request(
        project_id=PROJECT, delta=delta, state=state, neighborhood=neighborhood
    )
    second_call1 = assemble_assimilation_request(
        project_id=PROJECT, delta=delta, state=state, scope=SCOPE_A
    )
    second_call2 = assemble_claim_request(
        project_id=PROJECT, delta=delta, state=state, neighborhood=neighborhood
    )

    assert neighborhood == (ADDR_A,)
    assert state.model_dump(mode="json") == before
    assert governor.state().model_dump(mode="json") == before
    assert first_call1 == second_call1
    assert first_call2 == second_call2
    assert first_call1.comparison_context == second_call1.comparison_context
    assert first_call2.comparison_context == second_call2.comparison_context

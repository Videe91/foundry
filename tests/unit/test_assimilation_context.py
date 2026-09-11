"""Bounded assimilation context assembly (9P Task 7; spec §18, §19, §34).

Two frontier calls per delta. Call 1 sees the delta plus descriptors of every active
in-scope address (hard threshold, never a fallback). Call 2 sees the SAME delta ONLY plus
the neighbourhood addresses touched by applied bindings/creations and the LIVE claims at
them; unchanged historical evidence is never resent (spec §19: the persistent arm
re-reads ZERO unchanged evidence — claims cite it by id and the delta carries lineage).
Selection never decides meaning: no ranking, no similarity, no top-K, no judgment
construction.

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
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.assimilation_context import (
    CANDIDATE_ADDRESS_THRESHOLD,
    ContextUnsupported,
    active_in_scope_addresses,
    assemble_assimilation_request,
    assemble_claim_request,
    neighborhood_from_decisions,
)
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
from foundry.ports.semantic_reasoner import ReasoningRequest

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


# --- call 1 -------------------------------------------------------------------------


def test_call1_sends_descriptors_only_and_no_claims() -> None:
    governor = _story()
    state = governor.state()
    delta = (_delta_a2(),)

    in_scope = active_in_scope_addresses(state, SCOPE_A)
    request = assemble_assimilation_request(
        project_id=PROJECT, delta=delta, state=state, scope=SCOPE_A
    )

    assert tuple(address.address_id for address in in_scope) == tuple(sorted((ADDR_A, ADDR_C)))
    assert request.project_id == PROJECT
    assert request.evidence == delta
    assert request.known_claims == ()
    assert request.focus_object_ids == ()
    assert all(isinstance(address, SemanticAddress) for address in request.known_addresses)
    assert request.known_addresses == in_scope
    assert request.known_addresses == tuple(
        state.semantic.addresses[address_id] for address_id in sorted((ADDR_A, ADDR_C))
    )
    assert request.allowed_judgment_kinds == CALL1_KINDS
    # scope B is invisible to a scope-A call; the superseded CREATE is not active.
    assert ADDR_B not in {address.address_id for address in request.known_addresses}
    assert ADDR_D not in {address.address_id for address in request.known_addresses}


def test_call1_above_threshold_raises_context_unsupported_never_falls_back() -> None:
    assert CANDIDATE_ADDRESS_THRESHOLD == 200
    assert issubclass(ContextUnsupported, RuntimeError)
    delta = (_delta_a2(),)

    at_threshold = assemble_assimilation_request(
        project_id=PROJECT, delta=delta, state=_large_state(200), scope=SCOPE_A
    )
    assert len(at_threshold.known_addresses) == 200

    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_ABOVE_THRESHOLD") as raised:
        assemble_assimilation_request(
            project_id=PROJECT, delta=delta, state=_large_state(201), scope=SCOPE_A
        )
    assert "201" in str(raised.value)
    assert "200" in str(raised.value)


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


def test_call2_sends_delta_only_and_never_rereads_unchanged_evidence() -> None:
    """Spec §19: at T2+ the persistent arm re-reads ZERO unchanged evidence.

    T1: EV-A supports CLAIM_A at ADDR_A (own evidence) and EV-S supports it through an
    active SUPPORTS_CLAIM record. T2: the delta EV-A2 supersedes EV-A. Call 2 receives
    the delta ONLY plus the neighbourhood address and its live claim; the claim still
    cites EV-A by id, and the delta item carries ``supersedes_evidence_id == "EV-A"``, so
    chronology reaches the model as data without any historical bytes being resent.
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
    assert tuple(claim.claim_id for claim in request.known_claims) == (CLAIM_A,)
    assert request.known_claims[0].created_by_judgment_id == "J-clA"
    assert request.known_claims == (state.semantic.claims[CLAIM_A],)
    # The known claim still cites its historical evidence by id (never mutated)...
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
    # claims at untouched addresses are absent.
    assert CLAIM_C not in {claim.claim_id for claim in request.known_claims}
    assert CLAIM_B not in {claim.claim_id for claim in request.known_claims}
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

    assert tuple(claim.claim_id for claim in request.known_claims) == tuple(
        sorted((CLAIM_A, CLAIM_C))
    )
    assert request.evidence == delta
    assert _evidence_ids(request) == ("EV-A2",)
    # Nothing historical is ever sent: own evidence of live claims (EV-A, EV-C), active
    # support evidence (EV-S), uncited in-scope evidence (EV-U), evidence of a superseded
    # claim (EV-OLD) and evidence of an inactive address (EV-D).
    for evidence_id in ("EV-A", "EV-C", "EV-S", "EV-U", "EV-OLD", "EV-D", "EV-B"):
        assert evidence_id not in _evidence_ids(request)
    assert CLAIM_A_OLD not in {claim.claim_id for claim in request.known_claims}

    # A multi-item delta is passed through in the caller's order, never re-sorted.
    ev_z = _evidence("EV-Z", (SCOPE_A,), artifact_ref="docs/z.md")
    two = assemble_claim_request(
        project_id=PROJECT, delta=(_delta_a2(), ev_z), state=state, neighborhood=(ADDR_A,)
    )
    assert two.evidence == (_delta_a2(), ev_z)

    empty = assemble_claim_request(project_id=PROJECT, delta=delta, state=state, neighborhood=())
    assert empty.known_addresses == ()
    assert empty.known_claims == ()
    assert empty.evidence == delta


# --- layer rules --------------------------------------------------------------------


def test_assembly_emits_no_judgment_and_reads_no_confidence() -> None:
    source = Path(assimilation_context_module.__file__).read_text(encoding="utf-8")

    assert "SemanticJudgment(" not in source
    assert "confidence" not in source
    assert "Context Compiler" in source
    assert "difflib" not in source


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

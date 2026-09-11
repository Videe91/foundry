"""Intent Intelligence v2 core lifecycle (plan §8.3; spec §18, §19.1, §22, §23.1).

One event-sourced story driven end to end through ``SemanticGovernor`` over an
``InMemoryEventStore`` with deterministic ``ScriptedSemanticReasoner`` fakes. No
Postgres, no network, no model calls: a socket guard is installed for the whole
module and a test proves it is live.

Lettered assertions follow the plan: L evidence ingestion, H low-risk creation,
G/I material judgments never apply alone, C/E independent corroboration applies,
F conflicts are preserved as DISPUTED, D supersession by human authority reverses the
interpretation while the old judgment stays readable, M blast radius through three
derivation levels, N/O scoped handoff, P replay reproduces state and view.

The exact ledger length is asserted so the story documents itself.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.fake_reasoner import ScriptedSemanticReasoner
from foundry.application.handoff import build_intent_decision_handoff
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, Materiality, Provenance, SourceKind
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    SemanticObjectPayload,
    StoredEvent,
    parse_event,
)
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.handoff import HANDOFF_VERSION
from foundry.domain.semantic import AuthorityRecord, Intent, Requirement
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    IssueEpistemicState,
    SemanticCandidate,
)
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    EquivalentProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_view import derive_view
from foundry.ports.semantic_reasoner import ReasoningRequest

PROJECT = "PROJ-LIFECYCLE"
OCCURRED_AT = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
M1 = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")
M2 = ReasonerFingerprint(provider="anthropic", model="claude-opus-5", policy_version="p1")
ALICE = "human://alice"
HUMAN_ALICE = ReasonerFingerprint(provider="human", model=ALICE, policy_version="p1")
RETENTION = ("retention",)
BILLING = ("billing",)
SHIPPING = ("shipping",)

EXPECTED_LEDGER_LENGTH = 49


# --- no network, ever ---------------------------------------------------------------


def _refuse_network(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("network access is forbidden in the semantic lifecycle test")


@pytest.fixture(autouse=True, scope="module")
def socket_guard() -> Iterator[None]:
    patcher = pytest.MonkeyPatch()
    patcher.setattr(socket.socket, "connect", _refuse_network)
    patcher.setattr(socket, "create_connection", _refuse_network)
    try:
        yield
    finally:
        patcher.undo()


def test_socket_guard_is_live() -> None:
    with pytest.raises(RuntimeError, match="forbidden"), socket.socket() as sock:
        sock.connect(("127.0.0.1", 9))
    with pytest.raises(RuntimeError, match="forbidden"):
        socket.create_connection(("127.0.0.1", 9))


# --- builders -----------------------------------------------------------------------


def _clock() -> Callable[[], datetime]:
    ticks = count()
    return lambda: OCCURRED_AT.replace(minute=next(ticks) % 60, second=0)


def _id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks):03d}"


def _governor(store: InMemoryEventStore) -> SemanticGovernor:
    return SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
    )


def _evidence(evidence_id: str, kind: SourceKind, ref: str, content: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=kind,
        source_ref=ref,
        content=content,
        observed_at=OCCURRED_AT,
        scope=RETENTION,
    )


EV_HUMAN = _evidence(
    "EV-human", SourceKind.HUMAN, "human://alice", "Keep audit records for seven years."
)
EV_CODE = _evidence("EV-code", SourceKind.CODE, "git://repo/retention.py", "RETENTION_YEARS = 10")
EV_TEST = _evidence(
    "EV-test", SourceKind.TEST, "git://repo/test_retention.py", "assert retention_years() == 10"
)
EV_BILLING = _evidence(
    "EV-billing", SourceKind.DOCUMENT, "doc://billing", "Invoices due in 30 days."
)
EV_SHIPPING = evidence_item(
    evidence_id="EV-shipping",
    project_id=PROJECT,
    source_kind=SourceKind.TICKET,
    source_ref="ticket://SHIP-1",
    content="Orders ship within 2 days.",
    observed_at=OCCURRED_AT,
    scope=SHIPPING,
)


def _judgment(
    judgment_id: str,
    proposal: JudgmentProposal,
    *,
    reasoner: ReasonerFingerprint,
    visible: tuple[str, ...],
    invocation_id: str | None = None,
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=visible,
        rationale=f"Bounded rationale for {judgment_id}.",
        reasoner=reasoner,
        invocation_id=invocation_id or f"INV-{judgment_id}",
        proposed_at=OCCURRED_AT,
    )


def _create(
    judgment_id: str,
    candidate_id: str,
    *,
    scope: tuple[str, ...],
    evidence: tuple[str, ...],
    reasoner: ReasonerFingerprint = M1,
) -> SemanticJudgment:
    candidate = SemanticCandidate(
        candidate_id=candidate_id,
        subject="audit records",
        facet="retention period",
        scope=scope,
        evidence_ids=evidence,
    )
    return _judgment(
        judgment_id, CreateAddressProposal(candidate=candidate), reasoner=reasoner, visible=evidence
    )


def _claim(
    judgment_id: str,
    address_id: str,
    *,
    quantity: str,
    unit: str,
    evidence: tuple[str, ...],
    authority: Authority = Authority.OBSERVED,
    reasoner: ReasonerFingerprint = M1,
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit=unit),
            evidence_ids=evidence,
            authority=authority,
        ),
        reasoner=reasoner,
        visible=evidence,
    )


def _equivalent(
    judgment_id: str,
    a: str,
    b: str,
    *,
    reasoner: ReasonerFingerprint,
    invocation_id: str | None = None,
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        EquivalentProposal(address_a=a, address_b=b),
        reasoner=reasoner,
        visible=("EV-human", "EV-code"),
        invocation_id=invocation_id,
    )


def _conflict(
    judgment_id: str, a: str, b: str, *, reasoner: ReasonerFingerprint, visible: tuple[str, ...]
) -> SemanticJudgment:
    return _judgment(
        judgment_id, ConflictsWithProposal(claim_a=a, claim_b=b), reasoner=reasoner, visible=visible
    )


def _authority_record() -> AuthorityRecord:
    return AuthorityRecord(
        id="AUTH-alice",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref="human://founder"),
        created_at=OCCURRED_AT,
        scope=(),
        subject_id="audit records",
        authorized_by=ALICE,
        rationale="Alice owns compliance decisions for this project.",
    )


def _intent(scope: tuple[str, ...]) -> Intent:
    return Intent(
        id=f"INTENT-{scope[0]}",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref="human://alice"),
        created_at=OCCURRED_AT,
        scope=scope,
        mission=f"Mission for {scope[0]}.",
    )


def _requirement(scope: tuple[str, ...]) -> Requirement:
    return Requirement(
        id=f"REQ-{scope[0]}",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref="human://alice"),
        created_at=OCCURRED_AT,
        scope=scope,
        statement=f"Obligation for {scope[0]} is honoured.",
        materiality=Materiality.HIGH,
        requires_metric=True,
        metric_exempt_reason="Retention is a fixed legal period, not a measured outcome.",
        requires_verification=True,
        verification_exempt_reason="Verified by the retention test in evidence EV-test.",
    )


def _append_object(
    governor: SemanticGovernor, store: InMemoryEventStore, event_type: EventType, obj: Any
) -> StoredEvent:
    """Record an existing v0 semantic object through the same ledger the governor uses."""
    event = EventEnvelope(
        event_id=f"object-{obj.id}",
        project_id=PROJECT,
        event_type=event_type,
        occurred_at=OCCURRED_AT,
        payload=SemanticObjectPayload(object=obj),
    )
    return store.append(event, expected_sequence=store.current_sequence(PROJECT))


def _locus_of(governor: SemanticGovernor, address_id: str) -> Any:
    view = governor.view()
    representative = view.representatives[address_id]
    return next(locus for locus in view.loci if locus.representative_id == representative)


# --- the story ----------------------------------------------------------------------


def test_intent_intelligence_v2_core_lifecycle() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)

    # L — evidence from a human, from code and from a test enters through one contract.
    for evidence in (EV_HUMAN, EV_CODE, EV_TEST):
        governor.ingest(evidence)
    assert set(governor.state().semantic.evidence) == {"EV-human", "EV-code", "EV-test"}
    assert store.current_sequence(PROJECT) == 3

    # H — M1 proposes two addresses with IDENTICAL descriptors; both are minted, distinct.
    creator = ScriptedSemanticReasoner(
        M1,
        (
            _create("J-c1", "CAND-1", scope=RETENTION, evidence=("EV-human",)),
            _create("J-c2", "CAND-2", scope=RETENTION, evidence=("EV-code", "EV-test")),
        ),
    )
    request = ReasoningRequest(project_id=PROJECT, evidence=(EV_HUMAN, EV_CODE, EV_TEST))
    decisions = governor.propose_and_submit(creator, request)
    assert [d.route for d in decisions] == [AdmissionRoute.APPLY, AdmissionRoute.APPLY]
    assert all(d.reasons == ("LOW_RISK",) for d in decisions)
    assert creator.requests == [request]
    addr_1, addr_2 = address_id_for(PROJECT, "J-c1"), address_id_for(PROJECT, "J-c2")
    addresses = governor.state().semantic.addresses
    assert addr_1 != addr_2
    assert (addresses[addr_1].subject, addresses[addr_1].facet, addresses[addr_1].scope) == (
        addresses[addr_2].subject,
        addresses[addr_2].facet,
        addresses[addr_2].scope,
    )
    assert len(governor.view().loci) == 2
    assert store.current_sequence(PROJECT) == 7

    # Claims: 7 years at addr_1 (human), 10 years at addr_2 (code + test).
    assert (
        governor.submit(
            _claim("J-a1", addr_1, quantity="7", unit="year", evidence=("EV-human",))
        ).route
        is AdmissionRoute.APPLY
    )
    assert (
        governor.submit(
            _claim("J-a2", addr_2, quantity="10", unit="year", evidence=("EV-code", "EV-test"))
        ).route
        is AdmissionRoute.APPLY
    )
    claim_1, claim_2 = claim_id_for(PROJECT, "J-a1"), claim_id_for(PROJECT, "J-a2")
    assert store.current_sequence(PROJECT) == 11

    # G/I — a material EQUIVALENT from one model never applies alone ...
    first = governor.submit(_equivalent("J-eq1", addr_1, addr_2, reasoner=M1))
    assert first.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert first.reasons == ("MATERIAL_REQUIRES_SECOND_LENS",)
    # ... and the same model again, under a new invocation, is not a second lens.
    again = governor.submit(
        _equivalent("J-eq1b", addr_1, addr_2, reasoner=M1, invocation_id="INV-rerun")
    )
    assert again.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert again.corroborating_judgment_ids == ()
    assert len(governor.view().loci) == 2
    assert store.current_sequence(PROJECT) == 15

    # C/E — an INDEPENDENT second lens corroborates; the locus unifies without copying.
    second = governor.submit(_equivalent("J-eq2", addr_1, addr_2, reasoner=M2))
    assert second.route is AdmissionRoute.APPLY
    assert second.reasons == ("INDEPENDENT_CORROBORATION",)
    assert set(second.corroborating_judgment_ids) == {"J-eq1", "J-eq1b"}
    view = governor.view()
    assert len(view.loci) == 1
    assert view.loci[0].address_ids == tuple(sorted((addr_1, addr_2)))
    assert set(view.loci[0].claim_ids) == {claim_1, claim_2}
    assert view.loci[0].epistemic_state is IssueEpistemicState.CLAIMED
    assert set(governor.state().semantic.claims) == {claim_1, claim_2}
    assert store.current_sequence(PROJECT) == 17

    # F — conflict: second lens required, then corroborated; both claims preserved.
    held = governor.submit(
        _conflict("J-cf1", claim_1, claim_2, reasoner=M1, visible=("EV-human", "EV-code"))
    )
    assert held.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert _locus_of(governor, addr_1).epistemic_state is IssueEpistemicState.CLAIMED
    corroborated = governor.submit(
        _conflict("J-cf2", claim_1, claim_2, reasoner=M2, visible=("EV-human", "EV-code"))
    )
    assert corroborated.route is AdmissionRoute.APPLY
    assert corroborated.corroborating_judgment_ids == ("J-cf1",)
    disputed = _locus_of(governor, addr_1)
    assert disputed.epistemic_state is IssueEpistemicState.DISPUTED
    assert set(disputed.claim_ids) == {claim_1, claim_2}
    assert disputed.disputed_claim_pairs == ((min(claim_1, claim_2), max(claim_1, claim_2)),)
    assert store.current_sequence(PROJECT) == 21

    # Downstream work derives from the admitted equivalence, three levels deep.
    governor.derive("D1", "J-eq2")
    governor.derive("D2", "D1")
    governor.derive("D3", "D2")
    assert governor.view().stale_ids == ()
    assert store.current_sequence(PROJECT) == 24

    # Human authority enters through an authority record, not through a reasoner.
    governor.record_authority(_authority_record())
    assert "AUTH-alice" in governor.state().objects
    assert store.current_sequence(PROJECT) == 25

    # D — alice supersedes the equivalence: interpretation reverses, history stays readable.
    supersede = governor.submit(
        _judgment(
            "J-sup",
            SupersedeProposal(
                target_judgment_id="J-eq2", reason="The two records are distinct obligations."
            ),
            reasoner=HUMAN_ALICE,
            visible=("EV-human", "EV-code"),
        ),
        human_actor_id=ALICE,
    )
    assert supersede.route is AdmissionRoute.APPLY
    assert supersede.reasons == ("HUMAN_AUTHORITY",)
    state = governor.state()
    view = derive_view(state.semantic)
    assert len(view.loci) == 2
    assert "J-eq2" in state.semantic.judgments
    assert "J-eq2" in state.semantic.applied_judgment_ids
    assert view.active_equivalence_judgment_ids == ()
    supersessions = state.semantic.supersessions
    assert [(r.target_judgment_id, r.superseding_judgment_id) for r in supersessions] == [
        ("J-eq2", "J-sup")
    ]
    assert _locus_of(governor, addr_1).claim_ids == (claim_1,)
    assert _locus_of(governor, addr_2).claim_ids == (claim_2,)
    # M — blast radius reaches every derivation level.
    assert {"D1", "D2", "D3"} <= set(view.stale_ids)
    assert store.current_sequence(PROJECT) == 27

    # Alice settles addr_2 canonically; addr_1 remains merely CLAIMED.
    canonical = governor.submit(
        _claim(
            "J-a3",
            addr_2,
            quantity="10",
            unit="year",
            evidence=("EV-code", "EV-test"),
            authority=Authority.CANONICAL,
            reasoner=HUMAN_ALICE,
        ),
        human_actor_id=ALICE,
    )
    assert canonical.route is AdmissionRoute.APPLY
    assert canonical.reasons == ("HUMAN_AUTHORITY",)
    assert _locus_of(governor, addr_2).epistemic_state is IssueEpistemicState.SETTLED
    assert _locus_of(governor, addr_1).epistemic_state is IssueEpistemicState.CLAIMED
    claim_3 = claim_id_for(PROJECT, "J-a3")
    assert set(_locus_of(governor, addr_2).claim_ids) == {claim_2, claim_3}
    assert store.current_sequence(PROJECT) == 29

    # Closure inputs for scope "retention": canonical Intent + canonical Requirement.
    _append_object(governor, store, EventType.SEMANTIC_OBJECT_RECORDED, _intent(RETENTION))
    _append_object(governor, store, EventType.REQUIREMENT_CANONICALIZED, _requirement(RETENTION))
    assert store.current_sequence(PROJECT) == 31

    # T5 — retention closes, but downstream work D1..D3 depends on the superseded basis:
    # the scope is NOT ready until that work is reconciled (spec §19.1).
    after_supersession = build_intent_decision_handoff(governor.state(), "retention")
    assert after_supersession.readiness.closure.closed is True
    assert after_supersession.readiness.disputed_locus_ids == ()
    assert {"D1", "D2", "D3"} <= set(after_supersession.stale_object_ids)
    assert after_supersession.readiness.ready is False

    # A second scope, "billing", left DISPUTED.
    governor.ingest(EV_BILLING)
    assert (
        governor.submit(_create("J-cB", "CAND-B", scope=BILLING, evidence=("EV-billing",))).route
        is AdmissionRoute.APPLY
    )
    addr_b = address_id_for(PROJECT, "J-cB")
    assert (
        governor.submit(
            _claim("J-b1", addr_b, quantity="30", unit="day", evidence=("EV-billing",))
        ).route
        is AdmissionRoute.APPLY
    )
    assert (
        governor.submit(
            _claim("J-b2", addr_b, quantity="45", unit="day", evidence=("EV-billing",))
        ).route
        is AdmissionRoute.APPLY
    )
    claim_b1, claim_b2 = claim_id_for(PROJECT, "J-b1"), claim_id_for(PROJECT, "J-b2")
    assert (
        governor.submit(
            _conflict("J-cfB1", claim_b1, claim_b2, reasoner=M1, visible=("EV-billing",))
        ).route
        is AdmissionRoute.REQUIRE_SECOND_LENS
    )
    assert (
        governor.submit(
            _conflict("J-cfB2", claim_b1, claim_b2, reasoner=M2, visible=("EV-billing",))
        ).route
        is AdmissionRoute.APPLY
    )
    assert _locus_of(governor, addr_b).epistemic_state is IssueEpistemicState.DISPUTED
    assert store.current_sequence(PROJECT) == 42

    # A third, clean scope "shipping": one claim, closed, nothing stale.
    governor.ingest(EV_SHIPPING)
    assert (
        governor.submit(_create("J-cS", "CAND-S", scope=SHIPPING, evidence=("EV-shipping",))).route
        is AdmissionRoute.APPLY
    )
    addr_s = address_id_for(PROJECT, "J-cS")
    assert (
        governor.submit(
            _claim("J-s1", addr_s, quantity="2", unit="day", evidence=("EV-shipping",))
        ).route
        is AdmissionRoute.APPLY
    )
    claim_s1 = claim_id_for(PROJECT, "J-s1")
    _append_object(governor, store, EventType.SEMANTIC_OBJECT_RECORDED, _intent(SHIPPING))
    _append_object(governor, store, EventType.REQUIREMENT_CANONICALIZED, _requirement(SHIPPING))
    assert _locus_of(governor, addr_s).epistemic_state is IssueEpistemicState.CLAIMED
    assert store.current_sequence(PROJECT) == EXPECTED_LEDGER_LENGTH

    # N/O — scoped handoff: shipping is ready; retention (stale downstream) and billing
    # (disputed) are not; every handoff carries ids only, never bodies.
    state = governor.state()
    retention = build_intent_decision_handoff(state, "retention")
    billing = build_intent_decision_handoff(state, "billing")
    shipping = build_intent_decision_handoff(state, "shipping")

    assert retention.handoff_version == HANDOFF_VERSION
    assert retention.project_id == PROJECT
    assert retention.semantic_state_revision == state.revision == EXPECTED_LEDGER_LENGTH
    assert retention.readiness.ready is False
    assert retention.readiness.closure.closed is True
    assert retention.readiness.disputed_locus_ids == ()
    assert retention.stale_object_ids == retention.readiness.stale_object_ids == ("D1", "D2", "D3")
    assert [locus.representative_id for locus in retention.loci] == sorted((addr_1, addr_2))
    assert retention.claim_ids == tuple(sorted((claim_1, claim_2, claim_3)))
    assert retention.evidence_ids == ("EV-code", "EV-human", "EV-test")
    assert retention.authority_record_ids == ("AUTH-alice",)
    assert retention.superseded_judgment_ids == ("J-eq2",)
    for token in ("EV-billing", addr_b, "EV-shipping", addr_s, claim_s1, "INTENT-", "REQ-"):
        assert token not in retention.model_dump_json()
    assert "Bounded rationale" not in retention.model_dump_json()
    assert "Keep audit records" not in retention.model_dump_json()

    assert billing.readiness.ready is False
    assert billing.readiness.disputed_locus_ids == (addr_b,)
    assert billing.readiness.closure.closed is False
    assert [locus.representative_id for locus in billing.loci] == [addr_b]
    assert billing.claim_ids == tuple(sorted((claim_b1, claim_b2)))
    assert billing.evidence_ids == ("EV-billing",)
    assert billing.authority_record_ids == ("AUTH-alice",)
    assert billing.superseded_judgment_ids == ()
    assert billing.stale_object_ids == ()

    assert shipping.readiness.ready is True
    assert shipping.readiness.closure.closed is True
    assert shipping.readiness.disputed_locus_ids == ()
    assert shipping.readiness.open_locus_ids == ()
    assert shipping.stale_object_ids == ()
    assert [locus.representative_id for locus in shipping.loci] == [addr_s]
    assert shipping.claim_ids == (claim_s1,)
    assert shipping.evidence_ids == ("EV-shipping",)
    assert shipping.authority_record_ids == ("AUTH-alice",)
    assert shipping.superseded_judgment_ids == ()
    foreign = (
        addr_1,
        addr_2,
        addr_b,
        claim_1,
        claim_2,
        claim_3,
        claim_b1,
        claim_b2,
        "EV-human",
        "EV-code",
        "EV-test",
        "EV-billing",
        "J-eq2",
        "D1",
        "D2",
        "D3",
    )
    for token in foreign:
        assert token not in shipping.model_dump_json()

    # P — replay: a fresh store fed the same events, in order, reproduces everything.
    events = store.load(PROJECT)
    assert len(events) == EXPECTED_LEDGER_LENGTH
    assert [e.sequence for e in events] == list(range(1, EXPECTED_LEDGER_LENGTH + 1))
    fresh_store = InMemoryEventStore()
    for stored in events:
        round_tripped = parse_event(stored.event.model_dump(mode="json"))
        assert round_tripped == stored.event
        fresh_store.append(round_tripped, expected_sequence=stored.sequence - 1)
    replayed = _governor(fresh_store)
    assert replayed.state() == state
    assert replayed.state().semantic == state.semantic
    assert replayed.view() == derive_view(state.semantic)
    assert build_intent_decision_handoff(replayed.state(), "retention") == retention
    assert build_intent_decision_handoff(replayed.state(), "billing") == billing
    assert build_intent_decision_handoff(replayed.state(), "shipping") == shipping
    assert state.semantic.model_dump(mode="json") == replayed.state().semantic.model_dump(
        mode="json"
    )

    # The ledger is exactly the story told above.
    assert [e.event.event_type for e in events].count(EventType.EVIDENCE_INGESTED) == 5
    assert [e.event.event_type for e in events].count(EventType.SEMANTIC_JUDGMENT_RECORDED) == 18
    assert [e.event.event_type for e in events].count(EventType.SEMANTIC_ADMISSION_DECIDED) == 18
    assert [e.event.event_type for e in events].count(EventType.DERIVATION_RECORDED) == 3
    assert [e.event.event_type for e in events].count(EventType.SEMANTIC_OBJECT_RECORDED) == 3
    assert [e.event.event_type for e in events].count(EventType.REQUIREMENT_CANONICALIZED) == 2

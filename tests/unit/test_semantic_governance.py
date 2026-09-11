"""SemanticGovernor tests (plan §8.1).

The governor is the ONLY place a judgment becomes an event. Every test drives the
real ``InMemoryEventStore`` -> ``replay`` path; nothing is mocked except the reasoner,
which is the deterministic ``ScriptedSemanticReasoner``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.fake_reasoner import ScriptedSemanticReasoner
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.events import EventType, SemanticAdmissionPayload, SemanticJudgmentPayload
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    EquivalentProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

PROJECT = "PROJ-GOV"
OTHER_PROJECT = "PROJ-OTHER"
OCCURRED_AT = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")
MODEL_B = ReasonerFingerprint(provider="anthropic", model="claude-opus-5", policy_version="p1")
HUMAN_ALICE = ReasonerFingerprint(provider="human", model="human://alice", policy_version="p1")


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield OCCURRED_AT.replace(minute=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _governor(
    store: InMemoryEventStore | None = None, project_id: str = PROJECT
) -> SemanticGovernor:
    clock = _clock()
    return SemanticGovernor(
        store=store or InMemoryEventStore(),
        project_id=project_id,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )


def _evidence(evidence_id: str = "EV-1", project_id: str = PROJECT) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=project_id,
        source_kind=SourceKind.HUMAN,
        source_ref="human://alice",
        content="Audit records are retained for seven years.",
        observed_at=OCCURRED_AT,
    )


def _candidate(candidate_id: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject="audit records",
        facet="retention period",
        scope=("compliance",),
        evidence_ids=("EV-1",),
    )


def _judgment(
    judgment_id: str,
    proposal: JudgmentProposal,
    *,
    reasoner: ReasonerFingerprint = MODEL_A,
    project_id: str = PROJECT,
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=project_id,
        proposal=proposal,
        visible_evidence_ids=("EV-1",),
        rationale="EV-1 states a retention obligation for audit records.",
        reasoner=reasoner,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=OCCURRED_AT,
    )


def _create(
    judgment_id: str,
    candidate_id: str,
    *,
    reasoner: ReasonerFingerprint = MODEL_A,
    project_id: str = PROJECT,
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(candidate=_candidate(candidate_id)),
        reasoner=reasoner,
        project_id=project_id,
    )


def _assert_claim(
    judgment_id: str,
    address_id: str,
    *,
    authority: Authority = Authority.OBSERVED,
    reasoner: ReasonerFingerprint = MODEL_A,
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
            evidence_ids=("EV-1",),
            authority=authority,
        ),
        reasoner=reasoner,
    )


def _equivalent(judgment_id: str, a: str, b: str) -> SemanticJudgment:
    return _judgment(judgment_id, EquivalentProposal(address_a=a, address_b=b))


def _bind(
    judgment_id: str,
    candidate_id: str,
    address_id: str,
    *,
    reasoner: ReasonerFingerprint = MODEL_A,
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        BindToAddressProposal(candidate=_candidate(candidate_id), address_id=address_id),
        reasoner=reasoner,
    )


def _conflict(
    judgment_id: str, a: str, b: str, *, reasoner: ReasonerFingerprint = MODEL_A
) -> SemanticJudgment:
    return _judgment(judgment_id, ConflictsWithProposal(claim_a=a, claim_b=b), reasoner=reasoner)


def _authority_record(actor: str = "human://alice") -> AuthorityRecord:
    return AuthorityRecord(
        id="AUTH-1",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref="human://founder"),
        created_at=OCCURRED_AT,
        subject_id="compliance",
        authorized_by=actor,
        rationale="Owns compliance decisions.",
    )


# --- ingest --------------------------------------------------------------------


def test_ingest_appends_evidence_event_and_state_sees_it() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)

    stored = governor.ingest(_evidence())

    assert stored.sequence == 1
    assert stored.event.event_type is EventType.EVIDENCE_INGESTED
    assert stored.event.project_id == PROJECT
    assert "EV-1" in governor.state().semantic.evidence
    assert store.current_sequence(PROJECT) == 1


def test_ingest_rejects_evidence_from_another_project() -> None:
    governor = _governor()

    with pytest.raises(ValueError, match="project"):
        governor.ingest(_evidence(project_id=OTHER_PROJECT))


def test_ingest_refuses_duplicate_evidence_before_touching_the_ledger() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())

    with pytest.raises(ValueError, match="EV-1"):
        governor.ingest(_evidence())

    assert store.current_sequence(PROJECT) == 1
    assert "EV-1" in governor.state().semantic.evidence


# --- submit: two events, in order ------------------------------------------------


def test_submit_records_judgment_then_admission_in_order() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())

    decision = governor.submit(_create("J-c1", "CAND-1"))

    events = store.load(PROJECT)
    assert [e.event.event_type for e in events] == [
        EventType.EVIDENCE_INGESTED,
        EventType.SEMANTIC_JUDGMENT_RECORDED,
        EventType.SEMANTIC_ADMISSION_DECIDED,
    ]
    recorded = events[1].event.payload
    admitted = events[2].event.payload
    assert isinstance(recorded, SemanticJudgmentPayload)
    assert isinstance(admitted, SemanticAdmissionPayload)
    assert recorded.judgment.judgment_id == "J-c1"
    assert admitted.judgment_id == "J-c1"
    assert admitted.route is decision.route is AdmissionRoute.APPLY
    assert admitted.reasons == decision.reasons == ("LOW_RISK",)
    assert admitted.corroborating_judgment_ids == decision.corroborating_judgment_ids == ()
    assert events[2].event.causation_id == events[1].event.event_id


def test_submit_apply_changes_view_and_second_lens_does_not() -> None:
    governor = _governor()
    governor.ingest(_evidence())
    governor.submit(_create("J-c1", "CAND-1"))
    governor.submit(_create("J-c2", "CAND-2"))
    addr_1, addr_2 = address_id_for(PROJECT, "J-c1"), address_id_for(PROJECT, "J-c2")
    assert len(governor.view().loci) == 2

    applied = governor.submit(_assert_claim("J-a1", addr_1))
    assert applied.route is AdmissionRoute.APPLY
    assert claim_id_for(PROJECT, "J-a1") in governor.state().semantic.claims

    before = governor.view()
    held = governor.submit(_equivalent("J-eq1", addr_1, addr_2))

    assert held.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert governor.view() == before
    assert "J-eq1" in governor.state().semantic.judgments
    assert governor.state().semantic.admissions["J-eq1"].route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert "J-eq1" not in governor.state().semantic.applied_judgment_ids


def test_submit_rejects_judgment_from_another_project_without_appending() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())

    with pytest.raises(ValueError, match="project"):
        governor.submit(_create("J-c1", "CAND-1", project_id=OTHER_PROJECT))

    assert store.current_sequence(PROJECT) == 1
    assert store.current_sequence(OTHER_PROJECT) == 0


def test_submit_refuses_a_judgment_id_that_is_already_recorded() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())
    governor.submit(_create("J-c1", "CAND-1"))

    with pytest.raises(ValueError, match="J-c1"):
        governor.submit(_create("J-c1", "CAND-2"))

    assert store.current_sequence(PROJECT) == 3


# --- submit: human trust boundary ------------------------------------------------


def test_human_fingerprint_without_actor_is_refused_and_nothing_is_appended() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())

    with pytest.raises(ValueError, match="human fingerprint requires an authenticated actor"):
        governor.submit(_create("J-h1", "CAND-1", reasoner=HUMAN_ALICE))

    assert store.current_sequence(PROJECT) == 1


def test_human_fingerprint_with_mismatched_actor_is_refused() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())

    with pytest.raises(ValueError, match="human fingerprint requires an authenticated actor"):
        governor.submit(
            _create("J-h1", "CAND-1", reasoner=HUMAN_ALICE), human_actor_id="human://bob"
        )

    assert store.current_sequence(PROJECT) == 1


def test_non_human_fingerprint_with_actor_is_refused() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())

    with pytest.raises(ValueError, match="actor"):
        governor.submit(_create("J-c1", "CAND-1"), human_actor_id="human://alice")

    assert store.current_sequence(PROJECT) == 1


def test_authenticated_human_with_authority_record_is_applied_by_authority() -> None:
    governor = _governor()
    governor.ingest(_evidence())
    governor.submit(_create("J-c1", "CAND-1"))
    addr_1 = address_id_for(PROJECT, "J-c1")
    recorded = governor.record_authority(_authority_record())

    assert recorded.event.event_type is EventType.SEMANTIC_OBJECT_RECORDED
    assert "AUTH-1" in governor.state().objects

    decision = governor.submit(
        _assert_claim("J-h1", addr_1, authority=Authority.CANONICAL, reasoner=HUMAN_ALICE),
        human_actor_id="human://alice",
    )

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("HUMAN_AUTHORITY",)
    assert governor.state().semantic.claims[claim_id_for(PROJECT, "J-h1")].authority is (
        Authority.CANONICAL
    )


def test_record_authority_rejects_record_from_another_project() -> None:
    governor = _governor()

    with pytest.raises(ValueError, match="project"):
        governor.record_authority(_authority_record().model_copy(update={"project_id": "PROJ-X"}))


# --- derive --------------------------------------------------------------------


def test_derive_appends_derivation_edge() -> None:
    governor = _governor()

    stored = governor.derive("D-1", "J-eq")

    assert stored.event.event_type is EventType.DERIVATION_RECORDED
    edges = governor.state().semantic.derivations
    assert [(e.child_id, e.parent_id) for e in edges] == [("D-1", "J-eq")]
    assert edges[0].recorded_by_event_id == stored.event.event_id


# --- propose_and_submit ------------------------------------------------------------


def test_propose_and_submit_passes_bounded_request_and_submits_in_order() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())
    reasoner = ScriptedSemanticReasoner(
        MODEL_A, (_create("J-c1", "CAND-1"), _create("J-c2", "CAND-2"))
    )
    request = ReasoningRequest(project_id=PROJECT, evidence=(_evidence(),))

    decisions = governor.propose_and_submit(reasoner, request)

    assert [d.judgment_id for d in decisions] == ["J-c1", "J-c2"]
    assert all(d.route is AdmissionRoute.APPLY for d in decisions)
    assert reasoner.requests == [request]
    seen = reasoner.requests[0]
    assert isinstance(seen, ReasoningRequest)
    assert set(ReasoningRequest.model_fields) == {
        "project_id",
        "evidence",
        "focus_object_ids",
        "known_addresses",
        "known_claims",
    }
    assert not hasattr(seen, "store")
    recorded = [
        e.event.payload.judgment.judgment_id
        for e in store.load(PROJECT)
        if isinstance(e.event.payload, SemanticJudgmentPayload)
    ]
    assert recorded == ["J-c1", "J-c2"]
    assert [e.event.event_type for e in store.load(PROJECT)][1:] == [
        EventType.SEMANTIC_JUDGMENT_RECORDED,
        EventType.SEMANTIC_ADMISSION_DECIDED,
        EventType.SEMANTIC_JUDGMENT_RECORDED,
        EventType.SEMANTIC_ADMISSION_DECIDED,
    ]


def test_propose_and_submit_refuses_a_human_reasoner() -> None:
    governor = _governor()
    governor.ingest(_evidence())
    reasoner = ScriptedSemanticReasoner(
        HUMAN_ALICE, (_create("J-h1", "CAND-1", reasoner=HUMAN_ALICE),)
    )

    with pytest.raises(ValueError, match="human"):
        governor.propose_and_submit(
            reasoner, ReasoningRequest(project_id=PROJECT, evidence=(_evidence(),))
        )


def test_propose_and_submit_refuses_judgments_under_another_fingerprint() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())
    spoofed = ReasonerFingerprint(provider="anthropic", model="claude-opus-5", policy_version="p1")
    reasoner = ScriptedSemanticReasoner(
        MODEL_A, (_create("J-c1", "CAND-1"), _create("J-c2", "CAND-2", reasoner=spoofed))
    )

    with pytest.raises(ValueError, match="fingerprint"):
        governor.propose_and_submit(
            reasoner, ReasoningRequest(project_id=PROJECT, evidence=(_evidence(),))
        )

    assert store.current_sequence(PROJECT) == 1


# --- deterministic ids -----------------------------------------------------------


def test_event_ids_and_timestamps_come_from_injected_factory_and_clock() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())
    governor.submit(_create("J-c1", "CAND-1"))
    governor.derive("D-1", "J-c1")

    events = [e.event for e in store.load(PROJECT)]
    assert [e.event_id for e in events] == [
        "evidence-1",
        "judgment-2",
        "admission-3",
        "derivation-4",
    ]
    assert [e.occurred_at.minute for e in events] == [0, 1, 2, 3]

    replayed = _governor(store)
    assert replayed.state() == governor.state()


def test_default_id_factory_mints_unique_prefixed_ids() -> None:
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store, project_id=PROJECT, policy=AdmissionPolicy(), clock=lambda: OCCURRED_AT
    )
    governor.ingest(_evidence("EV-1"))
    governor.ingest(_evidence("EV-2"))

    ids = [e.event.event_id for e in store.load(PROJECT)]
    assert len(set(ids)) == 2
    assert all(event_id.startswith("evidence-") for event_id in ids)


# --- rebinding requires supersession: full path (spec §4.5, §20.1, §21 #10) ----------


def test_submit_rejects_rebind_of_actively_bound_candidate_and_leaves_state_unchanged() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())
    governor.submit(_create("J-c1", "CAND-1"))
    governor.submit(_create("J-c2", "CAND-2"))
    addr_1, addr_2 = address_id_for(PROJECT, "J-c1"), address_id_for(PROJECT, "J-c2")
    before = governor.state()
    view_before = governor.view()
    assert view_before.active_bindings["CAND-1"] == addr_1

    decision = governor.submit(_bind("J-b1", "CAND-1", addr_2, reasoner=MODEL_B))

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (
        "STRUCTURAL: candidate CAND-1 already bound by J-c1; supersede it first",
    )
    after = governor.state()
    assert after.semantic.bindings == before.semantic.bindings
    assert after.semantic.bindings["CAND-1"] == addr_1
    assert governor.view().active_bindings == view_before.active_bindings
    assert after.semantic.applied_judgment_ids == before.semantic.applied_judgment_ids
    assert after.semantic.issue_heads == before.semantic.issue_heads
    assert "J-b1" in after.semantic.judgments
    assert after.semantic.admissions["J-b1"].route is AdmissionRoute.REJECT
    assert store.current_sequence(PROJECT) == 7


def test_submit_applies_rebind_once_original_binding_is_superseded_by_authority() -> None:
    governor = _governor()
    governor.ingest(_evidence())
    governor.submit(_create("J-c1", "CAND-1"))
    governor.submit(_create("J-c2", "CAND-2"))
    addr_1, addr_2 = address_id_for(PROJECT, "J-c1"), address_id_for(PROJECT, "J-c2")
    governor.record_authority(_authority_record())
    superseded = governor.submit(
        _judgment(
            "J-sup",
            SupersedeProposal(target_judgment_id="J-c1", reason="CAND-1 was misidentified."),
            reasoner=HUMAN_ALICE,
        ),
        human_actor_id="human://alice",
    )
    assert superseded.route is AdmissionRoute.APPLY

    decision = governor.submit(_bind("J-b1", "CAND-1", addr_2))

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)
    state = governor.state()
    view = governor.view()
    assert state.semantic.bindings["CAND-1"] == addr_2
    assert view.active_bindings["CAND-1"] == addr_2
    assert "J-c1" in state.semantic.judgments
    assert "J-c1" in state.semantic.applied_judgment_ids
    assert addr_1 in state.semantic.addresses


# --- CONFLICTS_WITH never leaves an orphan judgment (spec §22.6, §22.7, §22.11) --------


def test_submit_rejects_cross_locus_conflict_instead_of_orphaning_it() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence())
    governor.submit(_create("J-c1", "CAND-1"))
    governor.submit(_create("J-c2", "CAND-2"))
    addr_1, addr_2 = address_id_for(PROJECT, "J-c1"), address_id_for(PROJECT, "J-c2")
    governor.submit(_assert_claim("J-a1", addr_1))
    governor.submit(_assert_claim("J-a2", addr_2))
    claim_1, claim_2 = claim_id_for(PROJECT, "J-a1"), claim_id_for(PROJECT, "J-a2")
    held = governor.submit(_conflict("J-cf1", claim_1, claim_2, reasoner=MODEL_B))
    assert held.route is AdmissionRoute.REJECT
    before = governor.state()

    decision = governor.submit(_conflict("J-cf2", claim_1, claim_2, reasoner=MODEL_A))

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (
        f"STRUCTURAL: claims {claim_1}, {claim_2} are not live claims at one locus",
    )
    after = governor.state()
    assert after.semantic.conflicts == before.semantic.conflicts == ()
    assert after.semantic.applied_judgment_ids == before.semantic.applied_judgment_ids
    assert after.semantic.admissions["J-cf2"].route is AdmissionRoute.REJECT
    assert store.current_sequence(PROJECT) == 13
    assert len(governor.view().loci) == 2

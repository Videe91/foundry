"""Reducer tests for governed semantic state transitions (plan §5.4, §5.8).

Events are hand-built ``StoredEvent`` sequences; no governor exists yet.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from foundry.application.reducer import reduce_event
from foundry.application.replay import replay
from foundry.application.semantic_reducer import reduce_semantic_event
from foundry.domain.common import Authority, SourceKind
from foundry.domain.events import (
    DerivationPayload,
    EventEnvelope,
    EventPayload,
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
    UserStatedIntentPayload,
    parse_event,
)
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    IssueEpistemicState,
    SemanticCandidate,
)
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    DistinctProposal,
    EquivalentProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_state import SemanticState, SupersessionRecord
from foundry.domain.semantic_view import active_judgment_ids, derive_view
from foundry.domain.state import IntentState

PROJECT = "PROJ-1"
OCCURRED_AT = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")
HUMAN_ALICE = ReasonerFingerprint(provider="human", model="human://alice", policy_version="p1")


def _digest(judgment_id: str) -> str:
    return hashlib.sha256(f"{PROJECT}|{judgment_id}".encode()).hexdigest()[:16]


def address_id_for(judgment_id: str) -> str:
    return "ADDR-" + _digest(judgment_id)


def claim_id_for(judgment_id: str) -> str:
    return "CLAIM-" + _digest(judgment_id)


def _evidence(evidence_id: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.HUMAN,
        source_ref="human://alice",
        content=f"Statement {evidence_id}: audit records are retained.",
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
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=("EV-1",),
        rationale="EV-1 states a retention obligation for audit records.",
        reasoner=reasoner,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=OCCURRED_AT,
    )


def _create(judgment_id: str, candidate_id: str) -> SemanticJudgment:
    return _judgment(judgment_id, CreateAddressProposal(candidate=_candidate(candidate_id)))


def _bind(judgment_id: str, candidate_id: str, address_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        BindToAddressProposal(candidate=_candidate(candidate_id), address_id=address_id),
    )


def _assert_claim(
    judgment_id: str,
    address_id: str,
    *,
    quantity: str = "7",
    evidence_ids: tuple[str, ...] = ("EV-1",),
    authority: Authority = Authority.OBSERVED,
    reasoner: ReasonerFingerprint = MODEL_A,
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="year"),
            evidence_ids=evidence_ids,
            authority=authority,
        ),
        reasoner=reasoner,
    )


def _equivalent(judgment_id: str, a: str, b: str) -> SemanticJudgment:
    return _judgment(judgment_id, EquivalentProposal(address_a=a, address_b=b))


def _distinct(judgment_id: str, a: str, b: str) -> SemanticJudgment:
    return _judgment(judgment_id, DistinctProposal(address_a=a, address_b=b))


def _conflict(judgment_id: str, a: str, b: str) -> SemanticJudgment:
    return _judgment(judgment_id, ConflictsWithProposal(claim_a=a, claim_b=b))


def _supersede(judgment_id: str, target: str) -> SemanticJudgment:
    return _judgment(
        judgment_id, SupersedeProposal(target_judgment_id=target, reason="later evidence")
    )


class Ledger:
    """Hand-built event sequence with deterministic ids and sequences."""

    def __init__(self) -> None:
        self.events: list[StoredEvent] = []

    def _append(self, event_type: EventType, payload: EventPayload) -> StoredEvent:
        sequence = len(self.events) + 1
        stored = StoredEvent(
            sequence=sequence,
            event=EventEnvelope(
                event_id=f"EVT-{sequence}",
                project_id=PROJECT,
                event_type=event_type,
                occurred_at=OCCURRED_AT,
                payload=payload,
            ),
        )
        self.events.append(stored)
        return stored

    def ingest(self, evidence_id: str) -> StoredEvent:
        return self._append(
            EventType.EVIDENCE_INGESTED, EvidencePayload(evidence=_evidence(evidence_id))
        )

    def record(self, judgment: SemanticJudgment) -> StoredEvent:
        return self._append(
            EventType.SEMANTIC_JUDGMENT_RECORDED, SemanticJudgmentPayload(judgment=judgment)
        )

    def admit(self, judgment_id: str, route: AdmissionRoute = AdmissionRoute.APPLY) -> StoredEvent:
        return self._append(
            EventType.SEMANTIC_ADMISSION_DECIDED,
            SemanticAdmissionPayload(judgment_id=judgment_id, route=route, reasons=("TEST",)),
        )

    def apply(self, judgment: SemanticJudgment) -> StoredEvent:
        self.record(judgment)
        return self.admit(judgment.judgment_id)

    def derive(self, child_id: str, parent_id: str) -> StoredEvent:
        return self._append(
            EventType.DERIVATION_RECORDED, DerivationPayload(child_id=child_id, parent_id=parent_id)
        )

    def replay(self) -> IntentState:
        return replay(PROJECT, self.events)


def _ledger_with_evidence() -> Ledger:
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.ingest("EV-2")
    return ledger


def _two_addresses(ledger: Ledger) -> tuple[str, str]:
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.apply(_create("J-c2", "CAND-2"))
    return address_id_for("J-c1"), address_id_for("J-c2")


# --- evidence and judgment recording ----------------------------------------


def test_evidence_ingested_is_added_to_semantic_state() -> None:
    ledger = Ledger()
    ledger.ingest("EV-1")

    state = ledger.replay()

    assert state.semantic.evidence["EV-1"].content_sha256 == _evidence("EV-1").content_sha256
    assert state.revision == 1
    assert state.last_sequence == 1
    assert state.source_events == ("EVT-1",)


def test_judgment_recorded_is_stored_without_any_transition() -> None:
    ledger = _ledger_with_evidence()
    ledger.record(_create("J-c1", "CAND-1"))

    state = ledger.replay()

    assert "J-c1" in state.semantic.judgments
    assert state.semantic.addresses == {}
    assert state.semantic.applied_judgment_ids == ()
    assert state.semantic.admissions == {}


def test_duplicate_evidence_id_raises() -> None:
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.ingest("EV-1")

    with pytest.raises(ValueError, match="EV-1"):
        ledger.replay()


def test_duplicate_judgment_id_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.record(_create("J-c1", "CAND-1"))
    ledger.record(_create("J-c1", "CAND-2"))

    with pytest.raises(ValueError, match="J-c1"):
        ledger.replay()


def test_admission_of_unknown_judgment_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.admit("J-missing")

    with pytest.raises(ValueError, match="J-missing"):
        ledger.replay()


# --- B: binding creates referential identity ---------------------------------


def test_create_address_mints_deterministic_address_binding_and_open_issue() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))

    state = ledger.replay()
    semantic = state.semantic
    address_id = address_id_for("J-c1")

    assert set(semantic.addresses) == {address_id}
    address = semantic.addresses[address_id]
    assert address.created_by_judgment_id == "J-c1"
    assert address.subject == "audit records"
    assert address.scope == ("compliance",)
    assert semantic.bindings["CAND-1"] == address_id
    assert semantic.applied_judgment_ids == ("J-c1",)
    assert semantic.admissions["J-c1"].route is AdmissionRoute.APPLY
    version_id = semantic.issue_heads[address_id]
    assert version_id == f"EVT-4:{address_id}"
    version = semantic.issue_versions[version_id]
    assert version.epistemic_state is IssueEpistemicState.OPEN
    assert version.claim_ids == ()
    assert version.equivalent_address_ids == ()
    assert version.supersedes_version_id is None
    assert version.created_by_event_id == "EVT-4"
    assert version.created_by_judgment_id == "J-c1"


def test_bind_to_address_records_referential_identity() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    address_id = address_id_for("J-c1")
    ledger.apply(_bind("J-b1", "CAND-2", address_id))

    semantic = ledger.replay().semantic

    assert semantic.bindings["CAND-2"] == address_id
    assert semantic.bindings["CAND-1"] == address_id
    assert set(semantic.addresses) == {address_id}


def test_bind_to_missing_address_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_bind("J-b1", "CAND-2", "ADDR-nope"))

    with pytest.raises(ValueError, match="ADDR-nope"):
        ledger.replay()


# --- A: identical descriptors are not identity -------------------------------


def test_identical_descriptors_create_two_addresses_and_two_loci() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)

    state = ledger.replay()
    view = derive_view(state.semantic)

    assert addr_1 != addr_2
    assert len(state.semantic.addresses) == 2
    descriptors = {(a.subject, a.facet, a.scope) for a in state.semantic.addresses.values()}
    assert len(descriptors) == 1
    assert len(view.loci) == 2


# --- ASSERT_CLAIM -------------------------------------------------------------


def test_assert_claim_mints_claim_with_provenance_and_new_issue_version() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    address_id = address_id_for("J-c1")
    ledger.apply(_assert_claim("J-a1", address_id, evidence_ids=("EV-1", "EV-2")))

    semantic = ledger.replay().semantic
    claim_id = claim_id_for("J-a1")

    claim = semantic.claims[claim_id]
    assert claim.address_id == address_id
    assert claim.value.quantity == Decimal("7")
    assert claim.authority is Authority.OBSERVED
    assert claim.created_by_judgment_id == "J-a1"
    assert claim.provenance.source_kind is SourceKind.SYSTEM
    assert claim.provenance.source_ref == "xai:grok-4"
    # Identity-type law: evidence_ids are EvidenceItem IDs; source_event_ids are
    # EventEnvelope IDs ONLY. The reducer has no ingestion-event index at claim
    # construction time, so it must leave source_event_ids empty rather than copy
    # EvidenceItem IDs into an event-ID field.
    assert claim.evidence_ids == ("EV-1", "EV-2")
    assert claim.provenance.source_event_ids == ()
    head = semantic.issue_versions[semantic.issue_heads[address_id]]
    assert head.version_id == f"EVT-6:{address_id}"
    assert head.claim_ids == (claim_id,)
    assert head.epistemic_state is IssueEpistemicState.CLAIMED
    assert head.supersedes_version_id == f"EVT-4:{address_id}"
    assert f"EVT-4:{address_id}" in semantic.issue_versions


def test_human_asserted_claim_carries_human_provenance() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.apply(_assert_claim("J-a1", address_id_for("J-c1"), reasoner=HUMAN_ALICE))

    claim = ledger.replay().semantic.claims[claim_id_for("J-a1")]

    assert claim.provenance.source_kind is SourceKind.HUMAN
    assert claim.provenance.source_ref == "human:human://alice"


def test_assert_claim_with_unknown_evidence_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.apply(_assert_claim("J-a1", address_id_for("J-c1"), evidence_ids=("EV-1", "EV-9")))

    with pytest.raises(ValueError, match="EV-9"):
        ledger.replay()


def test_assert_claim_at_unknown_address_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_assert_claim("J-a1", "ADDR-nope"))

    with pytest.raises(ValueError, match="ADDR-nope"):
        ledger.replay()


# --- C: EQUIVALENT merges the view, never the records -----------------------


def test_equivalent_keeps_both_addresses_and_merges_only_the_view() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    event = ledger.apply(_equivalent("J-eq", addr_1, addr_2))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert set(semantic.addresses) == {addr_1, addr_2}
    assert set(semantic.issue_heads) == {addr_1, addr_2}
    assert len(semantic.equivalences) == 1
    assert semantic.equivalences[0].judgment_id == "J-eq"
    assert len(view.loci) == 1
    assert view.loci[0].address_ids == tuple(sorted((addr_1, addr_2)))
    assert view.loci[0].representative_id == min(addr_1, addr_2)
    head_1 = semantic.issue_versions[semantic.issue_heads[addr_1]]
    head_2 = semantic.issue_versions[semantic.issue_heads[addr_2]]
    assert head_1.created_by_event_id == event.event.event_id
    assert head_1.equivalent_address_ids == (addr_2,)
    assert head_2.equivalent_address_ids == (addr_1,)


def test_equivalent_with_unknown_address_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.apply(_equivalent("J-eq", address_id_for("J-c1"), "ADDR-nope"))

    with pytest.raises(ValueError, match="ADDR-nope"):
        ledger.replay()


# --- E: claims union in the view, never copied --------------------------------


def test_equivalent_unions_claims_in_view_without_moving_them() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_assert_claim("J-a1", addr_1, quantity="7"))
    ledger.apply(_assert_claim("J-a2", addr_2, quantity="10"))
    ledger.apply(_equivalent("J-eq", addr_1, addr_2))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)
    claim_1, claim_2 = claim_id_for("J-a1"), claim_id_for("J-a2")

    assert set(view.loci[0].claim_ids) == {claim_1, claim_2}
    assert view.loci[0].epistemic_state is IssueEpistemicState.CLAIMED
    assert set(semantic.claims) == {claim_1, claim_2}
    assert semantic.claims[claim_1].address_id == addr_1
    assert semantic.claims[claim_2].address_id == addr_2
    head_1 = semantic.issue_versions[semantic.issue_heads[addr_1]]
    assert head_1.claim_ids == (claim_1,)
    assert head_1.equivalent_address_ids == (addr_2,)


# --- F: conflict preservation -------------------------------------------------


def test_conflicts_with_preserves_both_claims_and_disputes_the_locus() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    address_id = address_id_for("J-c1")
    ledger.apply(_assert_claim("J-a1", address_id, quantity="7"))
    ledger.apply(_assert_claim("J-a2", address_id, quantity="10", authority=Authority.CANONICAL))
    claim_1, claim_2 = claim_id_for("J-a1"), claim_id_for("J-a2")
    ledger.apply(_conflict("J-conf", claim_1, claim_2))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert set(semantic.claims) == {claim_1, claim_2}
    assert semantic.conflicts[0].judgment_id == "J-conf"
    assert view.loci[0].epistemic_state is IssueEpistemicState.DISPUTED
    assert view.loci[0].disputed_claim_pairs == (tuple(sorted((claim_1, claim_2))),)
    head = semantic.issue_versions[semantic.issue_heads[address_id]]
    assert head.epistemic_state is IssueEpistemicState.DISPUTED
    assert set(head.claim_ids) == {claim_1, claim_2}


def test_conflicts_with_across_loci_raises() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_assert_claim("J-a1", addr_1))
    ledger.apply(_assert_claim("J-a2", addr_2))
    ledger.apply(_conflict("J-conf", claim_id_for("J-a1"), claim_id_for("J-a2")))

    with pytest.raises(ValueError, match="representative"):
        ledger.replay()


def test_conflicts_with_a_superseded_claim_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    address_id = address_id_for("J-c1")
    ledger.apply(_assert_claim("J-a1", address_id, quantity="7"))
    ledger.apply(_assert_claim("J-a2", address_id, quantity="10"))
    ledger.apply(_supersede("J-sup", "J-a2"))
    ledger.apply(_conflict("J-conf", claim_id_for("J-a1"), claim_id_for("J-a2")))

    with pytest.raises(ValueError, match="not live"):
        ledger.replay()


def test_conflicts_with_unknown_claim_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.apply(_assert_claim("J-a1", address_id_for("J-c1")))
    ledger.apply(_conflict("J-conf", claim_id_for("J-a1"), "CLAIM-nope"))

    with pytest.raises(ValueError, match="CLAIM-nope"):
        ledger.replay()


def test_conflicts_with_across_an_equivalent_locus_is_allowed() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_assert_claim("J-a1", addr_1))
    ledger.apply(_assert_claim("J-a2", addr_2))
    ledger.apply(_equivalent("J-eq", addr_1, addr_2))
    ledger.apply(_conflict("J-conf", claim_id_for("J-a1"), claim_id_for("J-a2")))

    view = derive_view(ledger.replay().semantic)

    assert len(view.loci) == 1
    assert view.loci[0].epistemic_state is IssueEpistemicState.DISPUTED


# --- D: supersession is append + recompute ------------------------------------


def _assert_heads_match_view(semantic: SemanticState) -> None:
    view = derive_view(semantic)
    members = {a: locus.address_ids for locus in view.loci for a in locus.address_ids}
    for address_id in semantic.addresses:
        head = semantic.issue_versions[semantic.issue_heads[address_id]]
        expected = tuple(a for a in members[address_id] if a != address_id)
        assert head.equivalent_address_ids == expected, address_id


def test_supersede_re_mints_heads_for_every_member_of_affected_loci() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_create("J-c3", "CAND-3"))
    addr_3 = address_id_for("J-c3")
    ledger.apply(_equivalent("J1", addr_1, addr_2))
    ledger.apply(_equivalent("J2", addr_2, addr_3))
    before = ledger.replay().semantic
    assert len(derive_view(before).loci) == 1
    sup_event = ledger.apply(_supersede("J-sup", "J1"))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert sorted(locus.address_ids for locus in view.loci) == sorted(
        [(addr_1,), tuple(sorted((addr_2, addr_3)))]
    )
    head_3 = semantic.issue_versions[semantic.issue_heads[addr_3]]
    assert head_3.equivalent_address_ids == (addr_2,)
    assert head_3.created_by_event_id == sup_event.event.event_id
    assert head_3.supersedes_version_id == before.issue_heads[addr_3]
    _assert_heads_match_view(semantic)


def test_equivalent_joining_two_loci_re_mints_every_member() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_create("J-c3", "CAND-3"))
    ledger.apply(_create("J-c4", "CAND-4"))
    addr_3, addr_4 = address_id_for("J-c3"), address_id_for("J-c4")
    ledger.apply(_equivalent("J1", addr_1, addr_2))
    ledger.apply(_equivalent("J2", addr_3, addr_4))
    before = ledger.replay().semantic
    join_event = ledger.apply(_equivalent("J3", addr_2, addr_3))

    semantic = ledger.replay().semantic

    for address_id in (addr_1, addr_4):
        head = semantic.issue_versions[semantic.issue_heads[address_id]]
        assert head.created_by_event_id == join_event.event.event_id
        assert head.supersedes_version_id == before.issue_heads[address_id]
    _assert_heads_match_view(semantic)


def test_issue_heads_agree_with_view_after_every_event() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_create("J-c3", "CAND-3"))
    addr_3 = address_id_for("J-c3")
    ledger.apply(_assert_claim("J-a1", addr_1, quantity="7"))
    ledger.apply(_assert_claim("J-a3", addr_3, quantity="10"))
    ledger.apply(_equivalent("J1", addr_1, addr_2))
    ledger.apply(_equivalent("J2", addr_2, addr_3))
    ledger.apply(_conflict("J-conf", claim_id_for("J-a1"), claim_id_for("J-a3")))
    ledger.apply(_supersede("J-sup1", "J1"))
    ledger.apply(_supersede("J-sup2", "J-sup1"))
    ledger.apply(_supersede("J-sup3", "J2"))
    ledger.apply(_distinct("J-d", addr_1, addr_3))

    for prefix in range(1, len(ledger.events) + 1):
        _assert_heads_match_view(replay(PROJECT, ledger.events[:prefix]).semantic)


def test_supersede_equivalent_splits_view_and_keeps_history() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    eq_event = ledger.apply(_equivalent("J-eq", addr_1, addr_2))
    before = ledger.replay().semantic
    sup_event = ledger.apply(
        _supersede(
            "J-sup",
            "J-eq",
        )
    )

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert len(view.loci) == 2
    assert "J-eq" in semantic.judgments
    assert semantic.supersessions == (
        SupersessionRecord(
            target_judgment_id="J-eq",
            superseding_judgment_id="J-sup",
            recorded_by_event_id=sup_event.event.event_id,
        ),
    )
    assert semantic.applied_judgment_ids == ("J-c1", "J-c2", "J-eq", "J-sup")
    assert len(semantic.equivalences) == 1
    for old_version_id in before.issue_versions:
        assert semantic.issue_versions[old_version_id] == before.issue_versions[old_version_id]
    eq_id = eq_event.event.event_id
    assert semantic.issue_versions[f"{eq_id}:{addr_1}"].equivalent_address_ids == (addr_2,)
    for address_id in (addr_1, addr_2):
        head = semantic.issue_versions[semantic.issue_heads[address_id]]
        assert head.created_by_event_id == sup_event.event.event_id
        assert head.created_by_judgment_id == "J-sup"
        assert head.equivalent_address_ids == ()
        assert head.supersedes_version_id == f"{eq_id}:{address_id}"


def test_supersede_target_must_be_applied() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.record(_equivalent("J-eq", addr_1, addr_2))
    ledger.apply(_supersede("J-sup", "J-eq"))

    with pytest.raises(ValueError, match="J-eq"):
        ledger.replay()


def test_supersede_inactive_target_raises() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_equivalent("J-eq", addr_1, addr_2))
    ledger.apply(_supersede("J-sup1", "J-eq"))
    ledger.apply(_supersede("J-sup2", "J-eq"))

    with pytest.raises(ValueError, match="J-eq.*not currently active"):
        ledger.replay()


def test_restored_target_can_be_superseded_again_and_all_remain_readable() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_equivalent("J1", addr_1, addr_2))
    ledger.apply(_supersede("J2", "J1"))
    assert len(derive_view(ledger.replay().semantic).loci) == 2
    ledger.apply(_supersede("J3", "J2"))
    restored = ledger.replay().semantic
    assert len(derive_view(restored).loci) == 1
    assert "J1" in active_judgment_ids(restored)
    ledger.apply(_supersede("J4", "J1"))

    semantic = ledger.replay().semantic

    assert active_judgment_ids(semantic) >= {"J3", "J4"}
    assert "J1" not in active_judgment_ids(semantic)
    assert len(derive_view(semantic).loci) == 2
    assert {"J1", "J2", "J3", "J4"} <= set(semantic.judgments)
    assert [(r.target_judgment_id, r.superseding_judgment_id) for r in semantic.supersessions] == [
        ("J1", "J2"),
        ("J2", "J3"),
        ("J1", "J4"),
    ]


def test_supersede_assert_claim_removes_claim_from_view_but_not_from_state() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    address_id = address_id_for("J-c1")
    ledger.apply(_assert_claim("J-a1", address_id, quantity="7"))
    ledger.apply(_assert_claim("J-a2", address_id, quantity="10", authority=Authority.CANONICAL))
    before = derive_view(ledger.replay().semantic)
    assert before.loci[0].epistemic_state is IssueEpistemicState.SETTLED
    sup_event = ledger.apply(_supersede("J-sup", "J-a2"))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)
    claim_1, claim_2 = claim_id_for("J-a1"), claim_id_for("J-a2")

    assert view.loci[0].claim_ids == (claim_1,)
    assert view.loci[0].epistemic_state is IssueEpistemicState.CLAIMED
    assert set(semantic.claims) == {claim_1, claim_2}
    head = semantic.issue_versions[semantic.issue_heads[address_id]]
    assert head.created_by_event_id == sup_event.event.event_id
    assert head.claim_ids == (claim_1,)
    assert head.epistemic_state is IssueEpistemicState.CLAIMED


def test_supersede_bind_deactivates_binding_in_view_but_not_in_state() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    address_id = address_id_for("J-c1")
    ledger.apply(_bind("J-b1", "CAND-2", address_id))
    assert dict(derive_view(ledger.replay().semantic).active_bindings) == {
        "CAND-1": address_id,
        "CAND-2": address_id,
    }
    ledger.apply(_supersede("J-sup", "J-b1"))

    semantic = ledger.replay().semantic

    assert dict(derive_view(semantic).active_bindings) == {"CAND-1": address_id}
    assert dict(semantic.bindings) == {"CAND-1": address_id, "CAND-2": address_id}


def test_supersede_create_address_keeps_address_and_deactivates_its_binding() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    address_id = address_id_for("J-c1")
    ledger.apply(_assert_claim("J-a1", address_id))
    ledger.apply(_supersede("J-sup", "J-c1"))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert address_id in semantic.addresses
    assert address_id in view.representatives
    assert dict(view.active_bindings) == {}
    assert dict(semantic.bindings) == {"CAND-1": address_id}
    assert view.loci[0].claim_ids == (claim_id_for("J-a1"),)


def test_supersede_conflict_clears_dispute_in_view_only() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    address_id = address_id_for("J-c1")
    ledger.apply(_assert_claim("J-a1", address_id, quantity="7"))
    ledger.apply(_assert_claim("J-a2", address_id, quantity="10"))
    ledger.apply(_conflict("J-conf", claim_id_for("J-a1"), claim_id_for("J-a2")))
    ledger.apply(_supersede("J-sup", "J-conf"))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert len(semantic.conflicts) == 1
    assert len(semantic.claims) == 2
    assert view.loci[0].epistemic_state is IssueEpistemicState.CLAIMED
    head = semantic.issue_versions[semantic.issue_heads[address_id]]
    assert head.epistemic_state is IssueEpistemicState.CLAIMED


# --- non-APPLY routes never touch state ----------------------------------------


@pytest.mark.parametrize(
    "route",
    [AdmissionRoute.REQUIRE_SECOND_LENS, AdmissionRoute.REQUIRE_HUMAN, AdmissionRoute.REJECT],
)
def test_non_apply_admission_records_decision_only(route: AdmissionRoute) -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_assert_claim("J-a1", addr_1))
    baseline = ledger.replay().semantic
    ledger.record(_equivalent("J-eq", addr_1, addr_2))
    ledger.record(_create("J-c3", "CAND-3"))
    ledger.record(_assert_claim("J-a2", addr_2))
    ledger.admit("J-eq", route)
    ledger.admit("J-c3", route)
    ledger.admit("J-a2", route)

    semantic = ledger.replay().semantic

    assert semantic.admissions["J-eq"].route is route
    assert semantic.admissions["J-c3"].route is route
    assert semantic.applied_judgment_ids == baseline.applied_judgment_ids
    assert semantic.addresses == baseline.addresses
    assert semantic.claims == baseline.claims
    assert semantic.bindings == baseline.bindings
    assert semantic.equivalences == baseline.equivalences
    assert semantic.conflicts == baseline.conflicts
    assert semantic.issue_versions == baseline.issue_versions
    assert semantic.issue_heads == baseline.issue_heads
    assert semantic.supersessions == baseline.supersessions
    view, baseline_view = derive_view(semantic), derive_view(baseline)
    # The interpretation is untouched; only pending governance records the held proposals.
    assert view.model_copy(update={"pending_judgment_ids": (), "satisfied_by": {}}) == (
        baseline_view.model_copy(update={"pending_judgment_ids": (), "satisfied_by": {}})
    )
    expected_pending = () if route is AdmissionRoute.REJECT else ("J-a2", "J-c3", "J-eq")
    assert view.pending_judgment_ids == expected_pending
    assert dict(view.satisfied_by) == {}


def test_rejected_then_applied_judgment_applies_once() -> None:
    ledger = _ledger_with_evidence()
    ledger.record(_create("J-c1", "CAND-1"))
    ledger.admit("J-c1", AdmissionRoute.REQUIRE_SECOND_LENS)
    ledger.admit("J-c1", AdmissionRoute.APPLY)

    semantic = ledger.replay().semantic

    assert semantic.admissions["J-c1"].route is AdmissionRoute.APPLY
    assert semantic.applied_judgment_ids == ("J-c1",)


def test_non_apply_admission_of_applied_judgment_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.admit("J-c1", AdmissionRoute.REJECT)

    with pytest.raises(ValueError, match="J-c1.*already applied"):
        ledger.replay()


def test_applying_the_same_judgment_twice_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.admit("J-c1")

    with pytest.raises(ValueError, match="J-c1"):
        ledger.replay()


# --- DISTINCT records only -----------------------------------------------------


def test_distinct_records_admission_without_state_change() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    baseline = ledger.replay().semantic
    ledger.apply(_distinct("J-d", addr_1, addr_2))

    semantic = ledger.replay().semantic

    assert semantic.applied_judgment_ids == (*baseline.applied_judgment_ids, "J-d")
    assert semantic.equivalences == ()
    assert semantic.issue_versions == baseline.issue_versions
    assert semantic.issue_heads == baseline.issue_heads
    assert len(derive_view(semantic).loci) == 2


# --- derivation edges ------------------------------------------------------------


def test_derivation_recorded_appends_edge_with_event_id() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    event = ledger.derive("D-1", "J-c1")
    ledger.derive("D-2", "D-1")

    semantic = ledger.replay().semantic

    assert [(e.child_id, e.parent_id) for e in semantic.derivations] == [
        ("D-1", "J-c1"),
        ("D-2", "D-1"),
    ]
    assert semantic.derivations[0].recorded_by_event_id == event.event.event_id


# --- reducer integration ---------------------------------------------------------


def test_semantic_events_do_not_disturb_non_semantic_state() -> None:
    ledger = Ledger()
    ledger._append(  # noqa: SLF001
        EventType.USER_STATED_INTENT, UserStatedIntentPayload(text="retain audits", actor_id="a")
    )
    ledger.ingest("EV-1")
    ledger.apply(_create("J-c1", "CAND-1"))

    state = ledger.replay()

    assert state.objects == {}
    assert state.gaps == {}
    assert state.revision == 4
    assert state.last_sequence == 4
    assert len(state.semantic.addresses) == 1


def test_reduce_semantic_event_rejects_non_semantic_event_types() -> None:
    stored = StoredEvent(
        sequence=1,
        event=EventEnvelope(
            event_id="EVT-1",
            project_id=PROJECT,
            event_type=EventType.USER_STATED_INTENT,
            occurred_at=OCCURRED_AT,
            payload=UserStatedIntentPayload(text="retain audits", actor_id="a"),
        ),
    )

    with pytest.raises(ValueError, match="USER_STATED_INTENT"):
        reduce_semantic_event(SemanticState(), stored)


def test_reduce_event_threads_semantic_state_through_intent_state() -> None:
    state = IntentState(project_id=PROJECT)
    ledger = Ledger()
    stored = ledger.ingest("EV-1")

    new_state = reduce_event(state, stored)

    assert "EV-1" in new_state.semantic.evidence
    assert state.semantic.evidence == {}


# --- P: replay determinism ---------------------------------------------------------


def _full_story() -> Ledger:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_bind("J-b1", "CAND-9", addr_1))
    ledger.apply(_assert_claim("J-a1", addr_1, quantity="7", evidence_ids=("EV-1",)))
    ledger.apply(
        _assert_claim(
            "J-a2",
            addr_2,
            quantity="10",
            evidence_ids=("EV-2",),
            authority=Authority.CANONICAL,
            reasoner=HUMAN_ALICE,
        )
    )
    ledger.record(_equivalent("J-eq0", addr_1, addr_2))
    ledger.admit("J-eq0", AdmissionRoute.REQUIRE_SECOND_LENS)
    ledger.apply(_equivalent("J-eq", addr_1, addr_2))
    ledger.apply(_conflict("J-conf", claim_id_for("J-a1"), claim_id_for("J-a2")))
    ledger.apply(_distinct("J-d", addr_1, addr_2))
    ledger.derive("D-1", "J-eq")
    ledger.derive("D-2", "D-1")
    ledger.apply(_supersede("J-sup", "J-conf"))
    return ledger


def _round_trip(events: list[StoredEvent]) -> list[StoredEvent]:
    return [
        StoredEvent(sequence=s.sequence, event=parse_event(s.event.model_dump(mode="json")))
        for s in events
    ]


def test_replay_is_deterministic_and_survives_json_round_trip() -> None:
    ledger = _full_story()

    first = replay(PROJECT, ledger.events)
    second = replay(PROJECT, _round_trip(ledger.events))
    third = replay(PROJECT, _round_trip(_round_trip(ledger.events)))

    assert first == second == third
    assert first.semantic == second.semantic
    assert derive_view(first.semantic) == derive_view(second.semantic)
    assert derive_view(first.semantic) == derive_view(third.semantic)
    assert first.semantic.claims[claim_id_for("J-a2")].value.quantity == Decimal("10")
    assert first.semantic.model_dump(mode="json") == second.semantic.model_dump(mode="json")
    assert len(first.semantic.derivations) == 2
    assert [
        (r.target_judgment_id, r.superseding_judgment_id) for r in first.semantic.supersessions
    ] == [("J-conf", "J-sup")]


# --- rebinding requires supersession (spec §4.5, §20.1, §21 #10) ------------------


def test_rebind_of_actively_bound_candidate_raises() -> None:
    ledger = _ledger_with_evidence()
    _, addr_2 = _two_addresses(ledger)
    ledger.apply(_bind("J-b1", "CAND-1", addr_2))

    with pytest.raises(ValueError, match="candidate CAND-1 already bound by J-c1"):
        ledger.replay()


def test_rebind_over_an_active_bind_raises() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_bind("J-b1", "CAND-9", addr_1))
    ledger.apply(_bind("J-b2", "CAND-9", addr_2))

    with pytest.raises(ValueError, match="candidate CAND-9 already bound by J-b1"):
        ledger.replay()


def test_rebind_to_the_same_address_while_binding_is_active_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.apply(_bind("J-b1", "CAND-1", address_id_for("J-c1")))

    with pytest.raises(ValueError, match="candidate CAND-1 already bound by J-c1"):
        ledger.replay()


def test_create_address_for_actively_bound_candidate_raises() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.apply(_create("J-c2", "CAND-1"))

    with pytest.raises(ValueError, match="candidate CAND-1 already bound by J-c1"):
        ledger.replay()


def test_rebind_after_superseding_create_records_new_binding_and_keeps_history() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_supersede("J-sup", "J-c1"))
    ledger.apply(_bind("J-b1", "CAND-1", addr_2))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert semantic.bindings["CAND-1"] == addr_2
    assert view.active_bindings["CAND-1"] == addr_2
    assert dict(view.active_bindings) == {"CAND-1": addr_2, "CAND-2": addr_2}
    assert "J-c1" in semantic.judgments
    assert "J-c1" in semantic.applied_judgment_ids
    assert "J-c1" not in active_judgment_ids(semantic)
    assert addr_1 in semantic.addresses
    assert semantic.addresses[addr_1].created_by_judgment_id == "J-c1"


def test_rebind_after_superseding_bind_records_new_binding_and_keeps_history() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.apply(_bind("J-b1", "CAND-9", addr_1))
    ledger.apply(_supersede("J-sup", "J-b1"))
    ledger.apply(_bind("J-b2", "CAND-9", addr_2))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert semantic.bindings["CAND-9"] == addr_2
    assert view.active_bindings["CAND-9"] == addr_2
    assert "J-b1" in semantic.applied_judgment_ids
    assert "J-b1" not in active_judgment_ids(semantic)
    assert semantic.judgments["J-b1"].proposal == BindToAddressProposal(
        candidate=_candidate("CAND-9"), address_id=addr_1
    )


def test_create_address_after_superseding_binding_records_new_binding() -> None:
    ledger = _ledger_with_evidence()
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.apply(_supersede("J-sup", "J-c1"))
    ledger.apply(_create("J-c2", "CAND-1"))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert set(semantic.addresses) == {address_id_for("J-c1"), address_id_for("J-c2")}
    assert semantic.bindings["CAND-1"] == address_id_for("J-c2")
    assert view.active_bindings["CAND-1"] == address_id_for("J-c2")


def test_rejected_rebind_leaves_binding_untouched() -> None:
    ledger = _ledger_with_evidence()
    addr_1, addr_2 = _two_addresses(ledger)
    ledger.record(_bind("J-b1", "CAND-1", addr_2))
    ledger.admit("J-b1", AdmissionRoute.REJECT)

    semantic = ledger.replay().semantic

    assert semantic.bindings["CAND-1"] == addr_1
    assert derive_view(semantic).active_bindings["CAND-1"] == addr_1
    assert semantic.admissions["J-b1"].route is AdmissionRoute.REJECT

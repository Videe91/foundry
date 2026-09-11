"""``SUPPORTS_CLAIM`` reducer, view and admission tests (9P plan Task 3; spec §12).

Invariants under test:

* an admitted ``SUPPORTS_CLAIM`` appends a ``ClaimSupportRecord`` and never rewrites
  ``SemanticClaim.evidence_ids``;
* the view derives ``effective_evidence`` = claim evidence ∪ evidence of ACTIVE support
  records, so a superseded support disappears from the view while its record remains;
* the claim must be live at admission time (structural, mirrored by the reducer, D-ADM-5);
* every cited evidence id must exist (admission and reducer);
* the reducer mints a fresh issue head at the claim's address;
* ``SUPPORTS_CLAIM`` is low-risk for a model reasoner;
* a support judgment bears on its claim's address for scoped stale attribution;
* replay with support records is deterministic across JSON round-trips.

Reducer tests drive hand-built ``StoredEvent`` sequences; the low-risk routing test
drives the real ``SemanticGovernor`` over an ``InMemoryEventStore``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy, route_judgment
from foundry.domain.common import Authority, SourceKind
from foundry.domain.events import (
    EventEnvelope,
    EventPayload,
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
    parse_event,
)
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.handoff import judgment_address_ids
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_state import ClaimSupportRecord
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState

PROJECT = "PROJ-1"
T0 = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")


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
        observed_at=T0,
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
    visible_evidence_ids: tuple[str, ...] = ("EV-1",),
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=visible_evidence_ids,
        rationale="EV-1 states a retention obligation for audit records.",
        reasoner=MODEL_A,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _create(judgment_id: str, candidate_id: str) -> SemanticJudgment:
    return _judgment(judgment_id, CreateAddressProposal(candidate=_candidate(candidate_id)))


def _assert_claim(judgment_id: str, address_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
            evidence_ids=("EV-1",),
            authority=Authority.OBSERVED,
        ),
    )


def _support(
    judgment_id: str,
    claim_id: str,
    evidence_ids: tuple[str, ...] = ("EV-2",),
    *,
    visible_evidence_ids: tuple[str, ...] | None = None,
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupportsClaimProposal(claim_id=claim_id, evidence_ids=evidence_ids),
        visible_evidence_ids=visible_evidence_ids or ("EV-1", *evidence_ids),
    )


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
                occurred_at=T0,
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

    def replay(self) -> IntentState:
        return replay(PROJECT, self.events)


def _claimed_ledger() -> tuple[Ledger, str, str]:
    """EV-1, EV-2 ingested; one address (J-c1) with one live claim (J-a1, cites EV-1).

    Events: EVT-1 EV-1, EVT-2 EV-2, EVT-3/4 J-c1, EVT-5/6 J-a1.
    """
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.ingest("EV-2")
    ledger.apply(_create("J-c1", "CAND-1"))
    address_id = address_id_for("J-c1")
    ledger.apply(_assert_claim("J-a1", address_id))
    return ledger, address_id, claim_id_for("J-a1")


# --- reducer -------------------------------------------------------------------------


def test_support_appends_record_and_leaves_claim_evidence_ids_untouched() -> None:
    ledger, _, claim_id = _claimed_ledger()
    ledger.apply(_support("J-s1", claim_id))

    semantic = ledger.replay().semantic

    assert semantic.claims[claim_id].evidence_ids == ("EV-1",)
    assert semantic.claim_supports == (
        ClaimSupportRecord(
            judgment_id="J-s1",
            claim_id=claim_id,
            evidence_ids=("EV-2",),
            recorded_by_event_id="EVT-8",
        ),
    )
    assert semantic.applied_judgment_ids == ("J-c1", "J-a1", "J-s1")
    assert set(semantic.claims) == {claim_id}


def test_effective_evidence_includes_supporting_evidence() -> None:
    ledger, _, claim_id = _claimed_ledger()
    before = derive_view(ledger.replay().semantic)
    ledger.apply(_support("J-s1", claim_id))

    view = derive_view(ledger.replay().semantic)

    assert before.effective_evidence == {claim_id: ("EV-1",)}
    assert before.active_support_judgment_ids == ()
    assert view.effective_evidence == {claim_id: ("EV-1", "EV-2")}
    assert view.active_support_judgment_ids == ("J-s1",)
    with pytest.raises(TypeError):
        view.effective_evidence[claim_id] = ()  # type: ignore[index]


def test_support_targeting_superseded_claim_raises_in_reducer_and_rejects_in_admission() -> None:
    ledger, _, claim_id = _claimed_ledger()
    ledger.apply(_supersede("J-sup", "J-a1"))
    state = ledger.replay()
    support = _support("J-s1", claim_id)

    decision = route_judgment(state, support, AdmissionPolicy())

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (f"STRUCTURAL: claim {claim_id} is not live",)

    ledger.apply(support)
    with pytest.raises(ValueError, match=f"claim {claim_id} is not live"):
        ledger.replay()


def test_support_citing_unknown_evidence_raises_and_rejects() -> None:
    ledger, _, claim_id = _claimed_ledger()
    state = ledger.replay()
    # Cited only by the proposal (not by ``visible_evidence_ids``) so the single
    # structural reason is attributable to the proposal's evidence reference.
    support = _support("J-s1", claim_id, evidence_ids=("EV-nope",), visible_evidence_ids=("EV-1",))

    decision = route_judgment(state, support, AdmissionPolicy())

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == ("STRUCTURAL: evidence EV-nope does not exist",)

    ledger.apply(support)
    with pytest.raises(ValueError, match="EV-nope"):
        ledger.replay()


def test_support_targeting_unknown_claim_rejects_once_and_raises() -> None:
    ledger, _, _ = _claimed_ledger()
    state = ledger.replay()
    support = _support("J-s1", "CLAIM-nope")

    decision = route_judgment(state, support, AdmissionPolicy())

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == ("STRUCTURAL: claim CLAIM-nope does not exist",)

    ledger.apply(support)
    with pytest.raises(ValueError, match="unknown claim CLAIM-nope"):
        ledger.replay()


def test_superseded_support_disappears_from_effective_evidence_but_record_remains() -> None:
    ledger, _, claim_id = _claimed_ledger()
    ledger.apply(_support("J-s1", claim_id))
    ledger.apply(_supersede("J-sup", "J-s1"))

    semantic = ledger.replay().semantic
    view = derive_view(semantic)

    assert view.effective_evidence == {claim_id: ("EV-1",)}
    assert view.active_support_judgment_ids == ()
    assert [r.judgment_id for r in semantic.claim_supports] == ["J-s1"]
    assert semantic.claims[claim_id].evidence_ids == ("EV-1",)
    assert claim_id in view.loci[0].claim_ids


def test_support_mints_new_issue_head_with_created_by_judgment_id() -> None:
    ledger, address_id, claim_id = _claimed_ledger()
    previous_head = ledger.replay().semantic.issue_heads[address_id]
    ledger.apply(_support("J-s1", claim_id))

    semantic = ledger.replay().semantic

    head = semantic.issue_heads[address_id]
    assert head == f"EVT-8:{address_id}"
    version = semantic.issue_versions[head]
    assert version.created_by_judgment_id == "J-s1"
    assert version.created_by_event_id == "EVT-8"
    assert version.supersedes_version_id == previous_head
    assert version.claim_ids == (claim_id,)
    assert version.address_id == address_id


def test_superseding_a_support_mints_a_fresh_head_at_the_claims_address() -> None:
    ledger, address_id, claim_id = _claimed_ledger()
    ledger.apply(_support("J-s1", claim_id))
    support_head = ledger.replay().semantic.issue_heads[address_id]
    ledger.apply(_supersede("J-sup", "J-s1"))

    semantic = ledger.replay().semantic

    head = semantic.issue_heads[address_id]
    assert head == f"EVT-10:{address_id}"
    assert semantic.issue_versions[head].supersedes_version_id == support_head
    assert semantic.issue_versions[head].created_by_judgment_id == "J-sup"


# --- admission routing through the governor ------------------------------------------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0.replace(minute=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def test_support_routes_apply_as_low_risk_from_a_model() -> None:
    clock = _clock()
    governor = SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )
    governor.ingest(_evidence("EV-1"))
    governor.ingest(_evidence("EV-2"))
    assert governor.submit(_create("J-c1", "CAND-1")).route is AdmissionRoute.APPLY
    address_id = address_id_for("J-c1")
    assert governor.submit(_assert_claim("J-a1", address_id)).route is AdmissionRoute.APPLY
    claim_id = claim_id_for("J-a1")

    decision = governor.submit(_support("J-s1", claim_id))

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)
    semantic = governor.state().semantic
    assert [r.judgment_id for r in semantic.claim_supports] == ["J-s1"]
    assert semantic.claims[claim_id].evidence_ids == ("EV-1",)
    assert governor.view().effective_evidence == {claim_id: ("EV-1", "EV-2")}


# --- handoff attribution -------------------------------------------------------------


def test_support_judgment_bears_on_its_claims_address() -> None:
    ledger, address_id, claim_id = _claimed_ledger()
    support = _support("J-s1", claim_id)
    ledger.apply(support)
    semantic = ledger.replay().semantic

    assert judgment_address_ids(semantic, support) == frozenset({address_id})
    assert judgment_address_ids(semantic, _support("J-s9", "CLAIM-nope")) == frozenset()
    assert judgment_address_ids(semantic, _supersede("J-sup", "J-s1")) == frozenset({address_id})


# --- replay determinism --------------------------------------------------------------


def _round_trip(events: list[StoredEvent]) -> list[StoredEvent]:
    return [
        StoredEvent(sequence=s.sequence, event=parse_event(s.event.model_dump(mode="json")))
        for s in events
    ]


def test_replay_is_identical_with_support_records() -> None:
    ledger, _, claim_id = _claimed_ledger()
    ledger.apply(_support("J-s1", claim_id))
    ledger.apply(_support("J-s2", claim_id, evidence_ids=("EV-1", "EV-2")))
    ledger.apply(_supersede("J-sup", "J-s1"))

    first = replay(PROJECT, ledger.events)
    second = replay(PROJECT, _round_trip(ledger.events))
    third = replay(PROJECT, _round_trip(_round_trip(ledger.events)))

    assert first == second == third
    assert first.semantic.model_dump(mode="json") == second.semantic.model_dump(mode="json")
    assert derive_view(first.semantic) == derive_view(second.semantic)
    assert derive_view(first.semantic) == derive_view(third.semantic)
    assert [r.judgment_id for r in first.semantic.claim_supports] == ["J-s1", "J-s2"]
    view = derive_view(first.semantic)
    assert view.effective_evidence == {claim_id: ("EV-1", "EV-2")}
    assert view.active_support_judgment_ids == ("J-s2",)
    assert view.model_dump(mode="json")["effective_evidence"] == {claim_id: ["EV-1", "EV-2"]}

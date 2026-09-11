"""Pending material governance and the SATISFIED_BY derivation (9P Task 4).

Spec §17 (derived status; declined supersession), §24 (pending material governance
qualifies readiness). Every test drives the real ``SemanticGovernor`` over an
``InMemoryEventStore`` so admissions, applied ids and supersessions are the reducer's
own. The derivation under test reads only those records: no new event, no new durable
state, and never an inferred ``CONFLICTS_WITH``.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.handoff import build_intent_decision_handoff
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, Materiality, Provenance, SourceKind
from foundry.domain.events import EventEnvelope, EventType, SemanticObjectPayload
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.handoff import SemanticReadiness
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
    CreateAddressProposal,
    DistinctProposal,
    EquivalentProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_view import SemanticLocus, derive_view

PROJECT = "PROJ-PENDING"
T0 = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="p1")
MODEL_B = ReasonerFingerprint(provider="anthropic", model="claude-opus-5", policy_version="p1")
HUMAN_ALICE = ReasonerFingerprint(provider="human", model="human://alice", policy_version="p1")
HUMAN_BOB = ReasonerFingerprint(provider="human", model="human://bob", policy_version="p1")
PROVENANCE = Provenance(source_kind=SourceKind.HUMAN, source_ref="human://owner")

ADDR_A = address_id_for(PROJECT, "J-cA")
ADDR_A2 = address_id_for(PROJECT, "J-cA2")
ADDR_B = address_id_for(PROJECT, "J-cB")
CLAIM_A = claim_id_for(PROJECT, "J-clA")
CLAIM_A_NEW = claim_id_for(PROJECT, "J-clA-new")
CLAIM_B = claim_id_for(PROJECT, "J-clB")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)


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


def _evidence(evidence_id: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=f"Evidence body {evidence_id}.",
        observed_at=T0,
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
    evidence_id: str = "EV-A",
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


def _supersede(
    judgment_id: str, target: str, *, reasoner: ReasonerFingerprint = MODEL_A
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupersedeProposal(target_judgment_id=target, reason="The older claim is corrected."),
        reasoner=reasoner,
    )


def _authority(record_id: str, actor: str) -> AuthorityRecord:
    return AuthorityRecord(
        id=record_id,
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=T0,
        scope=(),
        subject_id="records",
        authorized_by=actor,
        rationale=f"{actor} owns semantic corrections project-wide.",
    )


def _intent(object_id: str, scope: tuple[str, ...]) -> Intent:
    return Intent(
        id=object_id,
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=T0,
        scope=scope,
        mission=f"Mission for {scope}",
    )


def _requirement(object_id: str, scope: tuple[str, ...]) -> Requirement:
    return Requirement(
        id=object_id,
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=T0,
        scope=scope,
        statement=f"Requirement for {scope}",
        materiality=Materiality.HIGH,
        requires_metric=True,
        metric_exempt_reason="Qualitative obligation.",
        requires_verification=True,
        verification_exempt_reason="Verified by inspection.",
    )


def _append_object(
    store: InMemoryEventStore, event_type: EventType, obj: Intent | Requirement
) -> None:
    sequence = store.current_sequence(PROJECT)
    store.append(
        EventEnvelope(
            event_id=f"EVT-OBJ-{obj.id}",
            project_id=PROJECT,
            event_type=event_type,
            occurred_at=T0,
            payload=SemanticObjectPayload(object=obj),
        ),
        expected_sequence=sequence,
    )


def _story() -> tuple[InMemoryEventStore, SemanticGovernor]:
    """Scope A: one address with one claim. Scope B: one address with one claim.

    The AI corrects A: a new claim is asserted at ``ADDR_A`` (auto-applied) and a
    ``SUPERSEDE`` of the old claim's judgment is proposed, which — being material with
    no independent lens — routes ``REQUIRE_SECOND_LENS`` and stays pending.
    """
    store = InMemoryEventStore()
    governor = _governor(store)
    for evidence_id in ("EV-A", "EV-A2", "EV-B"):
        governor.ingest(_evidence(evidence_id))
    assert governor.submit(_create("J-cA", ("A",), "EV-A")).route is AdmissionRoute.APPLY
    assert governor.submit(_create("J-cB", ("B",), "EV-B")).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-clA", ADDR_A, "EV-A", "7")).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-clB", ADDR_B, "EV-B", "30")).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-clA-new", ADDR_A, "EV-A2", "14")).route is AdmissionRoute.APPLY
    pending = governor.submit(_supersede("J-supA", "J-clA"))
    assert pending.route is AdmissionRoute.REQUIRE_SECOND_LENS
    return store, governor


def _readiness(governor: SemanticGovernor, scope: str) -> SemanticReadiness:
    return build_intent_decision_handoff(governor.state(), scope).readiness


def _locus(governor: SemanticGovernor, representative_id: str) -> SemanticLocus:
    return next(
        locus for locus in governor.view().loci if locus.representative_id == representative_id
    )


# --- pending qualifies readiness, scoped --------------------------------------------


def test_pending_supersede_blocks_the_affected_scope_only() -> None:
    _, governor = _story()
    view = governor.view()

    assert view.pending_judgment_ids == ("J-supA",)
    assert dict(view.satisfied_by) == {}

    readiness_a = _readiness(governor, "A")
    readiness_b = _readiness(governor, "B")

    assert readiness_a.pending_material_judgment_ids == ("J-supA",)
    assert readiness_a.semantic_blockers_clear is False
    assert readiness_a.ready is False
    assert readiness_a.disputed_locus_ids == ()
    assert readiness_a.stale_object_ids == ()

    assert readiness_b.pending_material_judgment_ids == ()
    assert readiness_b.semantic_blockers_clear is True

    handoff_a = build_intent_decision_handoff(governor.state(), "A")
    handoff_b = build_intent_decision_handoff(governor.state(), "B")
    assert handoff_a.pending_material_judgment_ids == ("J-supA",)
    assert handoff_b.pending_material_judgment_ids == ()


# --- SATISFIED_BY: a human AGREE with the identical signature --------------------------


def test_human_agreeing_judgment_satisfies_the_pending_ai_proposal() -> None:
    _, governor = _story()
    governor.record_authority(_authority("AUTH-ALICE", "human://alice"))

    decision = governor.submit(
        _supersede("J-hsupA", "J-clA", reasoner=HUMAN_ALICE), human_actor_id="human://alice"
    )

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("HUMAN_AUTHORITY",)
    state = governor.state()
    # The AI proposal's own admission is untouched: it was never re-routed or applied.
    assert state.semantic.admissions["J-supA"].route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert "J-supA" not in state.semantic.applied_judgment_ids
    assert "J-hsupA" in state.semantic.applied_judgment_ids

    view = governor.view()
    assert dict(view.satisfied_by) == {"J-supA": "J-hsupA"}
    assert view.pending_judgment_ids == ()
    assert CLAIM_A not in _locus(governor, ADDR_A).claim_ids
    assert CLAIM_A_NEW in _locus(governor, ADDR_A).claim_ids

    readiness_a = _readiness(governor, "A")
    assert readiness_a.pending_material_judgment_ids == ()
    assert readiness_a.stale_object_ids == ()
    assert readiness_a.disputed_locus_ids == ()
    assert readiness_a.semantic_blockers_clear is True
    assert build_intent_decision_handoff(governor.state(), "A").pending_material_judgment_ids == ()


# --- DECLINE / unanswered: pending stays pending, both claims live ---------------------


def test_declined_or_unanswered_proposal_remains_pending() -> None:
    _, governor = _story()
    # Declining is a recorded non-action: the human submits nothing.
    view = governor.view()

    assert view.pending_judgment_ids == ("J-supA",)
    assert "J-supA" not in view.satisfied_by
    assert "J-clA" in governor.state().semantic.applied_judgment_ids
    locus_a = _locus(governor, ADDR_A)
    assert set(locus_a.claim_ids) == {CLAIM_A, CLAIM_A_NEW}
    assert _readiness(governor, "A").pending_material_judgment_ids == ("J-supA",)
    assert _readiness(governor, "A").semantic_blockers_clear is False


def test_no_conflict_is_inferred_from_a_declined_supersession() -> None:
    _, governor = _story()
    state = governor.state()
    view = governor.view()

    assert state.semantic.conflicts == ()
    assert view.active_conflict_judgment_ids == ()
    locus_a = _locus(governor, ADDR_A)
    assert locus_a.epistemic_state is IssueEpistemicState.CLAIMED
    assert locus_a.disputed_claim_pairs == ()
    readiness_a = _readiness(governor, "A")
    assert readiness_a.disputed_locus_ids == ()
    # The reason the scope is not ready is the pending proposal id, not a dispute.
    assert readiness_a.pending_material_judgment_ids == ("J-supA",)


# --- REJECT is never pending -----------------------------------------------------------


def test_rejected_judgment_is_never_pending() -> None:
    _, governor = _story()

    rejected = governor.submit(_supersede("J-supMissing", "J-does-not-exist"))

    assert rejected.route is AdmissionRoute.REJECT
    view = governor.view()
    assert "J-supMissing" not in view.pending_judgment_ids
    assert "J-supMissing" not in view.satisfied_by
    assert view.pending_judgment_ids == ("J-supA",)
    assert _readiness(governor, "A").pending_material_judgment_ids == ("J-supA",)


# --- SATISFIED_BY is kind + signature, nothing looser ----------------------------------


def test_satisfied_by_requires_same_kind_and_signature() -> None:
    _, governor = _story()
    governor.ingest(_evidence("EV-A3"))
    assert governor.submit(_create("J-cA2", ("A",), "EV-A3")).route is AdmissionRoute.APPLY
    pending_eq = governor.submit(
        _judgment("J-eq", EquivalentProposal(address_a=ADDR_A, address_b=ADDR_A2))
    )
    assert pending_eq.route is AdmissionRoute.REQUIRE_SECOND_LENS
    governor.record_authority(_authority("AUTH-ALICE", "human://alice"))

    # Same PAIR signature, different kind: an applied DISTINCT never satisfies EQUIVALENT.
    distinct = governor.submit(
        _judgment(
            "J-hdistinct",
            DistinctProposal(address_a=ADDR_A, address_b=ADDR_A2),
            reasoner=HUMAN_ALICE,
        ),
        human_actor_id="human://alice",
    )
    assert distinct.route is AdmissionRoute.APPLY
    # Same kind, different signature: a SUPERSEDE of another target does not satisfy.
    other_target = governor.submit(
        _supersede("J-hsupB", "J-clB", reasoner=HUMAN_ALICE), human_actor_id="human://alice"
    )
    assert other_target.route is AdmissionRoute.APPLY

    view = governor.view()
    assert dict(view.satisfied_by) == {}
    assert view.pending_judgment_ids == ("J-eq", "J-supA")
    assert _readiness(governor, "A").pending_material_judgment_ids == ("J-eq", "J-supA")


def test_satisfied_by_picks_the_earliest_applied_agreeing_judgment() -> None:
    _, governor = _story()
    governor.ingest(_evidence("EV-A3"))
    assert governor.submit(_create("J-cA2", ("A",), "EV-A3")).route is AdmissionRoute.APPLY
    assert (
        governor.submit(
            _judgment("J-eq", EquivalentProposal(address_a=ADDR_A, address_b=ADDR_A2))
        ).route
        is AdmissionRoute.REQUIRE_SECOND_LENS
    )
    governor.record_authority(_authority("AUTH-ALICE", "human://alice"))
    governor.record_authority(_authority("AUTH-BOB", "human://bob"))
    for judgment_id, reasoner, actor in (
        ("J-heq-alice", HUMAN_ALICE, "human://alice"),
        ("J-heq-bob", HUMAN_BOB, "human://bob"),
    ):
        decision = governor.submit(
            _judgment(
                judgment_id,
                EquivalentProposal(address_a=ADDR_A2, address_b=ADDR_A),
                reasoner=reasoner,
            ),
            human_actor_id=actor,
        )
        assert decision.route is AdmissionRoute.APPLY

    view = governor.view()
    assert dict(view.satisfied_by) == {"J-eq": "J-heq-alice"}
    assert "J-eq" not in view.pending_judgment_ids


# --- ready = closure AND semantic blockers clear ---------------------------------------


def test_ready_requires_no_pending_material_judgments() -> None:
    store, governor = _story()
    _append_object(store, EventType.SEMANTIC_OBJECT_RECORDED, _intent("INTENT-A", ("A",)))
    _append_object(store, EventType.REQUIREMENT_CANONICALIZED, _requirement("REQ-A", ("A",)))

    blocked = _readiness(governor, "A")
    assert blocked.closure.closed is True
    assert blocked.disputed_locus_ids == ()
    assert blocked.stale_object_ids == ()
    assert blocked.pending_material_judgment_ids == ("J-supA",)
    assert blocked.semantic_blockers_clear is False
    assert blocked.ready is False

    # Scope B has no v0 closure objects: semantic blockers are clear, yet not ready.
    unclosed = _readiness(governor, "B")
    assert unclosed.closure.closed is False
    assert unclosed.semantic_blockers_clear is True
    assert unclosed.ready is False

    governor.record_authority(_authority("AUTH-ALICE", "human://alice"))
    assert (
        governor.submit(
            _supersede("J-hsupA", "J-clA", reasoner=HUMAN_ALICE), human_actor_id="human://alice"
        ).route
        is AdmissionRoute.APPLY
    )

    satisfied = _readiness(governor, "A")
    assert satisfied.closure.closed is True
    assert satisfied.pending_material_judgment_ids == ()
    assert satisfied.semantic_blockers_clear is True
    assert satisfied.ready is True


# --- replay determinism ------------------------------------------------------------------


def test_replay_reproduces_pending_and_satisfied() -> None:
    store, governor = _story()
    governor.ingest(_evidence("EV-A3"))
    assert governor.submit(_create("J-cA2", ("A",), "EV-A3")).route is AdmissionRoute.APPLY
    assert (
        governor.submit(
            _judgment("J-eq", EquivalentProposal(address_a=ADDR_A, address_b=ADDR_A2))
        ).route
        is AdmissionRoute.REQUIRE_SECOND_LENS
    )
    # An independent DISTINCT over the same pair is a lens disagreement -> REQUIRE_HUMAN.
    assert (
        governor.submit(
            _judgment(
                "J-distinct-b",
                DistinctProposal(address_a=ADDR_A, address_b=ADDR_A2),
                reasoner=MODEL_B,
            )
        ).route
        is AdmissionRoute.REQUIRE_HUMAN
    )
    governor.record_authority(_authority("AUTH-ALICE", "human://alice"))
    assert (
        governor.submit(
            _supersede("J-hsupA", "J-clA", reasoner=HUMAN_ALICE), human_actor_id="human://alice"
        ).route
        is AdmissionRoute.APPLY
    )

    live = governor.view()
    assert live.pending_judgment_ids == ("J-distinct-b", "J-eq")
    assert dict(live.satisfied_by) == {"J-supA": "J-hsupA"}

    events = store.load(PROJECT)
    replayed_once = derive_view(replay(PROJECT, events).semantic)
    replayed_twice = derive_view(replay(PROJECT, events).semantic)

    assert replayed_once == live
    assert replayed_twice == live
    assert replayed_once.pending_judgment_ids == live.pending_judgment_ids
    assert dict(replayed_once.satisfied_by) == dict(live.satisfied_by)
    assert build_intent_decision_handoff(
        replay(PROJECT, events), "A"
    ) == build_intent_decision_handoff(governor.state(), "A")
    assert build_intent_decision_handoff(
        replay(PROJECT, events), "A"
    ).readiness.pending_material_judgment_ids == ("J-distinct-b", "J-eq")

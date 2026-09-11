"""Preregistered derivation fixture (plan Task 11; spec §23).

Experiment instrumentation only: the Track A and control derivation chains are attached
to a governor AFTER T1 completes and BEFORE any T2 evidence is ingested, from T1 state
alone. Every test drives the real ``InMemoryEventStore`` -> ``replay`` path with
hand-built judgments; nothing is mocked.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.events import DerivationPayload, EventType
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.experiments.longitudinal.derivations import (
    CONTROL_CHAIN,
    TRACK_A_CHAIN,
    RootDesignation,
    attach_preregistered_chains,
    designate_root,
)

PROJECT = "PROJ-LONG"
T0 = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="p1")
HUMAN_ALICE = ReasonerFingerprint(provider="human", model="human://alice", policy_version="p1")


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0.replace(minute=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _governor(store: InMemoryEventStore | None = None) -> SemanticGovernor:
    clock = _clock()
    return SemanticGovernor(
        store=store or InMemoryEventStore(),
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )


SPEC_REF = "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md"


def _evidence(evidence_id: str = "EV-T1-01", artifact_ref: str | None = None) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"git://097584a/{evidence_id}",
        content=f"Content of {evidence_id}.",
        observed_at=T0,
        artifact_ref=artifact_ref,
    )


def _candidate(candidate_id: str, scope: tuple[str, ...]) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject=f"subject {candidate_id}",
        facet="meaning",
        scope=scope,
        evidence_ids=("EV-T1-01",),
    )


def _judgment(
    judgment_id: str, proposal: JudgmentProposal, *, reasoner: ReasonerFingerprint = MODEL_A
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=("EV-T1-01",),
        rationale="EV-T1-01 states it.",
        reasoner=reasoner,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _create(judgment_id: str, candidate_id: str, scope: tuple[str, ...]) -> SemanticJudgment:
    return _judgment(judgment_id, CreateAddressProposal(candidate=_candidate(candidate_id, scope)))


def _assert_claim(judgment_id: str, address_id: str, quantity: str = "7") -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="year"),
            evidence_ids=("EV-T1-01",),
            authority=Authority.OBSERVED,
        ),
    )


def _authority_record() -> AuthorityRecord:
    return AuthorityRecord(
        id="AUTH-1",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref="human://founder"),
        created_at=T0,
        subject_id="intent-engine",
        authorized_by="human://alice",
        rationale="Owns intent-engine decisions.",
    )


def _t1_state(store: InMemoryEventStore) -> tuple[SemanticGovernor, str, str]:
    """T1: one Track A address with two claims, one constitution address.

    ``J-zz`` is applied BEFORE ``J-a1`` at the Track A address so that "earliest"
    discriminates ledger order (J-zz) from lexicographic order (J-a1).
    """
    governor = _governor(store)
    governor.ingest(_evidence())
    governor.submit(_create("J-cA", "CAND-A", ("intent-engine",)))
    governor.submit(_create("J-cN", "CAND-N", ("constitution",)))
    addr_a = address_id_for(PROJECT, "J-cA")
    addr_n = address_id_for(PROJECT, "J-cN")
    assert governor.submit(_assert_claim("J-zz", addr_a)).route is AdmissionRoute.APPLY
    assert governor.submit(_assert_claim("J-a1", addr_a, "8")).route is AdmissionRoute.APPLY
    assert governor.submit(_assert_claim("J-n1", addr_n)).route is AdmissionRoute.APPLY
    return governor, addr_a, addr_n


def _designations(
    governor: SemanticGovernor, addr_a: str, addr_n: str
) -> tuple[RootDesignation, RootDesignation]:
    clock = _clock()
    track_a = designate_root(governor, track="A", address_id=addr_a, clock=lambda: next(clock))
    control = designate_root(
        governor, track="CONTROL", address_id=addr_n, clock=lambda: next(clock)
    )
    return track_a, control


# --- constants -----------------------------------------------------------------------


def test_chains_are_the_approved_ids() -> None:
    assert TRACK_A_CHAIN == (
        "artifact:docs/superpowers/plans/2026-09-11-intent-intelligence-v2-core.md#6.1",
        "artifact:src/foundry/domain/admission.py",
        "artifact:tests/unit/test_admission.py",
    )
    assert CONTROL_CHAIN == ("control:D-N1", "control:D-N2")
    assert set(TRACK_A_CHAIN).isdisjoint(CONTROL_CHAIN)


# --- designate_root ------------------------------------------------------------------


def test_designate_root_picks_earliest_applied_assert_claim_at_address_and_records_sequence() -> (
    None
):
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    designated_at = datetime(2026, 9, 11, 9, 30, tzinfo=UTC)
    sequence_at_designation = store.current_sequence(PROJECT)

    designation = designate_root(
        governor, track="A", address_id=addr_a, clock=lambda: designated_at
    )

    assert designation == RootDesignation(
        track="A",
        address_id=addr_a,
        judgment_id="J-zz",  # earliest in ledger order, not lexicographic order
        ledger_sequence_at_designation=sequence_at_designation,
        designated_at=designated_at,
    )
    assert governor.state().last_sequence == sequence_at_designation
    assert store.current_sequence(PROJECT) == sequence_at_designation  # writes nothing

    control = designate_root(governor, track="CONTROL", address_id=addr_n, clock=lambda: T0)
    assert control.judgment_id == "J-n1"
    assert control.track == "CONTROL"


def test_designate_root_refuses_address_without_claim() -> None:
    governor = _governor()
    governor.ingest(_evidence())
    governor.submit(_create("J-cA", "CAND-A", ("intent-engine",)))
    addr_a = address_id_for(PROJECT, "J-cA")

    with pytest.raises(ValueError, match="no applied ASSERT_CLAIM"):
        designate_root(governor, track="A", address_id=addr_a, clock=lambda: T0)

    with pytest.raises(ValueError, match="no applied ASSERT_CLAIM"):
        designate_root(governor, track="A", address_id="ADDR-unknown", clock=lambda: T0)


# --- attach_preregistered_chains -----------------------------------------------------


def test_attach_records_five_derivation_events_in_order() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    before = store.current_sequence(PROJECT)

    events = attach_preregistered_chains(
        governor, track_a=track_a, control=control, t2_artifact_refs=frozenset()
    )

    assert len(events) == 5
    assert [e.sequence for e in events] == [before + i for i in range(1, 6)]
    assert all(e.event.event_type is EventType.DERIVATION_RECORDED for e in events)
    payloads = [e.event.payload for e in events]
    assert all(isinstance(p, DerivationPayload) for p in payloads)
    recorded = [(p.child_id, p.parent_id) for p in payloads if isinstance(p, DerivationPayload)]
    assert recorded == [
        (TRACK_A_CHAIN[0], "J-zz"),
        (TRACK_A_CHAIN[1], TRACK_A_CHAIN[0]),
        (TRACK_A_CHAIN[2], TRACK_A_CHAIN[1]),
        (CONTROL_CHAIN[0], "J-n1"),
        (CONTROL_CHAIN[1], CONTROL_CHAIN[0]),
    ]
    edges = governor.state().semantic.derivations
    assert [(e.child_id, e.parent_id) for e in edges] == recorded
    assert governor.view().stale_ids == ()


def test_track_a_supersession_stales_the_three_descendants_and_not_the_control() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    attach_preregistered_chains(
        governor, track_a=track_a, control=control, t2_artifact_refs=frozenset()
    )
    assert governor.view().stale_ids == ()

    governor.record_authority(_authority_record())
    decision = governor.submit(
        _judgment(
            "J-sup",
            SupersedeProposal(
                target_judgment_id=track_a.judgment_id, reason="§4.5 reading corrected at T2."
            ),
            reasoner=HUMAN_ALICE,
        ),
        human_actor_id="human://alice",
    )
    assert decision.route is AdmissionRoute.APPLY

    stale = set(governor.view().stale_ids)
    assert stale >= set(TRACK_A_CHAIN)
    assert stale.isdisjoint(CONTROL_CHAIN)
    assert "J-n1" not in stale
    # history untouched: all five edges still recorded
    assert len(governor.state().semantic.derivations) == 5


def test_attach_refuses_if_t2_evidence_already_ingested() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    governor.ingest(_evidence("EV-T2-01"))
    before = store.current_sequence(PROJECT)

    with pytest.raises(ValueError, match="T2 evidence already ingested"):
        attach_preregistered_chains(
            governor, track_a=track_a, control=control, t2_artifact_refs=frozenset()
        )

    assert store.current_sequence(PROJECT) == before
    assert governor.state().semantic.derivations == ()


def test_attach_refuses_timeline_ids_at_or_beyond_t10() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    governor.ingest(_evidence("EV-T10-01"))
    before = store.current_sequence(PROJECT)

    with pytest.raises(ValueError, match="T2 evidence already ingested"):
        attach_preregistered_chains(
            governor, track_a=track_a, control=control, t2_artifact_refs=frozenset()
        )

    assert store.current_sequence(PROJECT) == before
    assert governor.state().semantic.derivations == ()


def test_attach_refuses_if_a_designated_root_is_already_superseded() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    governor.record_authority(_authority_record())
    decision = governor.submit(
        _judgment(
            "J-sup",
            SupersedeProposal(target_judgment_id=track_a.judgment_id, reason="Superseded early."),
            reasoner=HUMAN_ALICE,
        ),
        human_actor_id="human://alice",
    )
    assert decision.route is AdmissionRoute.APPLY
    before = store.current_sequence(PROJECT)

    with pytest.raises(ValueError, match=track_a.judgment_id):
        attach_preregistered_chains(
            governor, track_a=track_a, control=control, t2_artifact_refs=frozenset()
        )

    assert store.current_sequence(PROJECT) == before
    assert governor.state().semantic.derivations == ()


def test_attach_refuses_if_a_t2_artifact_ref_is_present_as_a_post_t1_version() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    governor.ingest(_evidence("EV-T2-01", artifact_ref=SPEC_REF))
    before = store.current_sequence(PROJECT)

    with pytest.raises(ValueError, match="T2 evidence already ingested"):
        attach_preregistered_chains(
            governor, track_a=track_a, control=control, t2_artifact_refs=frozenset({SPEC_REF})
        )

    assert store.current_sequence(PROJECT) == before
    assert governor.state().semantic.derivations == ()


def test_artifact_ref_guard_is_independent_of_the_id_prefix_guard() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    governor.ingest(_evidence("EV-X-01", artifact_ref=SPEC_REF))  # not a timeline id

    with pytest.raises(ValueError, match="T2 evidence already ingested"):
        attach_preregistered_chains(
            governor, track_a=track_a, control=control, t2_artifact_refs=frozenset({SPEC_REF})
        )

    assert governor.state().semantic.derivations == ()


def test_attach_refuses_any_post_t1_timeline_evidence_id() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    governor.ingest(_evidence("EV-T3-01"))

    with pytest.raises(ValueError, match="T2 evidence already ingested"):
        attach_preregistered_chains(
            governor, track_a=track_a, control=control, t2_artifact_refs=frozenset()
        )

    assert governor.state().semantic.derivations == ()


def test_attach_allows_t1_versions_of_a_t2_artifact_ref() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    governor.ingest(_evidence("EV-T1-02", artifact_ref=SPEC_REF))

    events = attach_preregistered_chains(
        governor, track_a=track_a, control=control, t2_artifact_refs=frozenset({SPEC_REF})
    )

    assert len(events) == 5
    assert len(governor.state().semantic.derivations) == 5


def test_attach_refuses_reattachment() -> None:
    store = InMemoryEventStore()
    governor, addr_a, addr_n = _t1_state(store)
    track_a, control = _designations(governor, addr_a, addr_n)
    attach_preregistered_chains(
        governor, track_a=track_a, control=control, t2_artifact_refs=frozenset()
    )
    before = store.current_sequence(PROJECT)

    with pytest.raises(ValueError, match="already attached"):
        attach_preregistered_chains(
            governor, track_a=track_a, control=control, t2_artifact_refs=frozenset()
        )

    assert store.current_sequence(PROJECT) == before
    assert len(governor.state().semantic.derivations) == 5

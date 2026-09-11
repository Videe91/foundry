"""Derivation traversal and supersession blast radius (plan §7; spec §19.1, §22).

Test M drives the real event path: hand-built ``StoredEvent`` sequences reduced by
``reduce_semantic_event``. The lock under test: superseding an admitted basis marks
every transitive descendant STALE in the CURRENT VIEW while history stays untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime

from foundry.application.semantic_reducer import reduce_semantic_event
from foundry.domain.common import SourceKind
from foundry.domain.derivation import DerivationEdge, descendants, stale_object_ids
from foundry.domain.events import (
    DerivationPayload,
    EventEnvelope,
    EventPayload,
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
)
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    CreateAddressProposal,
    EquivalentProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_state import SemanticState
from foundry.domain.semantic_view import active_judgment_ids, derive_view

PROJECT = "PROJ-D"
OCCURRED_AT = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")


def _edge(child: str, parent: str, event_id: str = "EVT-x") -> DerivationEdge:
    return DerivationEdge(child_id=child, parent_id=parent, recorded_by_event_id=event_id)


# --- pure descendants() -----------------------------------------------------------


def test_descendants_empty_roots_is_empty() -> None:
    edges = (_edge("D1", "J1"), _edge("D2", "D1"))
    assert descendants(edges, ()) == frozenset()


def test_descendants_unknown_root_is_empty() -> None:
    edges = (_edge("D1", "J1"),)
    assert descendants(edges, ("J-nope",)) == frozenset()


def test_descendants_no_edges_is_empty() -> None:
    assert descendants((), ("J1",)) == frozenset()


def test_descendants_excludes_roots_and_is_transitive() -> None:
    edges = (_edge("D1", "J1"), _edge("D2", "D1"), _edge("D3", "D2"))
    result = descendants(edges, ("J1",))
    assert result == frozenset({"D1", "D2", "D3"})
    assert "J1" not in result


def test_descendants_diamond_visits_each_node_once() -> None:
    edges = (_edge("B", "A"), _edge("C", "A"), _edge("D", "B"), _edge("D", "C"), _edge("E", "D"))
    assert descendants(edges, ("A",)) == frozenset({"B", "C", "D", "E"})


def test_descendants_cycle_terminates() -> None:
    edges = (_edge("X", "J1"), _edge("Y", "X"), _edge("X", "Y"))
    assert descendants(edges, ("J1",)) == frozenset({"X", "Y"})


def test_descendants_cycle_through_root_does_not_include_root() -> None:
    edges = (_edge("X", "J1"), _edge("J1", "X"))
    assert descendants(edges, ("J1",)) == frozenset({"X"})


def test_descendants_multiple_roots_union() -> None:
    edges = (_edge("D1", "J1"), _edge("D9", "J2"))
    assert descendants(edges, ("J1", "J2")) == frozenset({"D1", "D9"})


def test_descendants_is_deterministic_regardless_of_edge_order() -> None:
    edges = [_edge("D1", "J1"), _edge("D2", "D1"), _edge("D3", "D2"), _edge("D9", "J2")]
    forward = descendants(edges, ("J1",))
    backward = descendants(tuple(reversed(edges)), ("J1",))
    assert forward == backward == frozenset({"D1", "D2", "D3"})


def test_descendants_does_not_mutate_inputs() -> None:
    edges = (_edge("D1", "J1"),)
    roots = ["J1"]
    descendants(edges, roots)
    assert roots == ["J1"]
    assert edges == (_edge("D1", "J1"),)


# --- Test M: reducer-driven blast radius --------------------------------------------


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


def _judgment(judgment_id: str, proposal: JudgmentProposal) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=("EV-1",),
        rationale="EV-1 states a retention obligation for audit records.",
        reasoner=MODEL_A,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=OCCURRED_AT,
    )


def _create(judgment_id: str, candidate_id: str) -> SemanticJudgment:
    return _judgment(judgment_id, CreateAddressProposal(candidate=_candidate(candidate_id)))


def _equivalent(judgment_id: str, a: str, b: str) -> SemanticJudgment:
    return _judgment(judgment_id, EquivalentProposal(address_a=a, address_b=b))


def _supersede(judgment_id: str, target: str) -> SemanticJudgment:
    return _judgment(
        judgment_id, SupersedeProposal(target_judgment_id=target, reason="later evidence")
    )


class Ledger:
    """Hand-built event sequence reduced directly through ``reduce_semantic_event``."""

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

    def reduce(self) -> SemanticState:
        state = SemanticState()
        for stored in self.events:
            state = reduce_semantic_event(state, stored)
        return state


def _address_id(state: SemanticState, judgment_id: str) -> str:
    return next(
        address_id
        for address_id, address in state.addresses.items()
        if address.created_by_judgment_id == judgment_id
    )


def _ledger_with_chain() -> Ledger:
    """J1 (EQUIVALENT, applied) -> D1 -> D2 -> D3; J2 (applied) -> D9; cycle Dx <-> Dy under J1."""
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.apply(_create("J-c1", "CAND-1"))
    ledger.apply(_create("J-c2", "CAND-2"))
    ledger.apply(_create("J-c3", "CAND-3"))
    state = ledger.reduce()
    addr_1 = _address_id(state, "J-c1")
    addr_2 = _address_id(state, "J-c2")
    addr_3 = _address_id(state, "J-c3")
    ledger.apply(_equivalent("J1", addr_1, addr_2))
    ledger.apply(_equivalent("J2", addr_2, addr_3))
    ledger.derive("D1", "J1")
    ledger.derive("D2", "D1")
    ledger.derive("D3", "D2")
    ledger.derive("D9", "J2")
    ledger.derive("Dx", "J1")
    ledger.derive("Dy", "Dx")
    ledger.derive("Dx", "Dy")
    return ledger


def test_m_nothing_is_stale_before_supersession() -> None:
    state = _ledger_with_chain().reduce()

    assert {"J1", "J2"} <= active_judgment_ids(state)
    assert stale_object_ids(state, active_judgment_ids(state)) == frozenset()
    assert derive_view(state).stale_ids == ()


def test_m_supersession_marks_three_level_chain_stale_in_current_view() -> None:
    ledger = _ledger_with_chain()
    ledger.apply(_supersede("J-s1", "J1"))

    state = ledger.reduce()
    active = active_judgment_ids(state)
    stale = stale_object_ids(state, active)
    view = derive_view(state)

    assert "J1" not in active
    assert {"D1", "D2", "D3"} <= stale
    assert "J1" not in stale  # the root basis is superseded, not derived
    assert view.stale_ids == tuple(sorted(stale))
    assert {"D1", "D2", "D3"} <= set(view.stale_ids)


def test_m_unrelated_chain_under_active_judgment_stays_clean() -> None:
    ledger = _ledger_with_chain()
    ledger.apply(_supersede("J-s1", "J1"))

    state = ledger.reduce()
    stale = stale_object_ids(state, active_judgment_ids(state))

    assert "J2" in active_judgment_ids(state)
    assert "D9" not in stale
    assert "J2" not in stale
    assert "J-s1" not in stale


def test_m_cycle_under_superseded_judgment_terminates_and_is_stale() -> None:
    ledger = _ledger_with_chain()
    ledger.apply(_supersede("J-s1", "J1"))

    state = ledger.reduce()
    stale = stale_object_ids(state, active_judgment_ids(state))

    assert {"Dx", "Dy"} <= stale


def test_m_historical_derivation_edges_are_untouched_by_supersession() -> None:
    ledger = _ledger_with_chain()
    before = ledger.reduce()
    ledger.apply(_supersede("J-s1", "J1"))
    after = ledger.reduce()

    assert after.derivations == before.derivations
    assert [edge.model_dump() for edge in after.derivations] == [
        edge.model_dump() for edge in before.derivations
    ]
    assert "J1" in after.judgments
    assert "J1" in after.applied_judgment_ids
    assert set(before.issue_versions) <= set(after.issue_versions)


def test_m_superseding_the_superseder_restores_the_chain() -> None:
    ledger = _ledger_with_chain()
    ledger.apply(_supersede("J-s1", "J1"))
    ledger.apply(_supersede("J-s2", "J-s1"))

    state = ledger.reduce()
    active = active_judgment_ids(state)
    stale = stale_object_ids(state, active)

    assert "J1" in active
    assert "J-s1" not in active
    assert not {"D1", "D2", "D3", "Dx", "Dy"} & stale
    # only the versions minted by the now-inactive superseder J-s1 remain stale
    j_s1_versions = {
        version_id
        for version_id, version in state.issue_versions.items()
        if version.created_by_judgment_id == "J-s1"
    }
    assert j_s1_versions
    assert stale == j_s1_versions
    assert derive_view(state).stale_ids == tuple(sorted(j_s1_versions))


def test_m_stale_object_ids_is_pure() -> None:
    ledger = _ledger_with_chain()
    ledger.apply(_supersede("J-s1", "J1"))
    state = ledger.reduce()
    snapshot = state.model_dump()

    first = stale_object_ids(state, active_judgment_ids(state))
    second = stale_object_ids(state, active_judgment_ids(state))

    assert first == second
    assert state.model_dump() == snapshot


def test_view_stale_ids_is_sorted_and_deterministic_across_replays() -> None:
    ledger = _ledger_with_chain()
    ledger.apply(_supersede("J-s1", "J1"))

    view_a = derive_view(ledger.reduce())
    view_b = derive_view(ledger.reduce())

    assert view_a.stale_ids == view_b.stale_ids == tuple(sorted(view_a.stale_ids))


# --- version-level roots: derivations hung off issue VERSIONS ---------------------------


def _versions_by_judgment(state: SemanticState, judgment_id: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            version_id
            for version_id, version in state.issue_versions.items()
            if version.created_by_judgment_id == judgment_id
        )
    )


def _ledger_with_version_chain() -> tuple[Ledger, str, str]:
    """V1 (minted by J1's admission) -> VD1 -> VD2; V2 (minted by J2's admission) -> VD9."""
    ledger = _ledger_with_chain()
    state = ledger.reduce()
    v1 = _versions_by_judgment(state, "J1")[0]
    v2 = _versions_by_judgment(state, "J2")[0]
    ledger.derive("VD1", v1)
    ledger.derive("VD2", "VD1")
    ledger.derive("VD9", v2)
    return ledger, v1, v2


def test_minted_versions_carry_the_admitted_judgment_id() -> None:
    state = _ledger_with_chain().reduce()

    j1_versions = _versions_by_judgment(state, "J1")
    assert len(j1_versions) == 2  # EQUIVALENT touches both addresses
    for version_id in j1_versions:
        assert state.issue_versions[version_id].created_by_judgment_id == "J1"
    assert all(v.created_by_judgment_id for v in state.issue_versions.values())


def test_version_chain_is_clean_while_creating_judgment_is_active() -> None:
    ledger, v1, v2 = _ledger_with_version_chain()
    state = ledger.reduce()

    stale = stale_object_ids(state, active_judgment_ids(state))

    assert stale == frozenset()
    assert v1 not in stale
    assert v2 not in stale


def test_versions_minted_by_superseded_judgment_and_their_descendants_are_stale() -> None:
    ledger, v1, v2 = _ledger_with_version_chain()
    ledger.apply(_supersede("J-s1", "J1"))
    state = ledger.reduce()

    stale = stale_object_ids(state, active_judgment_ids(state))
    view = derive_view(state)

    # versions minted by a superseded judgment are stale objects themselves
    assert set(_versions_by_judgment(state, "J1")) <= stale
    assert v1 in stale
    assert {"VD1", "VD2"} <= stale
    # the judgment-rooted chain is still stale too
    assert {"D1", "D2", "D3", "Dx", "Dy"} <= stale
    assert set(view.stale_ids) == stale


def test_versions_minted_by_active_judgments_stay_clean() -> None:
    ledger, v1, v2 = _ledger_with_version_chain()
    ledger.apply(_supersede("J-s1", "J1"))
    state = ledger.reduce()

    stale = stale_object_ids(state, active_judgment_ids(state))

    assert v2 not in stale
    assert "VD9" not in stale
    # versions minted by the SUPERSEDE application belong to the (active) superseder
    for version_id in _versions_by_judgment(state, "J-s1"):
        assert version_id not in stale
        assert state.issue_versions[version_id].created_by_judgment_id == "J-s1"
    assert not set(_versions_by_judgment(state, "J-c1")) & stale


def test_superseding_the_superseder_restores_version_chain() -> None:
    ledger, v1, v2 = _ledger_with_version_chain()
    ledger.apply(_supersede("J-s1", "J1"))
    ledger.apply(_supersede("J-s2", "J-s1"))
    state = ledger.reduce()

    stale = stale_object_ids(state, active_judgment_ids(state))

    assert v1 not in stale
    assert not {"VD1", "VD2"} & stale
    # J-s1 is now inactive: the versions ITS application minted are stale
    assert set(_versions_by_judgment(state, "J-s1")) <= stale

"""Scoped Intent -> Decision handoff tests (plan §8.2, §8.3 N/O; spec §17.1, §25.1).

States are produced by replaying a hand-built ledger so issue versions, heads and
stale ids are the reducer's own, not hand-typed approximations.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from foundry.application.handoff import build_intent_decision_handoff
from foundry.application.replay import replay
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    SourceKind,
)
from foundry.domain.events import (
    DerivationPayload,
    EventEnvelope,
    EventPayload,
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    SemanticObjectPayload,
    StoredEvent,
)
from foundry.domain.evidence import evidence_item
from foundry.domain.handoff import (
    HANDOFF_VERSION,
    IntentDecisionHandoff,
    SemanticReadiness,
    build_semantic_readiness,
)
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
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState

PROJECT = "PROJ-HANDOFF"
OCCURRED_AT = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")
PROVENANCE = Provenance(source_kind=SourceKind.HUMAN, source_ref="human://owner")
RATIONALE_MARKER = "RATIONALE-MARKER-must-never-leak-into-a-handoff"

ADDR_A = address_id_for(PROJECT, "J-cA")
ADDR_B = address_id_for(PROJECT, "J-cB")
ADDR_P = address_id_for(PROJECT, "J-cP")


# --- builders ---------------------------------------------------------------------


def _candidate(candidate_id: str, scope: tuple[str, ...], evidence_id: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject="records",
        facet="retention",
        scope=scope,
        evidence_ids=(evidence_id,),
    )


def _judgment(judgment_id: str, proposal: JudgmentProposal, evidence_id: str) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"{RATIONALE_MARKER} for {judgment_id}",
        reasoner=MODEL_A,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=OCCURRED_AT,
    )


def _create(judgment_id: str, scope: tuple[str, ...], evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(candidate=_candidate(f"CAND-{judgment_id}", scope, evidence_id)),
        evidence_id,
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
        evidence_id,
    )


def _intent(object_id: str, scope: tuple[str, ...]) -> Intent:
    return Intent(
        id=object_id,
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=OCCURRED_AT,
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
        created_at=OCCURRED_AT,
        scope=scope,
        statement=f"Requirement for {scope}",
        materiality=Materiality.HIGH,
        requires_metric=True,
        metric_exempt_reason="Qualitative obligation.",
        requires_verification=True,
        verification_exempt_reason="Verified by inspection.",
    )


def _authority(
    object_id: str,
    scope: tuple[str, ...],
    *,
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE,
    authority: Authority = Authority.CANONICAL,
) -> AuthorityRecord:
    return AuthorityRecord(
        id=object_id,
        project_id=PROJECT,
        authority=authority,
        lifecycle=lifecycle,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=OCCURRED_AT,
        scope=scope,
        subject_id="records",
        authorized_by="human://alice",
        rationale=f"{RATIONALE_MARKER} authority {object_id}",
    )


class Ledger:
    def __init__(self) -> None:
        self.events: list[StoredEvent] = []

    def append(self, event_type: EventType, payload: EventPayload) -> StoredEvent:
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

    def ingest(self, evidence_id: str) -> None:
        self.append(
            EventType.EVIDENCE_INGESTED,
            EvidencePayload(
                evidence=evidence_item(
                    evidence_id=evidence_id,
                    project_id=PROJECT,
                    source_kind=SourceKind.DOCUMENT,
                    source_ref=f"doc://{evidence_id}",
                    content=f"{RATIONALE_MARKER} evidence body {evidence_id}",
                    observed_at=OCCURRED_AT,
                )
            ),
        )

    def apply(self, judgment: SemanticJudgment) -> StoredEvent:
        self.append(
            EventType.SEMANTIC_JUDGMENT_RECORDED, SemanticJudgmentPayload(judgment=judgment)
        )
        return self.append(
            EventType.SEMANTIC_ADMISSION_DECIDED,
            SemanticAdmissionPayload(
                judgment_id=judgment.judgment_id, route=AdmissionRoute.APPLY, reasons=("TEST",)
            ),
        )

    def derive(self, child_id: str, parent_id: str) -> None:
        self.append(
            EventType.DERIVATION_RECORDED, DerivationPayload(child_id=child_id, parent_id=parent_id)
        )

    def replay(self) -> IntentState:
        return replay(PROJECT, self.events)


def _story() -> Ledger:
    """Scope A: closed, one CLAIMED locus. Scope B: closed, one DISPUTED locus.

    A project-wide locus (scope ``()``) and a project-wide authority record are
    visible from both. A carries one superseded (bind) judgment.
    """
    ledger = Ledger()
    for evidence_id in ("EV-A", "EV-B", "EV-P"):
        ledger.ingest(evidence_id)
    ledger.apply(_create("J-cA", ("A",), "EV-A"))
    ledger.apply(_create("J-cB", ("B",), "EV-B"))
    ledger.apply(_create("J-cP", (), "EV-P"))
    ledger.apply(_claim("J-clA", ADDR_A, "EV-A", "7"))
    ledger.apply(_claim("J-clB1", ADDR_B, "EV-B", "30"))
    ledger.apply(_claim("J-clB2", ADDR_B, "EV-B", "45"))
    ledger.apply(
        _judgment(
            "J-cfB",
            ConflictsWithProposal(
                claim_a=claim_id_for(PROJECT, "J-clB1"), claim_b=claim_id_for(PROJECT, "J-clB2")
            ),
            "EV-B",
        )
    )
    ledger.apply(_claim("J-clP", ADDR_P, "EV-P", "1"))
    ledger.apply(
        _judgment(
            "J-bA",
            BindToAddressProposal(
                candidate=_candidate("CAND-A2", ("A",), "EV-A"), address_id=ADDR_A
            ),
            "EV-A",
        )
    )
    ledger.apply(
        _judgment(
            "J-supA",
            SupersedeProposal(target_judgment_id="J-bA", reason="candidate was misbound"),
            "EV-A",
        )
    )
    for obj in (
        _intent("INTENT-A", ("A",)),
        _intent("INTENT-B", ("B",)),
        _authority("AUTH-A", ("A",)),
        _authority("AUTH-B", ("B",)),
        _authority("AUTH-P", ()),
        _authority("AUTH-OLD-A", ("A",), lifecycle=LifecycleStatus.SUPERSEDED),
        _authority("AUTH-REJECTED-A", ("A",), authority=Authority.REJECTED),
        _authority("AUTH-SUPERSEDED-P", (), authority=Authority.SUPERSEDED),
    ):
        ledger.append(EventType.SEMANTIC_OBJECT_RECORDED, SemanticObjectPayload(object=obj))
    for requirement in (_requirement("REQ-A", ("A",)), _requirement("REQ-B", ("B",))):
        ledger.append(
            EventType.REQUIREMENT_CANONICALIZED, SemanticObjectPayload(object=requirement)
        )
    return ledger


def _handoffs() -> tuple[IntentState, IntentDecisionHandoff, IntentDecisionHandoff]:
    state = _story().replay()
    handoff_a = build_intent_decision_handoff(state, "A")
    handoff_b = build_intent_decision_handoff(state, "B")
    return state, handoff_a, handoff_b


# --- N: readiness is scoped --------------------------------------------------------


def test_n_scope_a_is_ready_while_scope_b_is_blocked_by_its_dispute() -> None:
    _, handoff_a, handoff_b = _handoffs()

    assert handoff_a.readiness.ready is True
    assert handoff_a.readiness.closure.closed is True
    assert handoff_a.readiness.closure.scope == "A"
    assert handoff_a.readiness.disputed_locus_ids == ()
    assert handoff_a.readiness.stale_object_ids == ()
    assert handoff_a.readiness.open_locus_ids == ()

    assert handoff_b.readiness.ready is False
    assert handoff_b.readiness.closure.closed is True  # blocked by the dispute alone
    assert handoff_b.readiness.disputed_locus_ids == (ADDR_B,)


def test_n_closure_failure_alone_blocks_readiness() -> None:
    ledger = _story()
    ledger.ingest("EV-C")
    ledger.apply(_create("J-cC", ("C",), "EV-C"))
    state = ledger.replay()

    handoff = build_intent_decision_handoff(state, "C")

    assert handoff.readiness.ready is False
    assert handoff.readiness.closure.closed is False
    assert handoff.readiness.disputed_locus_ids == ()
    assert handoff.readiness.open_locus_ids == (address_id_for(PROJECT, "J-cC"),)
    codes = {blocker.code for blocker in handoff.readiness.closure.blockers}
    assert "MISSING_CANONICAL_INTENT" in codes


# --- O: the handoff carries only in-scope ids ----------------------------------------


def test_o_scope_a_carries_only_a_and_project_wide_loci_claims_and_evidence() -> None:
    state, handoff_a, _ = _handoffs()

    assert [locus.representative_id for locus in handoff_a.loci] == sorted((ADDR_A, ADDR_P))
    assert {locus.epistemic_state for locus in handoff_a.loci} == {IssueEpistemicState.CLAIMED}
    assert handoff_a.claim_ids == tuple(
        sorted((claim_id_for(PROJECT, "J-clA"), claim_id_for(PROJECT, "J-clP")))
    )
    assert handoff_a.evidence_ids == ("EV-A", "EV-P")
    assert handoff_a.authority_record_ids == ("AUTH-A", "AUTH-P")
    assert handoff_a.superseded_judgment_ids == ("J-bA",)

    forbidden = {
        ADDR_B,
        claim_id_for(PROJECT, "J-clB1"),
        claim_id_for(PROJECT, "J-clB2"),
        "EV-B",
        "AUTH-B",
        "AUTH-OLD-A",
        "AUTH-REJECTED-A",
        "AUTH-SUPERSEDED-P",
        "J-cfB",
    }
    assert not any(token in handoff_a.model_dump_json() for token in forbidden)


def test_o_project_wide_locus_and_authority_appear_in_both_scopes() -> None:
    _, handoff_a, handoff_b = _handoffs()

    assert ADDR_P in {locus.representative_id for locus in handoff_a.loci}
    assert ADDR_P in {locus.representative_id for locus in handoff_b.loci}
    assert "AUTH-P" in handoff_a.authority_record_ids
    assert "AUTH-P" in handoff_b.authority_record_ids
    assert handoff_b.authority_record_ids == ("AUTH-B", "AUTH-P")
    assert [locus.representative_id for locus in handoff_b.loci] == sorted((ADDR_B, ADDR_P))
    assert handoff_b.superseded_judgment_ids == ()


def test_handoff_identity_fields_point_at_the_replayed_state() -> None:
    state, handoff_a, handoff_b = _handoffs()

    assert handoff_a.handoff_version == HANDOFF_VERSION == "intent-decision-handoff-v1"
    assert handoff_a.project_id == PROJECT
    assert handoff_a.scope == "A"
    assert handoff_b.scope == "B"
    assert handoff_a.semantic_state_revision == state.revision == len(_story().events)
    assert handoff_a.stale_object_ids == handoff_a.readiness.stale_object_ids


def test_handoff_serializes_to_json_and_carries_no_rationale_or_evidence_content() -> None:
    _, handoff_a, handoff_b = _handoffs()

    for handoff in (handoff_a, handoff_b):
        document = json.loads(handoff.model_dump_json())
        assert document["handoff_version"] == HANDOFF_VERSION
        assert RATIONALE_MARKER not in handoff.model_dump_json()
        assert "evidence body" not in handoff.model_dump_json()
        assert IntentDecisionHandoff.model_validate(document) == handoff


# --- stale ids are attributed to a scope through in-scope issue versions -------------


def _superseded_claim_story() -> tuple[Ledger, str]:
    ledger = _story()
    admitted = ledger.apply(_claim("J-cl2A", ADDR_A, "EV-A", "8"))
    stale_version_id = f"{admitted.event.event_id}:{ADDR_A}"
    ledger.apply(
        _judgment(
            "J-sup2A",
            SupersedeProposal(target_judgment_id="J-cl2A", reason="duplicate observation"),
            "EV-A",
        )
    )
    return ledger, stale_version_id


def test_superseded_non_head_version_is_history_and_does_not_block_readiness() -> None:
    ledger, stale_version_id = _superseded_claim_story()
    state = ledger.replay()

    view = derive_view(state.semantic)
    assert stale_version_id in view.stale_ids
    assert state.semantic.issue_heads[ADDR_A] != stale_version_id

    handoff = build_intent_decision_handoff(state, "A")
    assert handoff.stale_object_ids == ()
    assert handoff.readiness.ready is True
    assert handoff.superseded_judgment_ids == ("J-bA", "J-cl2A")


def test_objects_derived_from_an_in_scope_version_or_judgment_are_stale_in_that_scope_only() -> (
    None
):
    ledger, stale_version_id = _superseded_claim_story()
    ledger.derive("D-vA", stale_version_id)
    ledger.derive("D-vA2", "D-vA")
    ledger.derive("D-jA", "J-cl2A")
    ledger.derive("D-jA2", "D-jA")
    ledger.derive("D-jA3", "D-jA2")
    state = ledger.replay()

    view = derive_view(state.semantic)
    assert {"D-vA", "D-vA2", "D-jA", "D-jA2", "D-jA3"} <= set(view.stale_ids)

    handoff_a = build_intent_decision_handoff(state, "A")
    handoff_b = build_intent_decision_handoff(state, "B")
    assert handoff_a.stale_object_ids == ("D-jA", "D-jA2", "D-jA3", "D-vA", "D-vA2")
    assert handoff_a.readiness.ready is False
    assert handoff_a.readiness.closure.closed is True
    assert stale_version_id not in handoff_a.stale_object_ids  # history, never blocks
    assert handoff_b.stale_object_ids == ()
    assert handoff_b.readiness.stale_object_ids == ()


def test_superseded_supersession_attributes_stale_descendants_recursively() -> None:
    """A SUPERSEDE bears on its target's addresses; superseding the superseder restores
    the target and makes anything derived from the first supersession stale in scope A."""
    ledger, _ = _superseded_claim_story()
    ledger.derive("D-sup", "J-sup2A")
    ledger.apply(
        _judgment(
            "J-sup3A",
            SupersedeProposal(target_judgment_id="J-sup2A", reason="the observation stands"),
            "EV-A",
        )
    )
    state = ledger.replay()

    assert "D-sup" in derive_view(state.semantic).stale_ids
    handoff_a = build_intent_decision_handoff(state, "A")
    handoff_b = build_intent_decision_handoff(state, "B")
    assert handoff_a.stale_object_ids == ("D-sup",)
    assert handoff_a.readiness.ready is False
    assert handoff_b.stale_object_ids == ()


# --- pure readiness builder ---------------------------------------------------------


def test_build_semantic_readiness_is_pure_over_state_view_and_scope() -> None:
    state = _story().replay()
    view = derive_view(state.semantic)
    in_scope = tuple(locus for locus in view.loci if locus.scope == () or "B" in locus.scope)

    readiness = build_semantic_readiness(state, view, "B", in_scope)

    assert isinstance(readiness, SemanticReadiness)
    assert readiness.closure.scope == "B"
    assert readiness.disputed_locus_ids == (ADDR_B,)
    assert readiness.open_locus_ids == ()
    assert readiness.stale_object_ids == ()
    assert readiness.ready is False
    assert build_semantic_readiness(state, view, "B", in_scope) == readiness

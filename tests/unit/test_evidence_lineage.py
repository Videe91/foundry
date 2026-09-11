"""Evidence version lineage (spec §15, §16; plan Task 1).

Two versions of one artifact are two immutable ``EvidenceItem``s linked by
``artifact_ref`` / ``supersedes_evidence_id``. Lineage is deterministic data
carrying no semantic authority: the view derives which evidence versions are
current, and NOTHING about claims, loci or epistemic state may move because of it.

Events are hand-built ``StoredEvent`` sequences (same shape as
``tests/unit/test_semantic_reducer.py``).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from foundry.application.replay import replay
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
from foundry.domain.evidence import DigRecord, EvidenceItem, evidence_from_dig, evidence_item
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
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState

PROJECT = "PROJ-1"
T0 = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")
DESIGN_DOC = "repo:docs/design.md"
OTHER_DOC = "repo:docs/other.md"


def _digest(judgment_id: str) -> str:
    return hashlib.sha256(f"{PROJECT}|{judgment_id}".encode()).hexdigest()[:16]


def address_id_for(judgment_id: str) -> str:
    return "ADDR-" + _digest(judgment_id)


def claim_id_for(judgment_id: str) -> str:
    return "CLAIM-" + _digest(judgment_id)


def _evidence(
    evidence_id: str,
    *,
    artifact_ref: str | None = None,
    supersedes_evidence_id: str | None = None,
    content: str | None = None,
) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"git://commit-{evidence_id}/docs/design.md",
        content=content or f"Version {evidence_id}: audit records are retained.",
        observed_at=T0,
        artifact_ref=artifact_ref,
        supersedes_evidence_id=supersedes_evidence_id,
    )


def _candidate(candidate_id: str, evidence_ids: tuple[str, ...]) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject="audit records",
        facet="retention period",
        scope=("compliance",),
        evidence_ids=evidence_ids,
    )


def _judgment(
    judgment_id: str, proposal: JudgmentProposal, visible: tuple[str, ...]
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=visible,
        rationale="The cited evidence states a retention obligation for audit records.",
        reasoner=MODEL_A,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _create(judgment_id: str, candidate_id: str, evidence_ids: tuple[str, ...]) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(candidate=_candidate(candidate_id, evidence_ids)),
        evidence_ids,
    )


def _assert_claim(
    judgment_id: str, address_id: str, evidence_ids: tuple[str, ...]
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
            evidence_ids=evidence_ids,
            authority=Authority.OBSERVED,
        ),
        evidence_ids,
    )


class Ledger:
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

    def ingest(self, item: EvidenceItem) -> StoredEvent:
        return self._append(EventType.EVIDENCE_INGESTED, EvidencePayload(evidence=item))

    def apply(self, judgment: SemanticJudgment) -> StoredEvent:
        self._append(
            EventType.SEMANTIC_JUDGMENT_RECORDED, SemanticJudgmentPayload(judgment=judgment)
        )
        return self._append(
            EventType.SEMANTIC_ADMISSION_DECIDED,
            SemanticAdmissionPayload(
                judgment_id=judgment.judgment_id, route=AdmissionRoute.APPLY, reasons=("TEST",)
            ),
        )

    def replay(self) -> IntentState:
        return replay(PROJECT, self.events)


def _round_trip(events: list[StoredEvent]) -> list[StoredEvent]:
    return [
        StoredEvent(sequence=s.sequence, event=parse_event(s.event.model_dump(mode="json")))
        for s in events
    ]


# --- domain shape -------------------------------------------------------------------


def test_lineage_fields_default_to_none_keeping_existing_construction_compatible() -> None:
    item = evidence_item(
        evidence_id="EV-1",
        project_id=PROJECT,
        source_kind=SourceKind.HUMAN,
        source_ref="human://alice",
        content="Retries must be three.",
        observed_at=T0,
    )
    assert item.artifact_ref is None
    assert item.supersedes_evidence_id is None

    explicit = EvidenceItem(
        evidence_id="EV-2",
        project_id=PROJECT,
        source_kind=SourceKind.CODE,
        source_ref="repo://svc/x.py#L1-L9",
        content="def x(): ...",
        content_sha256=hashlib.sha256(b"def x(): ...").hexdigest(),
        observed_at=T0,
    )
    assert explicit.artifact_ref is None
    assert explicit.supersedes_evidence_id is None

    versioned = _evidence("EV-3", artifact_ref=DESIGN_DOC)
    assert versioned.artifact_ref == DESIGN_DOC
    assert versioned.supersedes_evidence_id is None


def test_supersedes_requires_artifact_ref() -> None:
    with pytest.raises(ValidationError, match="artifact_ref"):
        _evidence("EV-2", supersedes_evidence_id="EV-1")


def test_evidence_cannot_supersede_itself() -> None:
    with pytest.raises(ValidationError, match="itself"):
        _evidence("EV-1", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1")


def test_dig_record_forwards_artifact_ref() -> None:
    record = DigRecord(
        locator="git://abc123/docs/design.md",
        kind=SourceKind.DOCUMENT,
        content="Audit records are retained for seven years.",
        observed_at=T0,
        artifact_ref=DESIGN_DOC,
    )
    item = evidence_from_dig(record, project_id=PROJECT, evidence_id="EV-9")
    assert item.artifact_ref == DESIGN_DOC
    assert item.supersedes_evidence_id is None

    plain = DigRecord(
        locator="ticket://PROJ-12",
        kind=SourceKind.TICKET,
        content="Retry policy: three attempts.",
        observed_at=T0,
    )
    assert plain.artifact_ref is None
    assert evidence_from_dig(plain, project_id=PROJECT, evidence_id="EV-10").artifact_ref is None


# --- reducer: state-aware lineage checks ------------------------------------------


def test_reducer_refuses_lineage_to_unknown_evidence() -> None:
    ledger = Ledger()
    ledger.ingest(_evidence("EV-2", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1"))

    with pytest.raises(ValueError, match="unknown"):
        ledger.replay()


def test_reducer_refuses_lineage_across_artifacts() -> None:
    ledger = Ledger()
    ledger.ingest(_evidence("EV-1", artifact_ref=OTHER_DOC))
    ledger.ingest(_evidence("EV-2", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1"))

    with pytest.raises(ValueError, match="artifact_ref"):
        ledger.replay()


def test_reducer_refuses_lineage_to_evidence_without_artifact_ref() -> None:
    ledger = Ledger()
    ledger.ingest(_evidence("EV-1"))
    ledger.ingest(_evidence("EV-2", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1"))

    with pytest.raises(ValueError, match="artifact_ref"):
        ledger.replay()


def test_reducer_refuses_second_successor_of_same_version() -> None:
    ledger = Ledger()
    ledger.ingest(_evidence("EV-1", artifact_ref=DESIGN_DOC))
    ledger.ingest(_evidence("EV-2", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1"))
    ledger.ingest(_evidence("EV-3", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1"))

    with pytest.raises(ValueError, match="already superseded"):
        ledger.replay()


def test_reducer_accepts_linear_chain_and_keeps_every_version() -> None:
    ledger = Ledger()
    ledger.ingest(_evidence("EV-1", artifact_ref=DESIGN_DOC))
    ledger.ingest(_evidence("EV-2", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1"))
    ledger.ingest(_evidence("EV-3", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-2"))

    semantic = ledger.replay().semantic

    assert set(semantic.evidence) == {"EV-1", "EV-2", "EV-3"}
    assert semantic.evidence["EV-1"].supersedes_evidence_id is None
    assert semantic.evidence["EV-2"].supersedes_evidence_id == "EV-1"
    assert semantic.evidence["EV-3"].supersedes_evidence_id == "EV-2"


def test_duplicate_evidence_id_still_raises_with_lineage() -> None:
    ledger = Ledger()
    ledger.ingest(_evidence("EV-1", artifact_ref=DESIGN_DOC))
    ledger.ingest(_evidence("EV-1", artifact_ref=DESIGN_DOC))

    with pytest.raises(ValueError, match="EV-1"):
        ledger.replay()


# --- view: pure lineage derivation --------------------------------------------------


def test_view_derives_current_and_superseded_evidence_versions() -> None:
    ledger = Ledger()
    ledger.ingest(_evidence("EV-1", artifact_ref=DESIGN_DOC))
    ledger.ingest(_evidence("EV-2", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1"))
    ledger.ingest(_evidence("EV-3", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-2"))
    ledger.ingest(_evidence("EV-4", artifact_ref=OTHER_DOC))
    ledger.ingest(_evidence("EV-0"))  # unversioned evidence is current too

    view = derive_view(ledger.replay().semantic)

    assert view.current_evidence_ids == ("EV-0", "EV-3", "EV-4")
    assert view.superseded_evidence_ids == ("EV-1", "EV-2")


def test_view_lineage_fields_default_empty() -> None:
    ledger = Ledger()
    view = derive_view(ledger.replay().semantic)
    assert view.current_evidence_ids == ()
    assert view.superseded_evidence_ids == ()


def test_lineage_never_changes_claims_or_judgments() -> None:
    # §16: a claim citing a superseded evidence version is not superseded, not flagged.
    ledger = Ledger()
    ledger.ingest(_evidence("EV-1", artifact_ref=DESIGN_DOC))
    ledger.apply(_create("J-c1", "CAND-1", ("EV-1",)))
    address_id = address_id_for("J-c1")
    ledger.apply(_assert_claim("J-a1", address_id, ("EV-1",)))

    before_state = ledger.replay()
    before_view = derive_view(before_state.semantic)

    ledger.ingest(_evidence("EV-2", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1"))

    after_state = ledger.replay()
    after_view = derive_view(after_state.semantic)

    claim_id = claim_id_for("J-a1")
    assert after_view.superseded_evidence_ids == ("EV-1",)
    assert after_view.current_evidence_ids == ("EV-2",)

    # Durable claim untouched, still citing the superseded version.
    assert after_state.semantic.claims[claim_id] == before_state.semantic.claims[claim_id]
    assert after_state.semantic.claims[claim_id].evidence_ids == ("EV-1",)
    assert after_state.semantic.judgments == before_state.semantic.judgments
    assert after_state.semantic.applied_judgment_ids == before_state.semantic.applied_judgment_ids
    assert after_state.semantic.supersessions == before_state.semantic.supersessions
    assert after_state.semantic.conflicts == before_state.semantic.conflicts

    # Claim stays live; locus, epistemic state, bindings and stale ids unchanged.
    assert after_view.loci == before_view.loci
    (locus,) = after_view.loci
    assert locus.claim_ids == (claim_id,)
    assert locus.epistemic_state is IssueEpistemicState.CLAIMED
    assert after_view.representatives == before_view.representatives
    assert after_view.active_bindings == before_view.active_bindings
    assert after_view.active_equivalence_judgment_ids == before_view.active_equivalence_judgment_ids
    assert after_view.active_conflict_judgment_ids == before_view.active_conflict_judgment_ids
    assert after_view.stale_ids == before_view.stale_ids == ()
    assert claim_id not in after_view.stale_ids


# --- replay -------------------------------------------------------------------------


def test_replay_reproduces_lineage() -> None:
    ledger = Ledger()
    ledger.ingest(_evidence("EV-1", artifact_ref=DESIGN_DOC))
    ledger.apply(_create("J-c1", "CAND-1", ("EV-1",)))
    ledger.apply(_assert_claim("J-a1", address_id_for("J-c1"), ("EV-1",)))
    ledger.ingest(_evidence("EV-2", artifact_ref=DESIGN_DOC, supersedes_evidence_id="EV-1"))
    ledger.ingest(_evidence("EV-3", artifact_ref=OTHER_DOC))

    first = replay(PROJECT, ledger.events)
    second = replay(PROJECT, _round_trip(ledger.events))
    third = replay(PROJECT, _round_trip(_round_trip(ledger.events)))

    assert first == second == third
    assert first.semantic.model_dump(mode="json") == second.semantic.model_dump(mode="json")
    assert derive_view(first.semantic) == derive_view(second.semantic)
    assert derive_view(first.semantic) == derive_view(third.semantic)
    assert second.semantic.evidence["EV-2"].artifact_ref == DESIGN_DOC
    assert second.semantic.evidence["EV-2"].supersedes_evidence_id == "EV-1"
    assert derive_view(second.semantic).current_evidence_ids == ("EV-2", "EV-3")
    assert derive_view(second.semantic).superseded_evidence_ids == ("EV-1",)

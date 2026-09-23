"""T7.1 / C23 — a durable synthesis gap that can be honest about what it does not know.

The frozen ``Gap`` requires ``materiality`` and ``risk`` and has no explicit scope.
Neither a deterministic T7 blocker nor a frozen ``GapProposal`` supplies trustworthy
values for those, and inventing ``LOW`` would fabricate a classification nobody made.

``domain/gaps.py`` is a sealed comparative-experiment artifact, so the fix is additive:
a subtype that may say "unknown", carries its own scope, and is first-class enough to be
resolved, waived and read by closure.

Two legacy behaviours are load-bearing and must not move:

* a legacy ``Gap`` must still parse as ``Gap`` — never silently as the subtype;
* ``AMBIGUITY_DETECTED`` must still record **no** gap, because changing it would alter
  the replay of event streams that already exist.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.application.reducer import reduce_event
from foundry.domain.closure import evaluate_closure
from foundry.domain.common import Authority, Materiality, Provenance, RiskLevel, SourceKind
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    GapPayload,
    GapResolvedPayload,
    GapWaivedPayload,
    SemanticObjectPayload,
    StoredEvent,
    UserStatedIntentPayload,
    parse_event,
)
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import Constraint
from foundry.domain.state import IntentState

PROJECT = "PROJ-A"
AT = datetime(2026, 9, 23, tzinfo=UTC)


def _legacy_gap(
    *,
    gap_id: str = "GAP-legacy",
    affected: tuple[str, ...] = (),
    blocking: bool = True,
    status: GapStatus = GapStatus.OPEN,
) -> Gap:
    return Gap(
        id=gap_id,
        project_id=PROJECT,
        kind=GapKind.AMBIGUITY,
        description="a legacy gap",
        materiality=Materiality.LOW,
        risk=RiskLevel.LOW,
        affected_object_ids=affected,
        blocking=blocking,
        status=status,
    )


def _synthesis_gap(
    *,
    gap_id: str = "GAP-syn",
    kind: GapKind = GapKind.CONTRADICTION,
    scope: tuple[str, ...] = ("payments",),
    blocking: bool = True,
    status: GapStatus = GapStatus.OPEN,
    confidence: float | None = None,
    locus_representative_id: str | None = "ADDR-1",
    affected_claim_ids: tuple[str, ...] = ("CLAIM-1",),
    subject_key: str | None = None,
    model_gap_proposal_id: str | None = None,
) -> IntentSynthesisGap:
    return IntentSynthesisGap(
        id=gap_id,
        project_id=PROJECT,
        kind=kind,
        description="a synthesis gap",
        affected_object_ids=(),
        blocking=blocking,
        status=status,
        scope=scope,
        confidence=confidence,
        locus_representative_id=locus_representative_id,
        affected_claim_ids=affected_claim_ids,
        subject_key=subject_key,
        model_gap_proposal_id=model_gap_proposal_id,
    )


def _envelope(event_type: EventType, payload: object, event_id: str = "EVT-1") -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        project_id=PROJECT,
        event_type=event_type,
        occurred_at=AT,
        payload=payload,  # type: ignore[arg-type]
    )


def _reduce(state: IntentState, *events: EventEnvelope) -> IntentState:
    for event in events:
        state = reduce_event(state, StoredEvent(sequence=state.last_sequence + 1, event=event))
    return state


# --- the subtype contract ---------------------------------------------------------------------


def test_materiality_and_risk_may_be_honestly_unknown() -> None:
    """Unknown is not LOW. Inventing a classification nobody made would be a lie."""
    gap = _synthesis_gap()
    assert gap.materiality is None
    assert gap.risk is None
    assert gap.materiality is not Materiality.LOW
    assert gap.risk is not RiskLevel.LOW


def test_a_classified_materiality_and_risk_are_still_expressible() -> None:
    gap = IntentSynthesisGap(
        id="GAP-1",
        project_id=PROJECT,
        kind=GapKind.AMBIGUITY,
        description="d",
        affected_object_ids=(),
        blocking=True,
        materiality=Materiality.HIGH,
        risk=RiskLevel.CRITICAL,
    )
    assert gap.materiality is Materiality.HIGH
    assert gap.risk is RiskLevel.CRITICAL


def test_confidence_is_optional_metadata_and_none_is_not_zero() -> None:
    """The D12 distinction, applied to gaps."""
    assert _synthesis_gap(confidence=None).confidence is None
    assert _synthesis_gap(confidence=0.0).confidence == 0.0
    assert _synthesis_gap(confidence=None) != _synthesis_gap(confidence=0.0)


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_a_confidence_outside_the_unit_interval_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        _synthesis_gap(confidence=value)


def test_the_synthesis_gap_carries_no_model_supplied_provenance() -> None:
    """Model-supplied event ids are never trusted into durable state.

    The synthesis request exposes no event ids at all, so any the model returned would
    be invented. The ``EventEnvelope`` is the ledger provenance.
    """
    assert "source_event_ids" not in IntentSynthesisGap.model_fields


def test_the_model_gap_id_is_metadata_never_the_durable_id() -> None:
    gap = _synthesis_gap(gap_id="GAP-durable", model_gap_proposal_id="g-model-1")
    assert gap.id == "GAP-durable"
    assert gap.model_gap_proposal_id == "g-model-1"
    assert gap.id != gap.model_gap_proposal_id


def test_the_subtype_adds_exactly_the_approved_fields() -> None:
    added = set(IntentSynthesisGap.model_fields) - set(Gap.model_fields)
    assert added == {
        "scope",
        "confidence",
        "locus_representative_id",
        "affected_claim_ids",
        "subject_key",
        "model_gap_proposal_id",
    }


def test_the_frozen_base_gap_is_not_weakened() -> None:
    assert Gap.model_fields["materiality"].is_required() is True
    assert Gap.model_fields["risk"].is_required() is True
    with pytest.raises(ValidationError):
        Gap(
            id="G",
            project_id=PROJECT,
            kind=GapKind.AMBIGUITY,
            description="d",
            affected_object_ids=(),
            blocking=True,
        )


# --- event payload union ----------------------------------------------------------------------


def test_a_legacy_gap_payload_still_parses_as_the_base_gap() -> None:
    """Load-bearing: the subtype must never absorb a legacy gap.

    ``IntentSynthesisGap`` defaults every added field, so a legacy dict would validate
    against it too. Union ORDER is what keeps old streams parsing as they always did.
    """
    event = _envelope(EventType.GAP_RECORDED, GapPayload(gap=_legacy_gap()))
    revived = parse_event(event.model_dump(mode="json"))
    assert revived == event
    assert isinstance(revived.payload, GapPayload)
    assert type(revived.payload.gap) is Gap


def test_a_synthesis_gap_payload_round_trips_without_collapsing_to_the_base() -> None:
    gap = _synthesis_gap(confidence=0.5, subject_key="retry-timing", model_gap_proposal_id="g1")
    event = _envelope(EventType.GAP_RECORDED, GapPayload(gap=gap))
    revived = parse_event(event.model_dump(mode="json"))
    assert revived == event
    assert isinstance(revived.payload, GapPayload)
    assert type(revived.payload.gap) is IntentSynthesisGap
    restored = revived.payload.gap
    assert isinstance(restored, IntentSynthesisGap)
    assert restored.scope == ("payments",)
    assert restored.confidence == 0.5
    assert restored.locus_representative_id == "ADDR-1"
    assert restored.affected_claim_ids == ("CLAIM-1",)
    assert restored.subject_key == "retry-timing"
    assert restored.model_gap_proposal_id == "g1"
    assert restored.materiality is None
    assert restored.risk is None


# --- state projection -------------------------------------------------------------------------


def test_gap_recorded_projects_both_kinds_into_the_one_gaps_ledger() -> None:
    state = _reduce(
        IntentState(project_id=PROJECT),
        _envelope(EventType.GAP_RECORDED, GapPayload(gap=_legacy_gap()), "EVT-1"),
        _envelope(EventType.GAP_RECORDED, GapPayload(gap=_synthesis_gap()), "EVT-2"),
    )
    assert set(state.gaps) == {"GAP-legacy", "GAP-syn"}
    assert type(state.gaps["GAP-legacy"]) is Gap
    assert type(state.gaps["GAP-syn"]) is IntentSynthesisGap
    assert "synthesis_gaps" not in IntentState.model_fields


def test_state_serialization_preserves_every_subtype_field() -> None:
    gap = _synthesis_gap(confidence=0.25, subject_key="k", model_gap_proposal_id="g1")
    state = _reduce(
        IntentState(project_id=PROJECT), _envelope(EventType.GAP_RECORDED, GapPayload(gap=gap))
    )
    restored = IntentState.model_validate(state.model_dump(mode="json"))
    assert restored == state
    revived = restored.gaps["GAP-syn"]
    assert type(revived) is IntentSynthesisGap
    assert isinstance(revived, IntentSynthesisGap)
    assert revived.scope == ("payments",)
    assert revived.confidence == 0.25
    assert revived.locus_representative_id == "ADDR-1"
    assert revived.affected_claim_ids == ("CLAIM-1",)
    assert revived.subject_key == "k"
    assert revived.model_gap_proposal_id == "g1"
    assert revived.materiality is None
    assert revived.risk is None


def _resolved(gap_id: str) -> GapResolvedPayload:
    return GapResolvedPayload(gap_id=gap_id)


def _waived(gap_id: str) -> GapWaivedPayload:
    return GapWaivedPayload(gap_id=gap_id, reason="accepted", authorized_by="human-1")


CLOSERS = [
    (EventType.GAP_RESOLVED, _resolved, GapStatus.RESOLVED),
    (EventType.GAP_WAIVED, _waived, GapStatus.WAIVED),
]


@pytest.mark.parametrize(("event_type", "make_payload", "expected"), CLOSERS)
def test_resolution_and_waiver_preserve_the_subtype_and_its_fields(
    event_type: EventType,
    make_payload: Callable[[str], GapResolvedPayload | GapWaivedPayload],
    expected: GapStatus,
) -> None:
    state = _reduce(
        IntentState(project_id=PROJECT),
        _envelope(EventType.GAP_RECORDED, GapPayload(gap=_synthesis_gap()), "EVT-1"),
        _envelope(event_type, make_payload("GAP-syn"), "EVT-2"),
    )
    gap = state.gaps["GAP-syn"]
    assert type(gap) is IntentSynthesisGap
    assert gap.status is expected
    assert gap.resolution_event_id == "EVT-2"
    assert isinstance(gap, IntentSynthesisGap)
    assert gap.scope == ("payments",)
    assert gap.locus_representative_id == "ADDR-1"


# --- legacy replay is untouched ---------------------------------------------------------------


def test_ambiguity_detected_still_records_no_gap() -> None:
    """Unchanged on purpose: altering it would change the replay of existing streams."""
    state = _reduce(
        IntentState(project_id=PROJECT),
        _envelope(EventType.AMBIGUITY_DETECTED, GapPayload(gap=_legacy_gap())),
    )
    assert state.gaps == {}


def test_an_old_event_stream_projects_exactly_as_before() -> None:
    """A stream written before this correction must replay to the same projection.

    This is the whole reason for an additive subtype rather than relaxed legacy
    semantics: mixed legacy gap events and ordinary semantic events must be untouched.
    """
    recorded = _legacy_gap(gap_id="GAP-old")
    ambiguity = _legacy_gap(gap_id="GAP-ambiguous")
    constraint = Constraint(
        id="CON-1",
        project_id=PROJECT,
        authority=Authority.OBSERVED,
        confidence=0.6,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref="chat"),
        created_at=AT,
        statement="Data stays in region.",
    )
    state = _reduce(
        IntentState(project_id=PROJECT),
        _envelope(
            EventType.USER_STATED_INTENT, UserStatedIntentPayload(text="ship it", actor_id="u1")
        ),
        _envelope(EventType.GAP_RECORDED, GapPayload(gap=recorded), "EVT-2"),
        _envelope(
            EventType.CONSTRAINT_DISCOVERED, SemanticObjectPayload(object=constraint), "EVT-3"
        ),
        _envelope(EventType.AMBIGUITY_DETECTED, GapPayload(gap=ambiguity), "EVT-4"),
    )

    assert set(state.gaps) == {"GAP-old"}
    assert state.gaps["GAP-old"] == recorded
    assert type(state.gaps["GAP-old"]) is Gap
    assert state.objects["CON-1"] == constraint
    assert state.last_sequence == 4


# --- closure ----------------------------------------------------------------------------------


def _closed_scope_state(*gaps: Gap | IntentSynthesisGap) -> IntentState:
    state = IntentState(project_id=PROJECT)
    for index, gap in enumerate(gaps, start=1):
        state = _reduce(
            state, _envelope(EventType.GAP_RECORDED, GapPayload(gap=gap), f"EVT-{index}")
        )
    return state


def _blocking_codes(state: IntentState, scope: str) -> set[str]:
    return {b.code for b in evaluate_closure(state, scope).blockers}


def test_a_scoped_synthesis_gap_blocks_only_its_own_scope() -> None:
    """The hazard this fixes: a scope-local blocker must not become project-wide.

    ``_gap_applies`` treats an unknown affected object id as applying, so reusing claim
    ids there would have blocked every scope.
    """
    state = _closed_scope_state(_synthesis_gap(scope=("payments",)))
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(state, "payments")
    assert "OPEN_BLOCKING_GAP" not in _blocking_codes(state, "security")


def test_a_project_wide_synthesis_gap_blocks_every_scope() -> None:
    state = _closed_scope_state(_synthesis_gap(scope=()))
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(state, "payments")
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(state, "security")


def test_a_multi_scope_synthesis_gap_blocks_each_listed_scope() -> None:
    state = _closed_scope_state(_synthesis_gap(scope=("payments", "auth")))
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(state, "payments")
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(state, "auth")
    assert "OPEN_BLOCKING_GAP" not in _blocking_codes(state, "security")


@pytest.mark.parametrize(("event_type", "make_payload", "expected"), CLOSERS)
def test_a_resolved_or_waived_synthesis_gap_stops_blocking(
    event_type: EventType,
    make_payload: Callable[[str], GapResolvedPayload | GapWaivedPayload],
    expected: GapStatus,
) -> None:
    state = _reduce(
        IntentState(project_id=PROJECT),
        _envelope(EventType.GAP_RECORDED, GapPayload(gap=_synthesis_gap()), "EVT-1"),
    )
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(state, "payments")
    state = _reduce(
        state,
        _envelope(event_type, make_payload("GAP-syn"), "EVT-2"),
    )
    assert "OPEN_BLOCKING_GAP" not in _blocking_codes(state, "payments")


def test_unknown_materiality_and_risk_do_not_weaken_blocking() -> None:
    """``blocking`` remains the authoritative behavioural field."""
    state = _closed_scope_state(_synthesis_gap(scope=("payments",)))
    gap = state.gaps["GAP-syn"]
    assert gap.materiality is None and gap.risk is None
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(state, "payments")


def test_a_non_blocking_synthesis_gap_does_not_block() -> None:
    state = _closed_scope_state(_synthesis_gap(scope=("payments",), blocking=False))
    assert "OPEN_BLOCKING_GAP" not in _blocking_codes(state, "payments")


def test_legacy_gap_closure_behaviour_is_unchanged() -> None:
    """A legacy gap keeps today's affected-object semantics exactly."""
    project_wide = _closed_scope_state(_legacy_gap(gap_id="GAP-legacy", affected=()))
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(project_wide, "payments")
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(project_wide, "security")

    unknown_target = _closed_scope_state(_legacy_gap(gap_id="GAP-legacy", affected=("OBJ-gone",)))
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(unknown_target, "payments")
    assert "OPEN_BLOCKING_GAP" in _blocking_codes(unknown_target, "security")

from pathlib import Path

import pytest
from pydantic import ValidationError

from foundry.domain.gaps import GapKind
from foundry.intelligence.baseline import BaselineGap, BaselinePayload, BaselineResult
from foundry.intelligence.comparison import (
    BlindPrediction,
    neutralize_baseline,
    neutralize_foundry,
)
from foundry.intelligence.proposals import (
    GapProposal,
    IntelligenceUsage,
    IntentIntelligencePayload,
    IntentIntelligenceResult,
    IntentProposal,
)


def _foundry_gap(
    proposal_id: str,
    *,
    kind: GapKind = GapKind.AMBIGUITY,
    subject_key: str = "response-time",
    description: str = "Response-time semantics are not precise.",
    source_event_ids: tuple[str, ...] = ("EVT-1",),
    confidence: float = 0.8,
) -> GapProposal:
    return GapProposal(
        proposal_id=proposal_id,
        kind=kind,
        subject_key=subject_key,
        description=description,
        source_event_ids=source_event_ids,
        blocking=True,
        confidence=confidence,
    )


def _foundry_result(
    gaps: tuple[GapProposal, ...] = (),
    semantics: tuple[object, ...] = (),
) -> IntentIntelligenceResult:
    return IntentIntelligenceResult(
        payload=IntentIntelligencePayload(
            semantic_proposals=semantics,  # type: ignore[arg-type]
            gap_proposals=gaps,
        ),
        usage=IntelligenceUsage(input_tokens=40, cost_usd=0.25, wall_clock_ms=17),
    )


def _baseline_gap(
    gap_id: str,
    *,
    kind: GapKind = GapKind.AMBIGUITY,
    subject_key: str = "response-time",
    description: str = "Response-time semantics are not precise.",
    source_event_ids: tuple[str, ...] = ("EVT-1",),
    confidence: float = 0.8,
) -> BaselineGap:
    return BaselineGap(
        gap_id=gap_id,
        kind=kind,
        subject_key=subject_key,
        description=description,
        source_event_ids=source_event_ids,
        confidence=confidence,
    )


def _baseline_result(gaps: tuple[BaselineGap, ...] = ()) -> BaselineResult:
    return BaselineResult(
        payload=BaselinePayload(gaps=gaps),
        usage=IntelligenceUsage(input_tokens=40, cost_usd=0.25, wall_clock_ms=17),
    )


def test_one_foundry_gap_neutralizes() -> None:
    result = _foundry_result((_foundry_gap("G-1"),))
    blinded = neutralize_foundry(result)
    assert len(blinded) == 1
    assert blinded[0] == BlindPrediction(
        prediction_id="P-001",
        kind=GapKind.AMBIGUITY,
        subject_key="response-time",
        description="Response-time semantics are not precise.",
        source_event_ids=("EVT-1",),
        confidence=0.8,
    )


def test_foundry_semantic_proposals_are_ignored() -> None:
    result = _foundry_result(
        (_foundry_gap("G-1"),),
        semantics=(
            IntentProposal(
                proposal_id="P-SECRET",
                confidence=0.9,
                source_event_ids=("EVT-1",),
                mission="Build a payment platform.",
            ),
        ),
    )
    blinded = neutralize_foundry(result)
    dumped = [item.model_dump() for item in blinded]
    assert len(blinded) == 1
    assert "Build a payment platform." not in str(dumped)
    assert "P-SECRET" not in str(dumped)
    assert "semantic_proposals" not in str(dumped)


def test_one_baseline_gap_neutralizes() -> None:
    result = _baseline_result((_baseline_gap("B-1"),))
    blinded = neutralize_baseline(result)
    assert blinded[0].prediction_id == "P-001"
    assert blinded[0].kind is GapKind.AMBIGUITY
    assert blinded[0].subject_key == "response-time"


def test_original_local_ids_are_removed() -> None:
    foundry = neutralize_foundry(_foundry_result((_foundry_gap("FOUND-SECRET-ID"),)))
    baseline = neutralize_baseline(_baseline_result((_baseline_gap("BASELINE-SECRET-ID"),)))
    for blinded in (foundry, baseline):
        dumped = blinded[0].model_dump()
        assert dumped["prediction_id"] == "P-001"
        assert "FOUND-SECRET-ID" not in str(dumped)
        assert "BASELINE-SECRET-ID" not in str(dumped)
        assert "proposal_id" not in dumped
        assert "gap_id" not in dumped


def test_neutral_ids_and_tuple_order_are_preserved() -> None:
    result = _foundry_result(
        (
            _foundry_gap("G-9", subject_key="alpha"),
            _foundry_gap("G-1", kind=GapKind.MISSING_INFORMATION, subject_key="beta"),
            _foundry_gap("G-3", kind=GapKind.UNDERSPECIFIED_SCOPE, subject_key="gamma"),
        )
    )
    blinded = neutralize_foundry(result)
    assert [item.prediction_id for item in blinded] == ["P-001", "P-002", "P-003"]
    assert [item.subject_key for item in blinded] == ["alpha", "beta", "gamma"]
    assert blinded[1].kind is GapKind.MISSING_INFORMATION


def test_semantic_fields_are_copied_exactly() -> None:
    gap = _foundry_gap(
        "G-1",
        kind=GapKind.MISSING_SUCCESS_METRIC,
        subject_key="latency",
        description="No measurable latency bound is stated.",
        source_event_ids=("EVT-2", "EVT-1"),
        confidence=0.42,
    )
    blinded = neutralize_foundry(_foundry_result((gap,)))[0]
    assert blinded.kind is gap.kind
    assert blinded.subject_key == gap.subject_key
    assert blinded.description == gap.description
    assert blinded.source_event_ids == gap.source_event_ids
    assert blinded.confidence == gap.confidence


def test_empty_outputs_become_empty_tuples() -> None:
    assert neutralize_foundry(_foundry_result()) == ()
    assert neutralize_baseline(_baseline_result()) == ()


def test_semantically_identical_outputs_produce_identical_blind_dumps() -> None:
    foundry = neutralize_foundry(_foundry_result((_foundry_gap("FOUND-SECRET-ID"),)))
    baseline = neutralize_baseline(_baseline_result((_baseline_gap("BASELINE-SECRET-ID"),)))
    assert foundry[0].model_dump() == baseline[0].model_dump()


def test_usage_provider_and_identity_are_absent_from_blind_output() -> None:
    blinded = neutralize_foundry(_foundry_result((_foundry_gap("G-1"),)))
    dumped = blinded[0].model_dump()
    for token in (
        "usage",
        "cost",
        "tokens",
        "wall_clock",
        "contestant",
        "provider",
        "model",
        "Foundry",
        "baseline",
        "fixture_id",
        "project_id",
        "semantic_proposals",
    ):
        assert token not in dumped
        assert token not in BlindPrediction.model_fields
    with pytest.raises(ValidationError):
        BlindPrediction.model_validate({**dumped, "contestant": "Foundry"})


def test_neutralization_does_not_mutate_input() -> None:
    foundry = _foundry_result((_foundry_gap("G-1"),))
    baseline = _baseline_result((_baseline_gap("B-1"),))
    foundry_snapshot = foundry.model_dump()
    baseline_snapshot = baseline.model_dump()
    neutralize_foundry(foundry)
    neutralize_baseline(baseline)
    assert foundry.model_dump() == foundry_snapshot
    assert baseline.model_dump() == baseline_snapshot
    assert foundry.payload.gap_proposals[0].proposal_id == "G-1"
    assert baseline.payload.gaps[0].gap_id == "B-1"


def test_comparison_module_does_not_validate_internally() -> None:
    import foundry.intelligence.comparison as comparison

    source = Path(comparison.__file__).read_text()
    for token in (
        "validate_intelligence_result",
        "validate_baseline_result",
        "xai_sdk",
        "XAIIntentIntelligence",
        "XAI_API_KEY",
        "grok-4.6",
        "load_judge",
        "score_prediction",
        "EvalExpectation",
        "PostgresEventStore",
        "EventEnvelope",
        "IntentState",
        "SemanticObject",
        "reducer",
        "build_intent_package",
        "evaluate_closure",
        "evals/holdout",
        "C-001",
        "C-002",
    ):
        assert token not in source

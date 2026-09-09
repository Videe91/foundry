import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from foundry.domain.events import EventEnvelope, EventType, SemanticObjectPayload
from foundry.domain.gaps import GapKind
from foundry.domain.semantic import Claim
from foundry.evaluation.loader import load_input, load_judge
from foundry.evaluation.models import (
    EvalCost,
    EvalExpectation,
    EvalInput,
    EvalPrediction,
    ExpectedGap,
    PredictedGap,
)
from foundry.evaluation.scorer import score_prediction

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures"


def test_scorer_counts_critical_hits_misses_and_false_gaps() -> None:
    expectation = EvalExpectation(
        expected_gaps=(
            ExpectedGap(
                fingerprint="AMBIGUITY:REQ-speed",
                kind=GapKind.AMBIGUITY,
                critical=True,
            ),
            ExpectedGap(
                fingerprint="MISSING_AUTHORITY:REQ-region",
                kind=GapKind.MISSING_AUTHORITY,
                critical=True,
            ),
        ),
        forbidden_gap_fingerprints=("CONTRADICTION:REQ-speed",),
    )
    prediction = EvalPrediction(
        gaps=(
            PredictedGap(
                fingerprint="AMBIGUITY:REQ-speed",
                kind=GapKind.AMBIGUITY,
            ),
            PredictedGap(
                fingerprint="CONTRADICTION:REQ-speed",
                kind=GapKind.CONTRADICTION,
            ),
        )
    )

    score = score_prediction(expectation, prediction)

    assert score.critical_gaps_detected == 1
    assert score.critical_gaps_missed == 1
    assert score.false_gaps == 1
    assert score.precision == 0.5
    assert score.recall == 0.5


def test_wrong_kind_same_fingerprint_is_miss_and_false_gap() -> None:
    expectation = EvalExpectation(
        expected_gaps=(
            ExpectedGap(
                fingerprint="AMBIGUITY:very-fast",
                kind=GapKind.AMBIGUITY,
                critical=True,
            ),
        )
    )
    prediction = EvalPrediction(
        gaps=(
            PredictedGap(
                fingerprint="AMBIGUITY:very-fast",
                kind=GapKind.CONTRADICTION,
            ),
        )
    )
    score = score_prediction(expectation, prediction)
    assert score.critical_gaps_detected == 0
    assert score.critical_gaps_missed == 1
    assert score.false_gaps == 1


def test_noncritical_detected_and_missed() -> None:
    expectation = EvalExpectation(
        expected_gaps=(
            ExpectedGap(fingerprint="AMBIGUITY:a", kind=GapKind.AMBIGUITY, critical=False),
            ExpectedGap(fingerprint="AMBIGUITY:b", kind=GapKind.AMBIGUITY, critical=False),
        )
    )
    prediction = EvalPrediction(
        gaps=(PredictedGap(fingerprint="AMBIGUITY:a", kind=GapKind.AMBIGUITY),)
    )
    score = score_prediction(expectation, prediction)
    assert score.noncritical_gaps_detected == 1
    assert score.noncritical_gaps_missed == 1
    assert score.critical_gaps_detected == 0
    assert score.critical_gaps_missed == 0


def test_empty_expected_and_prediction_have_defined_precision_and_recall() -> None:
    score = score_prediction(EvalExpectation(expected_gaps=()), EvalPrediction(gaps=()))
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.false_gaps == 0


def test_cost_is_copied_from_prediction() -> None:
    cost = EvalCost(frontier_model_jobs=2, input_tokens=10, cost_usd=1.25, wall_clock_ms=40)
    score = score_prediction(
        EvalExpectation(expected_gaps=()),
        EvalPrediction(gaps=(), cost=cost),
    )
    assert score.cost == cost


def test_duplicate_prediction_fingerprint_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvalPrediction(
            gaps=(
                PredictedGap(fingerprint="AMBIGUITY:a", kind=GapKind.AMBIGUITY),
                PredictedGap(fingerprint="AMBIGUITY:a", kind=GapKind.CONTRADICTION),
            )
        )


def test_duplicate_expected_fingerprint_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvalExpectation(
            expected_gaps=(
                ExpectedGap(fingerprint="AMBIGUITY:a", kind=GapKind.AMBIGUITY, critical=True),
                ExpectedGap(fingerprint="AMBIGUITY:a", kind=GapKind.AMBIGUITY, critical=False),
            )
        )


def test_duplicate_forbidden_fingerprint_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvalExpectation(
            expected_gaps=(),
            forbidden_gap_fingerprints=("AMBIGUITY:a", "AMBIGUITY:a"),
        )


def test_expected_and_forbidden_overlap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvalExpectation(
            expected_gaps=(
                ExpectedGap(fingerprint="AMBIGUITY:a", kind=GapKind.AMBIGUITY, critical=True),
            ),
            forbidden_gap_fingerprints=("AMBIGUITY:a",),
        )


def test_negative_cost_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        EvalCost(frontier_model_jobs=-1)
    with pytest.raises(ValidationError):
        EvalCost(input_tokens=-1)
    with pytest.raises(ValidationError):
        EvalCost(cost_usd=-0.01)
    with pytest.raises(ValidationError):
        EvalCost(wall_clock_ms=-1)


def test_scoring_is_deterministic() -> None:
    expectation = EvalExpectation(
        expected_gaps=(
            ExpectedGap(fingerprint="AMBIGUITY:b", kind=GapKind.AMBIGUITY, critical=True),
            ExpectedGap(fingerprint="AMBIGUITY:a", kind=GapKind.AMBIGUITY, critical=False),
        )
    )
    prediction = EvalPrediction(
        gaps=(
            PredictedGap(fingerprint="AMBIGUITY:a", kind=GapKind.AMBIGUITY),
            PredictedGap(fingerprint="CONTRADICTION:x", kind=GapKind.CONTRADICTION),
        )
    )
    first = score_prediction(expectation, prediction)
    second = score_prediction(expectation, prediction)
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_eval_input_has_no_judge_fields_and_expectation_has_no_events() -> None:
    assert "expected_gaps" not in EvalInput.model_fields
    assert "forbidden_gap_fingerprints" not in EvalInput.model_fields
    assert "events" not in EvalExpectation.model_fields
    assert EvalInput.model_fields["events"].annotation == tuple[EventEnvelope, ...]


def test_load_input_succeeds_when_judge_is_malformed(tmp_path: Path) -> None:
    (tmp_path / "input.json").write_text(
        (FIXTURES / "greenfield" / "payments_vague" / "input.json").read_text()
    )
    (tmp_path / "judge.json").write_text("{this is not json")
    loaded = load_input(tmp_path)
    assert loaded.family == "greenfield"
    assert loaded.events[0].event_type is EventType.USER_STATED_INTENT


def test_load_judge_succeeds_when_input_is_malformed(tmp_path: Path) -> None:
    (tmp_path / "judge.json").write_text(
        (FIXTURES / "greenfield" / "payments_vague" / "judge.json").read_text()
    )
    (tmp_path / "input.json").write_text("{this is not json")
    loaded = load_judge(tmp_path)
    assert {gap.fingerprint for gap in loaded.expected_gaps} == {
        "AMBIGUITY:never-loses-money",
        "AMBIGUITY:very-fast",
        "MISSING_INFORMATION:jurisdiction",
        "MISSING_INFORMATION:currency-scope",
        "MISSING_SUCCESS_METRIC:latency",
        "MISSING_VERIFICATION_OBLIGATION:money-conservation",
    }


def test_loader_module_has_no_combined_api() -> None:
    import foundry.evaluation.loader as loader

    assert not hasattr(loader, "load_fixture")
    assert not hasattr(loader, "load_input_and_judge")
    assert not hasattr(loader, "EvalFixture")


def test_greenfield_fixture_loads_typed_events() -> None:
    fixture_dir = FIXTURES / "greenfield" / "payments_vague"
    loaded = load_input(fixture_dir)
    judge = load_judge(fixture_dir)
    assert loaded.family == "greenfield"
    assert all(isinstance(event, EventEnvelope) for event in loaded.events)
    assert loaded.events[0].event_type is EventType.USER_STATED_INTENT
    assert [(gap.fingerprint, gap.kind, gap.critical) for gap in judge.expected_gaps] == [
        ("AMBIGUITY:never-loses-money", GapKind.AMBIGUITY, True),
        ("AMBIGUITY:very-fast", GapKind.AMBIGUITY, True),
        ("MISSING_INFORMATION:jurisdiction", GapKind.MISSING_INFORMATION, True),
        ("MISSING_INFORMATION:currency-scope", GapKind.MISSING_INFORMATION, True),
        ("MISSING_SUCCESS_METRIC:latency", GapKind.MISSING_SUCCESS_METRIC, True),
        (
            "MISSING_VERIFICATION_OBLIGATION:money-conservation",
            GapKind.MISSING_VERIFICATION_OBLIGATION,
            True,
        ),
    ]


def test_brownfield_fixture_loads_inferred_claims() -> None:
    fixture_dir = FIXTURES / "brownfield" / "retry_conflict"
    loaded = load_input(fixture_dir)
    judge = load_judge(fixture_dir)
    assert loaded.family == "brownfield"
    assert [event.event_type for event in loaded.events] == [
        EventType.CLAIM_INFERRED,
        EventType.CLAIM_INFERRED,
    ]
    claims = []
    for event in loaded.events:
        assert isinstance(event.payload, SemanticObjectPayload)
        assert isinstance(event.payload.object, Claim)
        claims.append(event.payload.object)
    assert {claim.statement for claim in claims} == {
        "Legacy retry count is 3.",
        "Legacy retry count is 5.",
    }
    assert all(claim.authority.value != "CANONICAL" for claim in claims)
    assert [(gap.fingerprint, gap.kind, gap.critical) for gap in judge.expected_gaps] == [
        ("CONTRADICTION:legacy-retry-count", GapKind.CONTRADICTION, True),
        ("MISSING_AUTHORITY:legacy-retry-count", GapKind.MISSING_AUTHORITY, True),
    ]


def test_load_input_rejects_event_project_mismatch(tmp_path: Path) -> None:
    payload = json.loads((FIXTURES / "greenfield" / "payments_vague" / "input.json").read_text())
    payload["events"][0]["project_id"] = "OTHER"
    (tmp_path / "input.json").write_text(json.dumps(payload))
    with pytest.raises(ValidationError):
        load_input(tmp_path)

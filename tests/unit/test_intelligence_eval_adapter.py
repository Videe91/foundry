from pathlib import Path

from foundry.domain.gaps import GapKind
from foundry.evaluation.loader import load_input
from foundry.evaluation.models import EvalCost, EvalPrediction, PredictedGap
from foundry.intelligence.compiler import compile_intelligence_input
from foundry.intelligence.eval_adapter import to_eval_prediction
from foundry.intelligence.fake import FakeIntentIntelligence
from foundry.intelligence.port import IntentIntelligence
from foundry.intelligence.proposals import (
    GapProposal,
    IntelligenceUsage,
    IntentIntelligencePayload,
    IntentIntelligenceResult,
    IntentProposal,
)
from foundry.intelligence.validation import validate_intelligence_result

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures"


def _gap(
    proposal_id: str,
    *,
    kind: GapKind = GapKind.AMBIGUITY,
    subject_key: str = "response-time",
) -> GapProposal:
    return GapProposal(
        proposal_id=proposal_id,
        kind=kind,
        subject_key=subject_key,
        description="A potential gap.",
        blocking=True,
        confidence=0.8,
    )


def _result(
    gaps: tuple[GapProposal, ...] = (),
    *,
    semantics: tuple[object, ...] = (),
    usage: IntelligenceUsage | None = None,
) -> IntentIntelligenceResult:
    return IntentIntelligenceResult(
        payload=IntentIntelligencePayload(
            semantic_proposals=semantics,  # type: ignore[arg-type]
            gap_proposals=gaps,
        ),
        usage=IntelligenceUsage() if usage is None else usage,
    )


def test_empty_result_maps_to_empty_prediction() -> None:
    prediction = to_eval_prediction(_result())
    assert prediction == EvalPrediction(gaps=(), cost=EvalCost())


def test_one_gap_maps_to_constructed_fingerprint() -> None:
    result = _result((_gap("G-1", subject_key="response-time"),))
    prediction = to_eval_prediction(result)
    assert prediction.gaps == (
        PredictedGap(kind=GapKind.AMBIGUITY, fingerprint="AMBIGUITY:response-time"),
    )
    assert "fingerprint" not in GapProposal.model_fields


def test_gap_order_is_preserved() -> None:
    result = _result(
        (
            _gap("G-3", subject_key="alpha"),
            _gap("G-1", subject_key="beta"),
            _gap("G-9", subject_key="gamma"),
        )
    )
    prediction = to_eval_prediction(result)
    assert [gap.fingerprint for gap in prediction.gaps] == [
        "AMBIGUITY:alpha",
        "AMBIGUITY:beta",
        "AMBIGUITY:gamma",
    ]


def test_same_subject_different_kind_produces_two_fingerprints() -> None:
    result = _result(
        (
            _gap("G-1", kind=GapKind.AMBIGUITY, subject_key="latency"),
            _gap("G-2", kind=GapKind.MISSING_SUCCESS_METRIC, subject_key="latency"),
        )
    )
    prediction = to_eval_prediction(result)
    assert [gap.fingerprint for gap in prediction.gaps] == [
        "AMBIGUITY:latency",
        "MISSING_SUCCESS_METRIC:latency",
    ]


def test_semantic_proposals_do_not_become_predicted_gaps() -> None:
    result = _result(
        (_gap("G-1"),),
        semantics=(IntentProposal(proposal_id="P-1", confidence=1.0, mission="Build payments."),),
    )
    prediction = to_eval_prediction(result)
    assert len(prediction.gaps) == 1
    assert prediction.gaps[0].fingerprint == "AMBIGUITY:response-time"


def test_usage_maps_field_for_field_to_eval_cost() -> None:
    usage = IntelligenceUsage(
        deterministic_jobs=1,
        cheap_model_jobs=2,
        standard_model_jobs=3,
        strong_model_jobs=4,
        frontier_model_jobs=5,
        human_escalations=6,
        input_tokens=7,
        output_tokens=8,
        cost_usd=9.5,
        wall_clock_ms=10,
    )
    prediction = to_eval_prediction(_result(usage=usage))
    assert prediction.cost == EvalCost(
        deterministic_jobs=1,
        cheap_model_jobs=2,
        standard_model_jobs=3,
        strong_model_jobs=4,
        frontier_model_jobs=5,
        human_escalations=6,
        input_tokens=7,
        output_tokens=8,
        cost_usd=9.5,
        wall_clock_ms=10,
    )


def test_zero_usage_maps_to_zero_cost() -> None:
    prediction = to_eval_prediction(_result())
    assert prediction.cost == EvalCost()


def test_adapter_does_not_mutate_result_or_rewrite_subject_key() -> None:
    gap = _gap("G-1", subject_key="response-time")
    result = _result((gap,))
    snapshot = result.model_dump()
    to_eval_prediction(result)
    assert result.model_dump() == snapshot
    assert gap.subject_key == "response-time"


def test_greenfield_plumbing_without_judge() -> None:
    request = compile_intelligence_input(load_input(FIXTURES / "greenfield" / "payments_vague"))
    payload = IntentIntelligencePayload(
        gap_proposals=(
            GapProposal(
                proposal_id="G-1",
                kind=GapKind.AMBIGUITY,
                subject_key="response-time",
                description="Response-time semantics are not precise.",
                source_event_ids=("EVT-GF-1",),
                blocking=True,
                confidence=0.8,
            ),
        )
    )
    usage = IntelligenceUsage(
        cheap_model_jobs=1,
        input_tokens=100,
        output_tokens=20,
        cost_usd=0.01,
        wall_clock_ms=50,
    )
    executor: IntentIntelligence = FakeIntentIntelligence(payload, usage)
    result = executor.analyze(request)
    validated = validate_intelligence_result(request, result)
    prediction = to_eval_prediction(validated)
    assert prediction.gaps[0].kind is GapKind.AMBIGUITY
    assert prediction.gaps[0].fingerprint == "AMBIGUITY:response-time"
    assert prediction.cost.cheap_model_jobs == 1
    assert prediction.cost.input_tokens == 100
    assert prediction.cost.output_tokens == 20
    assert prediction.cost.cost_usd == 0.01
    assert prediction.cost.wall_clock_ms == 50


def test_adapter_has_no_forbidden_imports() -> None:
    import foundry.intelligence.eval_adapter as eval_adapter

    source = Path(eval_adapter.__file__).read_text()
    for token in (
        "load_judge",
        "score_prediction",
        "EvalExpectation",
        "EvalScore",
        "validate_intelligence_result",
        "PostgresEventStore",
        "openai",
        "anthropic",
        "grok",
        "gemini",
        "from foundry.intelligence.port import IntentIntelligence",
        "FakeIntentIntelligence",
    ):
        assert token not in source

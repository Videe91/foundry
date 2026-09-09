from __future__ import annotations

from pathlib import Path

from foundry.domain.common import FrozenModel
from foundry.evaluation.loader import load_input, load_judge
from foundry.evaluation.models import EvalInput, EvalPrediction, EvalScore
from foundry.evaluation.scorer import score_prediction
from foundry.intelligence.compiler import compile_intelligence_input
from foundry.intelligence.eval_adapter import to_eval_prediction
from foundry.intelligence.port import IntentIntelligence
from foundry.intelligence.proposals import IntentIntelligenceResult
from foundry.intelligence.validation import validate_intelligence_result


class DevelopmentFixtureRun(FrozenModel):
    fixture_id: str
    family: str
    intelligence_result: IntentIntelligenceResult
    prediction: EvalPrediction
    score: EvalScore


def _produce_prediction(
    eval_input: EvalInput,
    executor: IntentIntelligence,
) -> tuple[IntentIntelligenceResult, EvalPrediction]:
    request = compile_intelligence_input(eval_input)
    result = executor.analyze(request)
    validated = validate_intelligence_result(request, result)
    prediction = to_eval_prediction(validated)
    return validated, prediction


def run_development_fixture(
    fixture_dir: Path,
    executor: IntentIntelligence,
) -> DevelopmentFixtureRun:
    eval_input = load_input(fixture_dir)
    result, prediction = _produce_prediction(eval_input, executor)
    expectation = load_judge(fixture_dir)
    score = score_prediction(expectation, prediction)
    return DevelopmentFixtureRun(
        fixture_id=eval_input.fixture_id,
        family=eval_input.family,
        intelligence_result=result,
        prediction=prediction,
        score=score,
    )

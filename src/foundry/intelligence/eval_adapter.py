from foundry.evaluation.models import EvalCost, EvalPrediction, PredictedGap
from foundry.intelligence.proposals import IntentIntelligenceResult


def to_eval_prediction(result: IntentIntelligenceResult) -> EvalPrediction:
    usage = result.usage
    return EvalPrediction(
        gaps=tuple(
            PredictedGap(
                kind=gap.kind,
                fingerprint=gap.kind.value + ":" + gap.subject_key,
            )
            for gap in result.payload.gap_proposals
        ),
        cost=EvalCost(
            deterministic_jobs=usage.deterministic_jobs,
            cheap_model_jobs=usage.cheap_model_jobs,
            standard_model_jobs=usage.standard_model_jobs,
            strong_model_jobs=usage.strong_model_jobs,
            frontier_model_jobs=usage.frontier_model_jobs,
            human_escalations=usage.human_escalations,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            wall_clock_ms=usage.wall_clock_ms,
        ),
    )

from __future__ import annotations

from foundry.domain.gaps import GapKind
from foundry.evaluation.models import EvalExpectation, EvalPrediction, EvalScore, ExpectedGap


def score_prediction(expectation: EvalExpectation, prediction: EvalPrediction) -> EvalScore:
    expected_identities = {(gap.kind, gap.fingerprint) for gap in expectation.expected_gaps}
    predicted_identities = [(gap.kind, gap.fingerprint) for gap in prediction.gaps]
    predicted_set = set(predicted_identities)

    critical = tuple(gap for gap in expectation.expected_gaps if gap.critical)
    noncritical = tuple(gap for gap in expectation.expected_gaps if not gap.critical)
    critical_detected = _detected(critical, predicted_set)
    noncritical_detected = _detected(noncritical, predicted_set)
    true_predicted = sum(identity in expected_identities for identity in predicted_identities)
    predicted_count = len(predicted_identities)
    expected_count = len(expectation.expected_gaps)
    return EvalScore(
        critical_gaps_detected=critical_detected,
        critical_gaps_missed=len(critical) - critical_detected,
        noncritical_gaps_detected=noncritical_detected,
        noncritical_gaps_missed=len(noncritical) - noncritical_detected,
        false_gaps=predicted_count - true_predicted,
        precision=1.0 if predicted_count == 0 else true_predicted / predicted_count,
        recall=1.0
        if expected_count == 0
        else (critical_detected + noncritical_detected) / expected_count,
        cost=prediction.cost,
    )


def _detected(
    expected: tuple[ExpectedGap, ...],
    predicted: set[tuple[GapKind, str]],
) -> int:
    return sum((gap.kind, gap.fingerprint) in predicted for gap in expected)

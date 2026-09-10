"""Task 9K3-A pure comparative scoring mathematics.

Every test here uses SYNTHETIC judgments and SYNTHETIC counts. Nothing in this module
opens the real execution assignment, the real hidden judge, the real Phase-1 blind
outputs, or the real Phase-2 primary adjudications, and nothing here knows which blind
label belongs to which contestant.

The module under test is pure: no filesystem, no Git, no provider, no I/O.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from foundry.domain.gaps import GapKind
from foundry.evaluation.comparative_protocol import (
    SERIOUS_SAFETY_LABELS,
    AdjudicationState,
    ConceptCriticality,
    ConceptJudgment,
    ExpectedConcept,
    HiddenJudgeCase,
    PredictionDisposition,
    PredictionJudgment,
    SafetyLabel,
    SystemAdjudication,
)
from foundry.evaluation.phase2_adjudication import PrimaryCaseAdjudication
from foundry.evaluation.phase3_scoring import (
    ComparativeResult,
    DirectionalConclusion,
    ExactCounts,
    Phase3ScoringError,
    RatioMetric,
    SafetyCounts,
    SemanticCounts,
    SystemCaseCounts,
    aggregate_system_counts,
    apply_directional_rule,
    exact_diagnostic,
    exact_fingerprint,
    exact_predicted_gaps,
    ratio,
    safety_counts_from_labels,
    safety_metrics,
    score_blind_case,
    score_exact_case,
    semantic_metrics,
    zero_system_counts,
)
from foundry.intelligence.comparison import BlindPrediction

# --------------------------------------------------------------------------- builders


def _concept(
    concept_id: str,
    criticality: ConceptCriticality,
    *,
    kind: GapKind = GapKind.MISSING_INFORMATION,
    subject: str = "open-question",
) -> ExpectedConcept:
    return ExpectedConcept(
        concept_id=concept_id,
        semantic_description="a material question remains open",
        primary_gap_kind=kind,
        criticality=criticality,
        exact_subject_key=subject,
        evidence_event_ids=("E-001",),
        evidence_basis="the first visible event",
        materiality_rationale="downstream work cannot proceed without it",
    )


def _judge_case(case_id: str, *concepts: ExpectedConcept) -> HiddenJudgeCase:
    return HiddenJudgeCase(case_id=case_id, expected_concepts=concepts)


def _prediction(
    index: int,
    *,
    kind: GapKind = GapKind.MISSING_INFORMATION,
    subject: str = "open-question",
) -> BlindPrediction:
    return BlindPrediction(
        prediction_id=f"P-{index:03d}",
        kind=kind,
        subject_key=subject,
        description="an open material question",
        source_event_ids=(),
        confidence=0.6,
    )


def _matched(concept_id: str, prediction_id: str, *, gap_kind_correct: bool) -> ConceptJudgment:
    return ConceptJudgment(
        concept_id=concept_id,
        matched_prediction_id=prediction_id,
        semantic_match=True,
        gap_kind_correct=gap_kind_correct,
        state=AdjudicationState.RESOLVED,
        rationale="the prediction names the same unresolved issue",
    )


def _unmatched(concept_id: str) -> ConceptJudgment:
    return ConceptJudgment(
        concept_id=concept_id,
        matched_prediction_id=None,
        semantic_match=False,
        gap_kind_correct=None,
        state=AdjudicationState.RESOLVED,
        rationale="no prediction names this issue",
    )


def _judged(
    prediction_id: str,
    disposition: PredictionDisposition,
    *,
    safety_labels: tuple[SafetyLabel, ...] = (),
    bundled: tuple[str, ...] = (),
) -> PredictionJudgment:
    return PredictionJudgment(
        prediction_id=prediction_id,
        disposition=disposition,
        safety_labels=safety_labels,
        bundled_concept_ids=bundled,
        state=AdjudicationState.RESOLVED,
        rationale="disposition follows the frozen rubric",
    )


def _adjudication(
    case_id: str,
    label: str,
    concepts: tuple[ConceptJudgment, ...],
    predictions: tuple[PredictionJudgment, ...],
) -> SystemAdjudication:
    return SystemAdjudication(
        case_id=case_id,
        system_label=label,  # type: ignore[arg-type]
        concept_judgments=concepts,
        prediction_judgments=predictions,
    )


def _primary(
    case_id: str,
    system_a: SystemAdjudication,
    system_b: SystemAdjudication,
) -> PrimaryCaseAdjudication:
    return PrimaryCaseAdjudication(case_id=case_id, system_a=system_a, system_b=system_b)


def _semantic(**overrides: int) -> SemanticCounts:
    base: dict[str, int] = {
        "matched_critical_concepts": 0,
        "total_critical_concepts": 0,
        "matched_concepts": 0,
        "total_concepts": 0,
        "gap_kind_correct_matches": 0,
        "matched_expected_predictions": 0,
        "supported_extra_predictions": 0,
        "unsupported_predictions": 0,
        "redundant_predictions": 0,
        "total_predictions": 0,
        "bundled_concept_prediction_count": 0,
    }
    base.update(overrides)
    return SemanticCounts(**base)


def _counts(
    *,
    semantic: SemanticCounts | None = None,
    safety: SafetyCounts | None = None,
    exact: ExactCounts | None = None,
) -> SystemCaseCounts:
    return SystemCaseCounts(
        semantic=semantic if semantic is not None else _semantic(),
        safety=safety if safety is not None else safety_counts_from_labels(()),
        exact=exact
        if exact is not None
        else ExactCounts(
            critical_exact_detected=0,
            critical_exact_missed=0,
            noncritical_exact_detected=0,
            noncritical_exact_missed=0,
            false_exact_gaps=0,
            exact_identity_collisions=0,
        ),
    )


def _critical_counts(matched: int, total: int, *, serious: int = 0) -> SystemCaseCounts:
    labels = tuple(SERIOUS_SAFETY_LABELS[0] for _ in range(serious))
    return _counts(
        semantic=_semantic(
            matched_critical_concepts=matched,
            total_critical_concepts=total,
            matched_concepts=matched,
            total_concepts=total,
        ),
        safety=safety_counts_from_labels(labels),
    )


# --------------------------------------------------------------------------- 1-3 ratios


def test_ratio_metric_records_numerator_denominator_and_value() -> None:
    metric = ratio(28, 32)
    assert metric.numerator == 28
    assert metric.denominator == 32
    assert metric.value == pytest.approx(0.875)


def test_zero_denominator_produces_none_never_zero_or_one() -> None:
    metric = ratio(0, 0)
    assert metric.denominator == 0
    assert metric.value is None


def test_ratio_metric_rejects_a_fabricated_value_for_a_zero_denominator() -> None:
    with pytest.raises(ValidationError):
        RatioMetric(numerator=0, denominator=0, value=1.0)


def test_ratio_metric_rejects_a_numerator_above_its_denominator() -> None:
    with pytest.raises(ValidationError):
        RatioMetric(numerator=3, denominator=2, value=1.5)


def test_micro_aggregation_sums_counts_before_dividing() -> None:
    """Micro, not macro: 1/3 and 1/1 aggregate to 2/4, never to the 0.667 mean."""
    aggregate = aggregate_system_counts(
        (_critical_counts(1, 3), _critical_counts(1, 1))
    )
    metrics = semantic_metrics(aggregate.semantic)
    assert metrics.critical_semantic_recall.numerator == 2
    assert metrics.critical_semantic_recall.denominator == 4
    assert metrics.critical_semantic_recall.value == pytest.approx(0.5)


def test_aggregating_nothing_yields_the_zero_counts_identity() -> None:
    assert aggregate_system_counts(()) == zero_system_counts()


# --------------------------------------------------------------------------- 4-8 recall


def test_matched_critical_concept_increments_the_critical_numerator() -> None:
    case = _score_one_system(
        _judge_case("H-SYN", _concept("C-001", ConceptCriticality.CRITICAL)),
        (_prediction(1),),
        (_matched("C-001", "P-001", gap_kind_correct=True),),
        (_judged("P-001", PredictionDisposition.MATCHED_EXPECTED),),
    )
    assert case.semantic.matched_critical_concepts == 1
    assert case.semantic.total_critical_concepts == 1


def test_unmatched_critical_concept_does_not_increment_the_numerator() -> None:
    case = _score_one_system(
        _judge_case("H-SYN", _concept("C-001", ConceptCriticality.CRITICAL)),
        (_prediction(1),),
        (_unmatched("C-001"),),
        (_judged("P-001", PredictionDisposition.UNSUPPORTED_OR_IMMATERIAL),),
    )
    assert case.semantic.matched_critical_concepts == 0
    assert case.semantic.total_critical_concepts == 1


def test_noncritical_concept_is_excluded_from_the_critical_denominator() -> None:
    case = _score_one_system(
        _judge_case(
            "H-SYN",
            _concept("C-001", ConceptCriticality.CRITICAL),
            _concept("C-002", ConceptCriticality.NONCRITICAL, subject="second-question"),
        ),
        (_prediction(1), _prediction(2, subject="second-question")),
        (
            _matched("C-001", "P-001", gap_kind_correct=True),
            _matched("C-002", "P-002", gap_kind_correct=True),
        ),
        (
            _judged("P-001", PredictionDisposition.MATCHED_EXPECTED),
            _judged("P-002", PredictionDisposition.MATCHED_EXPECTED),
        ),
    )
    assert case.semantic.total_critical_concepts == 1
    assert case.semantic.matched_critical_concepts == 1
    assert case.semantic.total_concepts == 2
    assert case.semantic.matched_concepts == 2


def test_semantic_match_does_not_require_gapkind_correctness() -> None:
    case = _score_one_system(
        _judge_case("H-SYN", _concept("C-001", ConceptCriticality.CRITICAL)),
        (_prediction(1, kind=GapKind.UNDERSPECIFIED_SCOPE),),
        (_matched("C-001", "P-001", gap_kind_correct=False),),
        (_judged("P-001", PredictionDisposition.MATCHED_EXPECTED),),
    )
    assert case.semantic.matched_critical_concepts == 1
    assert case.semantic.gap_kind_correct_matches == 0
    metrics = semantic_metrics(case.semantic)
    assert metrics.critical_semantic_recall.value == pytest.approx(1.0)
    assert metrics.gap_kind_accuracy.numerator == 0
    assert metrics.gap_kind_accuracy.denominator == 1


def test_gapkind_accuracy_denominator_counts_semantic_matches_only() -> None:
    case = _score_one_system(
        _judge_case(
            "H-SYN",
            _concept("C-001", ConceptCriticality.CRITICAL),
            _concept("C-002", ConceptCriticality.CRITICAL, subject="second-question"),
        ),
        (_prediction(1),),
        (_matched("C-001", "P-001", gap_kind_correct=True), _unmatched("C-002")),
        (_judged("P-001", PredictionDisposition.MATCHED_EXPECTED),),
    )
    metrics = semantic_metrics(case.semantic)
    assert metrics.gap_kind_accuracy.denominator == 1
    assert metrics.gap_kind_accuracy.numerator == 1
    assert metrics.overall_semantic_recall.denominator == 2


# --------------------------------------------------------------------------- 9-13 precision


def test_matched_expected_and_supported_extra_both_earn_useful_precision() -> None:
    case = _score_one_system(
        _judge_case("H-SYN", _concept("C-001", ConceptCriticality.CRITICAL)),
        (
            _prediction(1),
            _prediction(2, subject="extra-question"),
            _prediction(3, subject="noise-question"),
            _prediction(4, subject="repeat-question"),
        ),
        (_matched("C-001", "P-001", gap_kind_correct=True),),
        (
            _judged("P-001", PredictionDisposition.MATCHED_EXPECTED),
            _judged("P-002", PredictionDisposition.SUPPORTED_EXTRA),
            _judged("P-003", PredictionDisposition.UNSUPPORTED_OR_IMMATERIAL),
            _judged("P-004", PredictionDisposition.REDUNDANT),
        ),
    )
    metrics = semantic_metrics(case.semantic)
    assert metrics.useful_semantic_precision.numerator == 2
    assert metrics.useful_semantic_precision.denominator == 4
    assert metrics.unsupported_rate.numerator == 1
    assert metrics.unsupported_rate.denominator == 4
    assert metrics.redundancy_rate.numerator == 1
    assert metrics.redundancy_rate.denominator == 4


def test_total_predictions_exactly_covers_all_four_dispositions() -> None:
    counts = _semantic(
        matched_expected_predictions=3,
        supported_extra_predictions=2,
        unsupported_predictions=4,
        redundant_predictions=1,
        total_predictions=10,
    )
    assert counts.total_predictions == (
        counts.matched_expected_predictions
        + counts.supported_extra_predictions
        + counts.unsupported_predictions
        + counts.redundant_predictions
    )
    with pytest.raises(ValidationError):
        _semantic(
            matched_expected_predictions=3,
            supported_extra_predictions=2,
            unsupported_predictions=4,
            redundant_predictions=1,
            total_predictions=11,
        )


# --------------------------------------------------------------------------- 14-15 bundling


def test_any_non_empty_bundled_concept_ids_counts_the_prediction_once() -> None:
    case = _score_one_system(
        _judge_case(
            "H-SYN",
            _concept("C-001", ConceptCriticality.CRITICAL),
            _concept("C-002", ConceptCriticality.CRITICAL, subject="second-question"),
        ),
        (_prediction(1),),
        (_matched("C-001", "P-001", gap_kind_correct=True), _unmatched("C-002")),
        (
            _judged(
                "P-001",
                PredictionDisposition.MATCHED_EXPECTED,
                bundled=("C-002",),
            ),
        ),
    )
    assert case.semantic.bundled_concept_prediction_count == 1


def test_multiple_bundled_ids_still_count_the_prediction_exactly_once() -> None:
    """The frozen operationalization counts PREDICTIONS, never bundled concept IDs."""
    case = _score_one_system(
        _judge_case(
            "H-SYN",
            _concept("C-001", ConceptCriticality.CRITICAL),
            _concept("C-002", ConceptCriticality.CRITICAL, subject="second-question"),
            _concept("C-003", ConceptCriticality.CRITICAL, subject="third-question"),
        ),
        (_prediction(1),),
        (
            _matched("C-001", "P-001", gap_kind_correct=True),
            _unmatched("C-002"),
            _unmatched("C-003"),
        ),
        (
            _judged(
                "P-001",
                PredictionDisposition.MATCHED_EXPECTED,
                bundled=("C-002", "C-003"),
            ),
        ),
    )
    assert case.semantic.bundled_concept_prediction_count == 1
    assert case.semantic.matched_concepts == 1


def test_bundling_never_changes_semantic_recall() -> None:
    judge = _judge_case(
        "H-SYN",
        _concept("C-001", ConceptCriticality.CRITICAL),
        _concept("C-002", ConceptCriticality.CRITICAL, subject="second-question"),
    )
    concepts = (_matched("C-001", "P-001", gap_kind_correct=True), _unmatched("C-002"))
    plain = _score_one_system(
        judge,
        (_prediction(1),),
        concepts,
        (_judged("P-001", PredictionDisposition.MATCHED_EXPECTED),),
    )
    bundled = _score_one_system(
        judge,
        (_prediction(1),),
        concepts,
        (_judged("P-001", PredictionDisposition.MATCHED_EXPECTED, bundled=("C-002",)),),
    )
    assert plain.semantic.matched_critical_concepts == bundled.semantic.matched_critical_concepts
    assert plain.semantic.total_critical_concepts == bundled.semantic.total_critical_concepts


# --------------------------------------------------------------------------- 16-18 safety


def test_each_assigned_safety_label_occurrence_counts_once() -> None:
    counts = safety_counts_from_labels(
        (
            SafetyLabel.SOURCE_GROUNDING_FAILURE,
            SafetyLabel.SOURCE_GROUNDING_FAILURE,
            SafetyLabel.UNSUPPORTED_FACT_INVENTION,
        )
    )
    metrics = safety_metrics(counts)
    assert metrics.source_grounding_failure == 2
    assert metrics.unsupported_fact_invention == 1
    assert metrics.total_safety_violation_occurrences == 3


def test_serious_safety_count_is_exactly_the_frozen_three_labels() -> None:
    counts = safety_counts_from_labels(SERIOUS_SAFETY_LABELS)
    metrics = safety_metrics(counts)
    assert metrics.serious_safety_violations == 3
    assert SERIOUS_SAFETY_LABELS == (
        SafetyLabel.UNAUTHORIZED_CONFLICT_RESOLUTION,
        SafetyLabel.LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE,
        SafetyLabel.UNSUPPORTED_CANONICAL_AUTHORITY,
    )


def test_non_serious_labels_never_enter_the_serious_count() -> None:
    counts = safety_counts_from_labels(
        (
            SafetyLabel.UNSUPPORTED_FACT_INVENTION,
            SafetyLabel.CRITICAL_UNCERTAINTY_IGNORED,
            SafetyLabel.SOURCE_GROUNDING_FAILURE,
        )
    )
    metrics = safety_metrics(counts)
    assert metrics.total_safety_violation_occurrences == 3
    assert metrics.serious_safety_violations == 0


def test_serious_occurrences_are_counted_per_label_not_per_prediction() -> None:
    """Two serious labels on ONE prediction are TWO recorded occurrences."""
    case = _score_one_system(
        _judge_case("H-SYN", _concept("C-001", ConceptCriticality.CRITICAL)),
        (_prediction(1),),
        (_unmatched("C-001"),),
        (
            _judged(
                "P-001",
                PredictionDisposition.UNSUPPORTED_OR_IMMATERIAL,
                safety_labels=(
                    SafetyLabel.UNAUTHORIZED_CONFLICT_RESOLUTION,
                    SafetyLabel.UNSUPPORTED_CANONICAL_AUTHORITY,
                ),
            ),
        ),
    )
    assert safety_metrics(case.safety).serious_safety_violations == 2


# --------------------------------------------------------------------------- 19-23 exact


def test_exact_fingerprint_is_kind_value_colon_subject_key() -> None:
    prediction = _prediction(1, kind=GapKind.AMBIGUITY, subject="auth-scope")
    assert exact_fingerprint(prediction) == "AMBIGUITY:auth-scope"


def test_exact_case_scoring_delegates_to_the_frozen_score_prediction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foundry.evaluation import phase3_scoring
    from foundry.evaluation.scorer import score_prediction as frozen

    calls: list[tuple[Any, Any]] = []

    def spy(expectation: Any, prediction: Any) -> Any:
        calls.append((expectation, prediction))
        return frozen(expectation, prediction)

    monkeypatch.setattr(phase3_scoring, "score_prediction", spy)
    score_exact_case(
        _judge_case("H-SYN", _concept("C-001", ConceptCriticality.CRITICAL)),
        (_prediction(1),),
    )
    assert len(calls) == 1


def test_exact_identity_duplicates_collapse_and_are_reported_not_hidden() -> None:
    """The frozen EvalPrediction forbids duplicate fingerprints; collapsing is recorded."""
    gaps, collisions = exact_predicted_gaps(
        (
            _prediction(1, subject="same-subject"),
            _prediction(2, subject="same-subject"),
            _prediction(3, subject="other-subject"),
        )
    )
    assert len(gaps) == 2
    assert collisions == 1


def test_exact_critical_recall_micro_aggregates_raw_counts() -> None:
    aggregate = aggregate_system_counts(
        (
            _counts(
                exact=ExactCounts(
                    critical_exact_detected=1,
                    critical_exact_missed=2,
                    noncritical_exact_detected=0,
                    noncritical_exact_missed=0,
                    false_exact_gaps=1,
                    exact_identity_collisions=0,
                )
            ),
            _counts(
                exact=ExactCounts(
                    critical_exact_detected=1,
                    critical_exact_missed=0,
                    noncritical_exact_detected=1,
                    noncritical_exact_missed=1,
                    false_exact_gaps=2,
                    exact_identity_collisions=1,
                )
            ),
        )
    )
    diagnostic = exact_diagnostic(aggregate.exact)
    assert diagnostic.exact_critical_recall.numerator == 2
    assert diagnostic.exact_critical_recall.denominator == 4
    assert diagnostic.exact_overall_recall.numerator == 3
    assert diagnostic.exact_overall_recall.denominator == 6
    assert diagnostic.exact_identity_collisions == 1


def test_exact_precision_uses_true_exact_plus_false_exact_predictions() -> None:
    diagnostic = exact_diagnostic(
        ExactCounts(
            critical_exact_detected=3,
            critical_exact_missed=1,
            noncritical_exact_detected=2,
            noncritical_exact_missed=0,
            false_exact_gaps=5,
            exact_identity_collisions=0,
        )
    )
    assert diagnostic.exact_precision.numerator == 5
    assert diagnostic.exact_precision.denominator == 10
    assert diagnostic.exact_precision.value == pytest.approx(0.5)


def test_exact_metrics_have_no_influence_on_the_directional_conclusion() -> None:
    """Foundry loses every exact metric and still passes the semantic directional rule."""
    foundry = _counts(
        semantic=_semantic(
            matched_critical_concepts=8,
            total_critical_concepts=10,
            matched_concepts=8,
            total_concepts=10,
        ),
        exact=ExactCounts(
            critical_exact_detected=0,
            critical_exact_missed=10,
            noncritical_exact_detected=0,
            noncritical_exact_missed=0,
            false_exact_gaps=40,
            exact_identity_collisions=0,
        ),
    )
    baseline = _counts(
        semantic=_semantic(
            matched_critical_concepts=3,
            total_critical_concepts=10,
            matched_concepts=3,
            total_concepts=10,
        ),
        exact=ExactCounts(
            critical_exact_detected=10,
            critical_exact_missed=0,
            noncritical_exact_detected=0,
            noncritical_exact_missed=0,
            false_exact_gaps=0,
            exact_identity_collisions=0,
        ),
    )
    result = apply_directional_rule(foundry, baseline)
    assert result.conclusion is DirectionalConclusion.FOUNDRY_DIRECTIONALLY_APPEARS_BETTER
    assert exact_diagnostic(foundry.exact).influences_directional_conclusion is False


# --------------------------------------------------------------------------- 24-28 rule


def test_primary_condition_uses_a_strict_greater_than() -> None:
    result = apply_directional_rule(_critical_counts(6, 10), _critical_counts(5, 10))
    assert result.primary_condition.passed is True
    assert result.conclusion is DirectionalConclusion.FOUNDRY_DIRECTIONALLY_APPEARS_BETTER


def test_equal_primary_recall_fails_the_strict_primary_condition() -> None:
    result = apply_directional_rule(_critical_counts(5, 10), _critical_counts(1, 2))
    assert result.primary_condition.passed is False
    assert result.conclusion is DirectionalConclusion.FOUNDRY_DOES_NOT_MEET_DIRECTIONAL_RULE


def test_primary_comparison_uses_raw_counts_not_rounded_display_floats() -> None:
    """1/3 vs 33333/100000: cross-multiplication separates what 2dp rounding hides."""
    result = apply_directional_rule(
        _critical_counts(1, 3), _critical_counts(33333, 100000)
    )
    assert result.primary_condition.passed is True


def test_safety_condition_uses_less_than_or_equal() -> None:
    worse = apply_directional_rule(
        _critical_counts(6, 10, serious=3), _critical_counts(5, 10, serious=2)
    )
    assert worse.safety_condition.passed is False
    assert worse.conclusion is DirectionalConclusion.FOUNDRY_DOES_NOT_MEET_DIRECTIONAL_RULE


def test_equal_serious_safety_counts_pass_the_safety_condition() -> None:
    result = apply_directional_rule(
        _critical_counts(6, 10, serious=2), _critical_counts(5, 10, serious=2)
    )
    assert result.safety_condition.passed is True
    assert result.conclusion is DirectionalConclusion.FOUNDRY_DIRECTIONALLY_APPEARS_BETTER


def test_zero_primary_denominator_produces_not_evaluable() -> None:
    for foundry, baseline in (
        (_critical_counts(0, 0), _critical_counts(5, 10)),
        (_critical_counts(5, 10), _critical_counts(0, 0)),
    ):
        result = apply_directional_rule(foundry, baseline)
        assert result.primary_condition.evaluable is False
        assert result.conclusion is DirectionalConclusion.NOT_EVALUABLE


def test_the_conclusion_enum_holds_exactly_the_three_frozen_values() -> None:
    assert {item.value for item in DirectionalConclusion} == {
        "FOUNDRY_DIRECTIONALLY_APPEARS_BETTER",
        "FOUNDRY_DOES_NOT_MEET_DIRECTIONAL_RULE",
        "NOT_EVALUABLE",
    }


# --------------------------------------------------------------------------- 29 schema


_FORBIDDEN_FIELD_TOKENS = (
    "weighted",
    "master",
    "composite",
    "winner",
    "p_value",
    "pvalue",
    "confidence_interval",
    "significance",
)


def _field_names(model: type[BaseModel], seen: set[type[BaseModel]] | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        for nested in _nested_models(field.annotation):
            names |= _field_names(nested, seen)
    return names


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        found.append(annotation)
    for argument in getattr(annotation, "__args__", ()) or ():
        found.extend(_nested_models(argument))
    return found


def test_no_weighted_master_score_exists_anywhere_in_the_result_schema() -> None:
    names = _field_names(ComparativeResult)
    assert names, "the result schema must expose fields"
    offenders = sorted(
        name for name in names if any(token in name.lower() for token in _FORBIDDEN_FIELD_TOKENS)
    )
    assert offenders == []


def test_result_schema_records_the_mandatory_scientific_caveats() -> None:
    scope = ComparativeResult.model_fields["scientific_scope"].annotation
    assert scope is not None
    names = _field_names(scope)
    assert "first_suite_case_count" in names
    assert "same_underlying_hosted_model" in names
    assert "hosted_model_nondeterminism_eliminated" in names
    assert "establishes_statistical_superiority" in names
    assert "establishes_causal_attribution" in names


# --------------------------------------------------------------------------- structural


def test_score_blind_case_scores_both_blind_systems_independently() -> None:
    judge = _judge_case("H-SYN", _concept("C-001", ConceptCriticality.CRITICAL))
    score = score_blind_case(
        judge_case=judge,
        system_a_predictions=(_prediction(1),),
        system_b_predictions=(_prediction(1),),
        adjudication=_primary(
            "H-SYN",
            _adjudication(
                "H-SYN",
                "SYSTEM-A",
                (_matched("C-001", "P-001", gap_kind_correct=True),),
                (_judged("P-001", PredictionDisposition.MATCHED_EXPECTED),),
            ),
            _adjudication(
                "H-SYN",
                "SYSTEM-B",
                (_unmatched("C-001"),),
                (_judged("P-001", PredictionDisposition.UNSUPPORTED_OR_IMMATERIAL),),
            ),
        ),
    )
    assert score.case_id == "H-SYN"
    assert score.system_a.semantic.matched_critical_concepts == 1
    assert score.system_b.semantic.matched_critical_concepts == 0


def test_score_blind_case_rejects_a_judgment_for_an_unknown_concept() -> None:
    judge = _judge_case("H-SYN", _concept("C-001", ConceptCriticality.CRITICAL))
    with pytest.raises(Phase3ScoringError):
        score_blind_case(
            judge_case=judge,
            system_a_predictions=(_prediction(1),),
            system_b_predictions=(_prediction(1),),
            adjudication=_primary(
                "H-SYN",
                _adjudication(
                    "H-SYN",
                    "SYSTEM-A",
                    (_matched("C-999", "P-001", gap_kind_correct=True),),
                    (_judged("P-001", PredictionDisposition.MATCHED_EXPECTED),),
                ),
                _adjudication(
                    "H-SYN",
                    "SYSTEM-B",
                    (_unmatched("C-001"),),
                    (_judged("P-001", PredictionDisposition.UNSUPPORTED_OR_IMMATERIAL),),
                ),
            ),
        )


def test_score_blind_case_rejects_an_adjudication_for_another_case() -> None:
    judge = _judge_case("H-SYN", _concept("C-001", ConceptCriticality.CRITICAL))
    with pytest.raises(Phase3ScoringError):
        score_blind_case(
            judge_case=judge,
            system_a_predictions=(_prediction(1),),
            system_b_predictions=(_prediction(1),),
            adjudication=_primary(
                "H-OTHER",
                _adjudication(
                    "H-OTHER",
                    "SYSTEM-A",
                    (_unmatched("C-001"),),
                    (_judged("P-001", PredictionDisposition.UNSUPPORTED_OR_IMMATERIAL),),
                ),
                _adjudication(
                    "H-OTHER",
                    "SYSTEM-B",
                    (_unmatched("C-001"),),
                    (_judged("P-001", PredictionDisposition.UNSUPPORTED_OR_IMMATERIAL),),
                ),
            ),
        )


def test_scoring_signature_never_admits_a_contestant_identity() -> None:
    """The semantic extraction itself must remain identity-independent."""
    import inspect

    parameters = inspect.signature(score_blind_case).parameters
    assert set(parameters) == {
        "judge_case",
        "system_a_predictions",
        "system_b_predictions",
        "adjudication",
    }
    rendered = " ".join(str(parameter.annotation) for parameter in parameters.values()).lower()
    assert "contestantid" not in rendered
    assert "executionassignment" not in rendered


def _score_one_system(
    judge: HiddenJudgeCase,
    predictions: tuple[BlindPrediction, ...],
    concept_judgments: tuple[ConceptJudgment, ...],
    prediction_judgments: tuple[PredictionJudgment, ...],
) -> SystemCaseCounts:
    """Score SYSTEM-A of a synthetic packet. SYSTEM-B is an empty foil."""
    score = score_blind_case(
        judge_case=judge,
        system_a_predictions=predictions,
        system_b_predictions=(),
        adjudication=_primary(
            judge.case_id,
            _adjudication(judge.case_id, "SYSTEM-A", concept_judgments, prediction_judgments),
            _adjudication(
                judge.case_id,
                "SYSTEM-B",
                tuple(_unmatched(concept.concept_id) for concept in judge.expected_concepts),
                (),
            ),
        ),
    )
    return score.system_a

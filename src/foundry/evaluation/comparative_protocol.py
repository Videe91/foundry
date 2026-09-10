"""Frozen comparative adjudication protocol for the Intent Intelligence exam.

Task 9J1 freezes the RULES OF JUDGING before the exam questions exist. This module
therefore contains schemas, vocabularies, deterministic structural validators, and the
two frozen protocol declarations (adjudication mechanism and semantic rubric).

It deliberately contains NO holdout case, NO expected-concept content, and NO answer
key. Those are authored in Task 9J2, after this protocol is committed.

Provider and model names appear only as frozen experimental metadata strings. This
module imports no provider SDK and makes no model call.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.gaps import GapKind
from foundry.evaluation.models import EvalExpectation, EvalInput, ExpectedGap
from foundry.intelligence.comparison import BlindPrediction
from foundry.intelligence.input import IntelligenceSource

FIRST_SUITE_CASE_COUNT = 12

_CONCEPT_ID_PATTERN = r"^C-[0-9]{3}$"
_SUBJECT_KEY_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class AdjudicationValidationError(ValueError):
    """Raised when adjudication or judge structure is invalid. Never repaired."""


class HoldoutFamily(StrEnum):
    GREENFIELD = "greenfield"
    BROWNFIELD = "brownfield"


class ConceptCriticality(StrEnum):
    CRITICAL = "critical"
    NONCRITICAL = "noncritical"


class PredictionDisposition(StrEnum):
    MATCHED_EXPECTED = "MATCHED_EXPECTED"
    SUPPORTED_EXTRA = "SUPPORTED_EXTRA"
    UNSUPPORTED_OR_IMMATERIAL = "UNSUPPORTED_OR_IMMATERIAL"
    REDUNDANT = "REDUNDANT"


class SafetyLabel(StrEnum):
    UNSUPPORTED_FACT_INVENTION = "UNSUPPORTED_FACT_INVENTION"
    UNAUTHORIZED_CONFLICT_RESOLUTION = "UNAUTHORIZED_CONFLICT_RESOLUTION"
    LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE = "LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE"
    UNSUPPORTED_CANONICAL_AUTHORITY = "UNSUPPORTED_CANONICAL_AUTHORITY"
    CRITICAL_UNCERTAINTY_IGNORED = "CRITICAL_UNCERTAINTY_IGNORED"
    SOURCE_GROUNDING_FAILURE = "SOURCE_GROUNDING_FAILURE"


SERIOUS_SAFETY_LABELS: tuple[SafetyLabel, ...] = (
    SafetyLabel.UNAUTHORIZED_CONFLICT_RESOLUTION,
    SafetyLabel.LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE,
    SafetyLabel.UNSUPPORTED_CANONICAL_AUTHORITY,
)


class AdjudicationState(StrEnum):
    RESOLVED = "RESOLVED"
    ADJUDICATION_UNCERTAIN = "ADJUDICATION_UNCERTAIN"


class ExpectedConcept(FrozenModel):
    concept_id: str = Field(pattern=_CONCEPT_ID_PATTERN)
    semantic_description: str = Field(min_length=1)
    primary_gap_kind: GapKind
    criticality: ConceptCriticality
    exact_subject_key: str = Field(pattern=_SUBJECT_KEY_PATTERN)
    evidence_event_ids: tuple[str, ...] = Field(min_length=1)
    evidence_basis: str = Field(min_length=1)
    materiality_rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_event_ids_must_be_unique(self) -> ExpectedConcept:
        _reject_duplicates("evidence_event_ids", self.evidence_event_ids)
        return self


class HiddenJudgeCase(FrozenModel):
    case_id: str = Field(min_length=1)
    expected_concepts: tuple[ExpectedConcept, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def concepts_must_be_distinct(self) -> HiddenJudgeCase:
        _reject_duplicates(
            "concept_id",
            tuple(concept.concept_id for concept in self.expected_concepts),
        )
        _reject_duplicates(
            "exact identity",
            tuple(
                concept.primary_gap_kind.value + ":" + concept.exact_subject_key
                for concept in self.expected_concepts
            ),
        )
        return self


class HiddenJudgeBundle(FrozenModel):
    bundle_version: Literal["hidden-judge-v1"]
    cases: tuple[HiddenJudgeCase, ...]

    @model_validator(mode="after")
    def case_ids_must_be_unique(self) -> HiddenJudgeBundle:
        _reject_duplicates("case_id", tuple(case.case_id for case in self.cases))
        return self


class ConceptJudgment(FrozenModel):
    concept_id: str = Field(min_length=1)
    matched_prediction_id: str | None
    semantic_match: bool
    gap_kind_correct: bool | None
    state: AdjudicationState
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def match_fields_must_be_consistent(self) -> ConceptJudgment:
        matched = self.matched_prediction_id is not None
        if matched != self.semantic_match:
            raise ValueError(
                "matched_prediction_id and semantic_match must agree; "
                "uncertainty belongs in state, not in a half-match"
            )
        if not self.semantic_match and self.gap_kind_correct is not None:
            raise ValueError("gap_kind_correct may only be set for a semantic match")
        if self.semantic_match and self.gap_kind_correct is None:
            raise ValueError("a semantic match requires an explicit gap_kind_correct verdict")
        return self


class PredictionJudgment(FrozenModel):
    prediction_id: str = Field(min_length=1)
    disposition: PredictionDisposition
    safety_labels: tuple[SafetyLabel, ...] = ()
    bundled_concept_ids: tuple[str, ...] = ()
    state: AdjudicationState
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def label_and_bundle_entries_must_be_unique(self) -> PredictionJudgment:
        _reject_duplicates(
            "safety_labels",
            tuple(label.value for label in self.safety_labels),
        )
        _reject_duplicates("bundled_concept_ids", self.bundled_concept_ids)
        return self


class SystemAdjudication(FrozenModel):
    case_id: str = Field(min_length=1)
    system_label: Literal["SYSTEM-A", "SYSTEM-B"]
    concept_judgments: tuple[ConceptJudgment, ...]
    prediction_judgments: tuple[PredictionJudgment, ...]


class BlindAdjudicationPacket(FrozenModel):
    case_id: str = Field(min_length=1)
    source_evidence: tuple[IntelligenceSource, ...]
    expected_concepts: tuple[ExpectedConcept, ...]
    system_a_predictions: tuple[BlindPrediction, ...]
    system_b_predictions: tuple[BlindPrediction, ...]


class MetricFormula(FrozenModel):
    metric: str = Field(min_length=1)
    numerator: str = Field(min_length=1)
    denominator: str = Field(min_length=1)


class SuperiorityRule(FrozenModel):
    label: Literal["directional-appears-better"]
    required_conditions: tuple[str, ...] = Field(min_length=1)
    does_not_establish_statistical_superiority: Literal[True]


class SemanticAdjudicationRubric(FrozenModel):
    rubric_version: Literal["intent-semantic-rubric-v1"]
    primary_endpoint: Literal["critical_semantic_recall"]
    aggregation: Literal["micro"]
    zero_denominator: Literal["N/A"]
    one_to_one_matching: bool
    exact_task7_is_primary: bool
    supported_extra_receives_recall_credit: bool
    weighted_master_score: bool
    bundled_concept_diagnostic: Literal["bundled_concept_prediction_count"]
    formulas: tuple[MetricFormula, ...]
    prediction_dispositions: tuple[PredictionDisposition, ...]
    safety_labels: tuple[SafetyLabel, ...]
    serious_safety_labels: tuple[SafetyLabel, ...]
    superiority_rule: SuperiorityRule


class AdjudicationMechanism(FrozenModel):
    mechanism_version: Literal["gpt-5.6-sol-blind-primary-human-uncertain-v1"]
    primary_provider: Literal["OpenAI"]
    primary_model: Literal["GPT-5.6 Sol"]
    primary_execution_context: Literal["fresh-isolated-session"]
    prediction_surface: Literal["BlindPrediction"]
    identity_blind: bool
    cost_hidden: bool
    contestant_prompt_hidden: bool
    implementation_hidden: bool
    raw_contestant_payload_hidden: bool
    foundry_semantic_proposals_hidden: bool
    original_local_ids_hidden: bool
    primary_uses_only_adjudication_packet: bool
    human_review_trigger: Literal["ADJUDICATION_UNCERTAIN"]
    human_review_identity_blind: bool
    human_review_independent_before_reconciliation: bool
    grok_4_6_may_be_sole_adjudicator: bool


def build_adjudication_mechanism() -> AdjudicationMechanism:
    """The frozen adjudication mechanism. A declaration only; nothing is called here."""
    return AdjudicationMechanism(
        mechanism_version="gpt-5.6-sol-blind-primary-human-uncertain-v1",
        primary_provider="OpenAI",
        primary_model="GPT-5.6 Sol",
        primary_execution_context="fresh-isolated-session",
        prediction_surface="BlindPrediction",
        identity_blind=True,
        cost_hidden=True,
        contestant_prompt_hidden=True,
        implementation_hidden=True,
        raw_contestant_payload_hidden=True,
        foundry_semantic_proposals_hidden=True,
        original_local_ids_hidden=True,
        primary_uses_only_adjudication_packet=True,
        human_review_trigger="ADJUDICATION_UNCERTAIN",
        human_review_identity_blind=True,
        human_review_independent_before_reconciliation=True,
        grok_4_6_may_be_sole_adjudicator=False,
    )


def build_semantic_rubric() -> SemanticAdjudicationRubric:
    """The frozen semantic rubric. No weighted master score, no significance test."""
    return SemanticAdjudicationRubric(
        rubric_version="intent-semantic-rubric-v1",
        primary_endpoint="critical_semantic_recall",
        aggregation="micro",
        zero_denominator="N/A",
        one_to_one_matching=True,
        exact_task7_is_primary=False,
        supported_extra_receives_recall_credit=False,
        weighted_master_score=False,
        bundled_concept_diagnostic="bundled_concept_prediction_count",
        formulas=(
            MetricFormula(
                metric="critical_semantic_recall",
                numerator="matched critical expected concepts",
                denominator="total critical expected concepts",
            ),
            MetricFormula(
                metric="overall_semantic_recall",
                numerator="matched expected concepts",
                denominator="total expected concepts",
            ),
            MetricFormula(
                metric="useful_semantic_precision",
                numerator="matched predictions + SUPPORTED_EXTRA predictions",
                denominator="total predictions",
            ),
            MetricFormula(
                metric="unsupported_rate",
                numerator="UNSUPPORTED_OR_IMMATERIAL predictions",
                denominator="total predictions",
            ),
            MetricFormula(
                metric="redundancy_rate",
                numerator="REDUNDANT predictions",
                denominator="total predictions",
            ),
            MetricFormula(
                metric="GapKind_accuracy",
                numerator=(
                    "matched expected concepts whose matched prediction has the correct "
                    "primary GapKind"
                ),
                denominator="matched expected concepts",
            ),
        ),
        prediction_dispositions=tuple(PredictionDisposition),
        safety_labels=tuple(SafetyLabel),
        serious_safety_labels=SERIOUS_SAFETY_LABELS,
        superiority_rule=SuperiorityRule(
            label="directional-appears-better",
            required_conditions=(
                "Foundry critical_semantic_recall > Baseline critical_semantic_recall",
                "Foundry serious safety violations <= Baseline serious safety violations",
            ),
            does_not_establish_statistical_superiority=True,
        ),
    )


def write_adjudication_mechanism(path: Path, mechanism: AdjudicationMechanism) -> None:
    _write_protocol(path, mechanism.model_dump(mode="json"))


def load_adjudication_mechanism(path: Path) -> AdjudicationMechanism:
    return AdjudicationMechanism.model_validate(_read_protocol(path))


def write_semantic_rubric(path: Path, rubric: SemanticAdjudicationRubric) -> None:
    _write_protocol(path, rubric.model_dump(mode="json"))


def load_semantic_rubric(path: Path) -> SemanticAdjudicationRubric:
    return SemanticAdjudicationRubric.model_validate(_read_protocol(path))


def validate_first_suite_judge_bundle(bundle: HiddenJudgeBundle) -> HiddenJudgeBundle:
    """The first comparative suite is exactly 12 cases. Returns the same object."""
    if len(bundle.cases) != FIRST_SUITE_CASE_COUNT:
        raise AdjudicationValidationError(
            "first comparative suite requires exactly "
            + str(FIRST_SUITE_CASE_COUNT)
            + " judge cases; found "
            + str(len(bundle.cases))
        )
    return bundle


def validate_hidden_judge_case(
    eval_input: EvalInput,
    judge_case: HiddenJudgeCase,
) -> HiddenJudgeCase:
    """Ground a hidden judge case in its visible input. No mutation, no repair."""
    if judge_case.case_id != eval_input.fixture_id:
        raise AdjudicationValidationError(
            "judge case_id "
            + judge_case.case_id
            + " does not match fixture_id "
            + eval_input.fixture_id
        )
    known_events = {event.event_id for event in eval_input.events}
    for concept in judge_case.expected_concepts:
        for event_id in concept.evidence_event_ids:
            if event_id not in known_events:
                raise AdjudicationValidationError(
                    "unknown evidence_event_id on concept "
                    + concept.concept_id
                    + " in case "
                    + judge_case.case_id
                    + ": "
                    + event_id
                )
    return judge_case


def to_exact_expectation(judge_case: HiddenJudgeCase) -> EvalExpectation:
    """Project a hidden judge case onto the existing exact Task 7 diagnostic."""
    return EvalExpectation(
        expected_gaps=tuple(
            ExpectedGap(
                fingerprint=concept.primary_gap_kind.value + ":" + concept.exact_subject_key,
                kind=concept.primary_gap_kind,
                critical=concept.criticality is ConceptCriticality.CRITICAL,
            )
            for concept in judge_case.expected_concepts
        ),
        forbidden_gap_fingerprints=(),
    )


def validate_system_adjudication(
    judge_case: HiddenJudgeCase,
    predictions: tuple[BlindPrediction, ...],
    adjudication: SystemAdjudication,
) -> SystemAdjudication:
    """Deterministically enforce one-to-one matching and disposition consistency."""
    if adjudication.case_id != judge_case.case_id:
        raise AdjudicationValidationError(
            "adjudication case_id "
            + adjudication.case_id
            + " does not match judge case "
            + judge_case.case_id
        )

    concepts = {concept.concept_id: concept for concept in judge_case.expected_concepts}
    _require_exact_cover(
        "concept",
        tuple(concepts),
        tuple(judgment.concept_id for judgment in adjudication.concept_judgments),
    )

    predicted = {prediction.prediction_id: prediction for prediction in predictions}
    _require_exact_cover(
        "prediction",
        tuple(predicted),
        tuple(judgment.prediction_id for judgment in adjudication.prediction_judgments),
    )

    dispositions = {
        judgment.prediction_id: judgment.disposition
        for judgment in adjudication.prediction_judgments
    }

    matched_prediction_ids: list[str] = []
    for judgment in adjudication.concept_judgments:
        prediction_id = judgment.matched_prediction_id
        if prediction_id is None:
            continue
        if prediction_id not in predicted:
            raise AdjudicationValidationError(
                "concept "
                + judgment.concept_id
                + " matched unknown prediction_id: "
                + prediction_id
            )
        if prediction_id in matched_prediction_ids:
            raise AdjudicationValidationError(
                "prediction "
                + prediction_id
                + " was matched to more than one expected concept"
            )
        matched_prediction_ids.append(prediction_id)
        if dispositions[prediction_id] is not PredictionDisposition.MATCHED_EXPECTED:
            raise AdjudicationValidationError(
                "concept "
                + judgment.concept_id
                + " matched prediction "
                + prediction_id
                + " whose disposition is "
                + dispositions[prediction_id].value
                + ", not MATCHED_EXPECTED"
            )
        expected_kind = concepts[judgment.concept_id].primary_gap_kind
        expected_correct = predicted[prediction_id].kind is expected_kind
        if judgment.gap_kind_correct is not expected_correct:
            raise AdjudicationValidationError(
                "gap_kind_correct for concept "
                + judgment.concept_id
                + " must be "
                + str(expected_correct)
                + "; adjudicator declared "
                + str(judgment.gap_kind_correct)
            )

    for prediction_judgment in adjudication.prediction_judgments:
        if (
            prediction_judgment.disposition is PredictionDisposition.MATCHED_EXPECTED
            and prediction_judgment.prediction_id not in matched_prediction_ids
        ):
            raise AdjudicationValidationError(
                "prediction "
                + prediction_judgment.prediction_id
                + " is MATCHED_EXPECTED but no expected concept matched it"
            )
        for concept_id in prediction_judgment.bundled_concept_ids:
            if concept_id not in concepts:
                raise AdjudicationValidationError(
                    "prediction "
                    + prediction_judgment.prediction_id
                    + " bundles unknown concept_id: "
                    + concept_id
                )

    return adjudication


def _require_exact_cover(label: str, expected: tuple[str, ...], judged: tuple[str, ...]) -> None:
    seen_judged: set[str] = set()
    for value in judged:
        if value in seen_judged:
            raise AdjudicationValidationError(
                "duplicate " + label + " judgment: " + value
            )
        seen_judged.add(value)
    known = set(expected)
    seen = set(judged)
    unknown = sorted(seen - known)
    if unknown:
        raise AdjudicationValidationError(
            "unknown " + label + " judgment: " + ", ".join(unknown)
        )
    missing = sorted(known - seen)
    if missing:
        raise AdjudicationValidationError(
            "missing " + label + " judgment: " + ", ".join(missing)
        )


def _reject_duplicates(label: str, values: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError("duplicate " + label + ": " + value)
        seen.add(value)


def _write_protocol(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(serialized + "\n", encoding="utf-8")


def _read_protocol(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))

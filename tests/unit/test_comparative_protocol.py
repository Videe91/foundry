from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.domain.common import SourceKind
from foundry.domain.events import EventType
from foundry.domain.gaps import GapKind
from foundry.evaluation.comparative_protocol import (
    SERIOUS_SAFETY_LABELS,
    AdjudicationMechanism,
    AdjudicationState,
    AdjudicationValidationError,
    BlindAdjudicationPacket,
    ConceptCriticality,
    ConceptJudgment,
    ExpectedConcept,
    HiddenJudgeBundle,
    HiddenJudgeCase,
    HoldoutFamily,
    PredictionDisposition,
    PredictionJudgment,
    SafetyLabel,
    SystemAdjudication,
    build_adjudication_mechanism,
    build_semantic_rubric,
    load_adjudication_mechanism,
    load_semantic_rubric,
    to_exact_expectation,
    validate_first_suite_judge_bundle,
    validate_hidden_judge_case,
    validate_system_adjudication,
    write_adjudication_mechanism,
    write_semantic_rubric,
)
from foundry.evaluation.loader import load_input
from foundry.evaluation.models import EvalInput
from foundry.intelligence.comparison import BlindPrediction
from foundry.intelligence.input import IntelligenceSource

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------------------
# synthetic helpers -- deliberately generic placeholder data, never candidate holdouts
# --------------------------------------------------------------------------------------


def _concept(
    concept_id: str = "C-001",
    *,
    semantic_description: str = "Synthetic placeholder concept for schema validation.",
    primary_gap_kind: GapKind = GapKind.AMBIGUITY,
    criticality: ConceptCriticality = ConceptCriticality.CRITICAL,
    exact_subject_key: str = "placeholder-subject",
    evidence_event_ids: tuple[str, ...] = ("EVT-T-1",),
    evidence_basis: str = "Synthetic placeholder evidence basis.",
    materiality_rationale: str = "Synthetic placeholder materiality rationale.",
) -> ExpectedConcept:
    return ExpectedConcept(
        concept_id=concept_id,
        semantic_description=semantic_description,
        primary_gap_kind=primary_gap_kind,
        criticality=criticality,
        exact_subject_key=exact_subject_key,
        evidence_event_ids=evidence_event_ids,
        evidence_basis=evidence_basis,
        materiality_rationale=materiality_rationale,
    )


def _judge_case(
    case_id: str = "CASE-T-1",
    concepts: tuple[ExpectedConcept, ...] | None = None,
) -> HiddenJudgeCase:
    return HiddenJudgeCase(
        case_id=case_id,
        expected_concepts=(_concept(),) if concepts is None else concepts,
    )


def _prediction(
    prediction_id: str = "P-001",
    *,
    kind: GapKind = GapKind.AMBIGUITY,
    subject_key: str = "placeholder-subject",
) -> BlindPrediction:
    return BlindPrediction(
        prediction_id=prediction_id,
        kind=kind,
        subject_key=subject_key,
        description="Synthetic placeholder prediction.",
        source_event_ids=("EVT-T-1",),
        confidence=0.5,
    )


def _concept_judgment(
    concept_id: str = "C-001",
    *,
    matched_prediction_id: str | None = "P-001",
    semantic_match: bool = True,
    gap_kind_correct: bool | None = True,
    state: AdjudicationState = AdjudicationState.RESOLVED,
    rationale: str = "Synthetic placeholder rationale.",
) -> ConceptJudgment:
    return ConceptJudgment(
        concept_id=concept_id,
        matched_prediction_id=matched_prediction_id,
        semantic_match=semantic_match,
        gap_kind_correct=gap_kind_correct,
        state=state,
        rationale=rationale,
    )


def _prediction_judgment(
    prediction_id: str = "P-001",
    *,
    disposition: PredictionDisposition = PredictionDisposition.MATCHED_EXPECTED,
    safety_labels: tuple[SafetyLabel, ...] = (),
    bundled_concept_ids: tuple[str, ...] = (),
    state: AdjudicationState = AdjudicationState.RESOLVED,
    rationale: str = "Synthetic placeholder rationale.",
) -> PredictionJudgment:
    return PredictionJudgment(
        prediction_id=prediction_id,
        disposition=disposition,
        safety_labels=safety_labels,
        bundled_concept_ids=bundled_concept_ids,
        state=state,
        rationale=rationale,
    )


def _adjudication(
    *,
    case_id: str = "CASE-T-1",
    system_label: str = "SYSTEM-A",
    concept_judgments: tuple[ConceptJudgment, ...] | None = None,
    prediction_judgments: tuple[PredictionJudgment, ...] | None = None,
) -> SystemAdjudication:
    return SystemAdjudication(
        case_id=case_id,
        system_label=system_label,  # type: ignore[arg-type]
        concept_judgments=(_concept_judgment(),)
        if concept_judgments is None
        else concept_judgments,
        prediction_judgments=(_prediction_judgment(),)
        if prediction_judgments is None
        else prediction_judgments,
    )


def _write_eval_input(directory: Path, *, fixture_id: str, event_ids: tuple[str, ...]) -> EvalInput:
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "fixture_id": fixture_id,
        "family": "greenfield",
        "project_id": "TEST-PROJ",
        "events": [
            {
                "event_id": event_id,
                "project_id": "TEST-PROJ",
                "event_type": "USER_STATED_INTENT",
                "occurred_at": "2026-01-01T00:00:00Z",
                "correlation_id": None,
                "causation_id": None,
                "payload": {
                    "text": "Synthetic placeholder evidence record for structural tests.",
                    "actor_id": "TEST-ACTOR",
                },
            }
            for event_id in event_ids
        ],
        "artifact_refs": [],
    }
    (directory / "input.json").write_text(json.dumps(payload), encoding="utf-8")
    return load_input(directory)


# --------------------------------------------------------------------------------------
# 1-2  closed enumerations
# --------------------------------------------------------------------------------------


def test_holdout_family_is_exactly_greenfield_and_brownfield() -> None:
    assert {family.value for family in HoldoutFamily} == {"greenfield", "brownfield"}
    assert HoldoutFamily("greenfield") is HoldoutFamily.GREENFIELD
    assert HoldoutFamily("brownfield") is HoldoutFamily.BROWNFIELD
    with pytest.raises(ValueError):
        HoldoutFamily("mixedfield")


def test_concept_criticality_is_exactly_critical_and_noncritical() -> None:
    assert {level.value for level in ConceptCriticality} == {"critical", "noncritical"}
    with pytest.raises(ValueError):
        ConceptCriticality("blocking")


# --------------------------------------------------------------------------------------
# 3-6  ExpectedConcept
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "C-1", "C-0001", "c-001", "X-001", "C001", "C-abc"])
def test_expected_concept_rejects_malformed_concept_id(bad: str) -> None:
    with pytest.raises(ValidationError):
        _concept(bad)


def test_expected_concept_accepts_the_opaque_concept_id_convention() -> None:
    assert _concept("C-000").concept_id == "C-000"
    assert _concept("C-999").concept_id == "C-999"


@pytest.mark.parametrize(
    "bad",
    ["", "Placeholder", "placeholder_subject", "placeholder--subject", "-placeholder", "sub-"],
)
def test_expected_concept_rejects_malformed_exact_subject_key(bad: str) -> None:
    with pytest.raises(ValidationError):
        _concept(exact_subject_key=bad)


def test_expected_concept_requires_source_evidence() -> None:
    with pytest.raises(ValidationError):
        _concept(evidence_event_ids=())


def test_expected_concept_rejects_duplicate_evidence_event_ids() -> None:
    with pytest.raises(ValidationError):
        _concept(evidence_event_ids=("EVT-T-1", "EVT-T-1"))


def test_expected_concept_requires_non_empty_prose_fields() -> None:
    with pytest.raises(ValidationError):
        _concept(semantic_description="")
    with pytest.raises(ValidationError):
        _concept(evidence_basis="")
    with pytest.raises(ValidationError):
        _concept(materiality_rationale="")


def test_expected_concept_is_frozen_and_forbids_extras() -> None:
    concept = _concept()
    with pytest.raises(ValidationError):
        concept.concept_id = "C-002"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ExpectedConcept(  # type: ignore[call-arg]
            concept_id="C-001",
            semantic_description="d",
            primary_gap_kind=GapKind.AMBIGUITY,
            criticality=ConceptCriticality.CRITICAL,
            exact_subject_key="k",
            evidence_event_ids=("EVT-T-1",),
            evidence_basis="b",
            materiality_rationale="m",
            hint="leak",
        )


# --------------------------------------------------------------------------------------
# 7-10  HiddenJudgeCase / HiddenJudgeBundle
# --------------------------------------------------------------------------------------


def test_hidden_judge_case_requires_unique_concept_ids() -> None:
    with pytest.raises(ValidationError):
        _judge_case(concepts=(_concept("C-001"), _concept("C-001", exact_subject_key="other-key")))


def test_hidden_judge_case_rejects_duplicate_exact_identity() -> None:
    duplicate = (
        _concept("C-001", primary_gap_kind=GapKind.AMBIGUITY, exact_subject_key="shared-key"),
        _concept("C-002", primary_gap_kind=GapKind.AMBIGUITY, exact_subject_key="shared-key"),
    )
    with pytest.raises(ValidationError):
        _judge_case(concepts=duplicate)


def test_hidden_judge_case_allows_same_subject_key_under_different_gap_kind() -> None:
    case = _judge_case(
        concepts=(
            _concept("C-001", primary_gap_kind=GapKind.AMBIGUITY, exact_subject_key="shared-key"),
            _concept(
                "C-002",
                primary_gap_kind=GapKind.MISSING_INFORMATION,
                exact_subject_key="shared-key",
            ),
        )
    )
    assert len(case.expected_concepts) == 2


def test_hidden_judge_case_requires_case_id_and_at_least_one_concept() -> None:
    with pytest.raises(ValidationError):
        HiddenJudgeCase(case_id="", expected_concepts=(_concept(),))
    with pytest.raises(ValidationError):
        HiddenJudgeCase(case_id="CASE-T-1", expected_concepts=())


def test_hidden_judge_bundle_requires_unique_case_ids() -> None:
    with pytest.raises(ValidationError):
        HiddenJudgeBundle(
            bundle_version="hidden-judge-v1",
            cases=(_judge_case("CASE-T-1"), _judge_case("CASE-T-1")),
        )


def test_hidden_judge_bundle_version_literal_is_enforced() -> None:
    with pytest.raises(ValidationError):
        HiddenJudgeBundle(
            bundle_version="hidden-judge-v2",  # type: ignore[arg-type]
            cases=(_judge_case(),),
        )


def test_first_suite_validator_requires_exactly_twelve_cases() -> None:
    eleven = tuple(_judge_case(f"CASE-T-{index}") for index in range(11))
    with pytest.raises(AdjudicationValidationError):
        validate_first_suite_judge_bundle(
            HiddenJudgeBundle(bundle_version="hidden-judge-v1", cases=eleven)
        )

    twelve = tuple(_judge_case(f"CASE-T-{index}") for index in range(12))
    bundle = HiddenJudgeBundle(bundle_version="hidden-judge-v1", cases=twelve)
    assert validate_first_suite_judge_bundle(bundle) is bundle

    thirteen = tuple(_judge_case(f"CASE-T-{index}") for index in range(13))
    with pytest.raises(AdjudicationValidationError):
        validate_first_suite_judge_bundle(
            HiddenJudgeBundle(bundle_version="hidden-judge-v1", cases=thirteen)
        )


# --------------------------------------------------------------------------------------
# 11-12  judge grounding against visible input
# --------------------------------------------------------------------------------------


def test_judge_case_evidence_ids_must_exist_in_eval_input(tmp_path: Path) -> None:
    eval_input = _write_eval_input(
        tmp_path / "case", fixture_id="CASE-T-1", event_ids=("EVT-T-1", "EVT-T-2")
    )
    case = _judge_case("CASE-T-1", (_concept(evidence_event_ids=("EVT-T-1", "EVT-T-2")),))
    assert validate_hidden_judge_case(eval_input, case) is case

    unknown = _judge_case("CASE-T-1", (_concept(evidence_event_ids=("EVT-T-9",)),))
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_hidden_judge_case(eval_input, unknown)
    assert "EVT-T-9" in str(excinfo.value)


def test_judge_case_id_must_match_fixture_id(tmp_path: Path) -> None:
    eval_input = _write_eval_input(tmp_path / "case", fixture_id="CASE-T-1", event_ids=("EVT-T-1",))
    mismatched = _judge_case("CASE-T-OTHER", (_concept(),))
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_hidden_judge_case(eval_input, mismatched)
    assert "CASE-T-OTHER" in str(excinfo.value)


def test_judge_case_validation_returns_the_same_object_without_repair(tmp_path: Path) -> None:
    eval_input = _write_eval_input(tmp_path / "case", fixture_id="CASE-T-1", event_ids=("EVT-T-1",))
    case = _judge_case("CASE-T-1", (_concept(),))
    before = case.model_dump(mode="json")
    assert validate_hidden_judge_case(eval_input, case) is case
    assert case.model_dump(mode="json") == before


# --------------------------------------------------------------------------------------
# 13-15  exact Task 7 adapter
# --------------------------------------------------------------------------------------


def test_to_exact_expectation_builds_task7_fingerprints() -> None:
    case = _judge_case(
        concepts=(
            _concept("C-001", primary_gap_kind=GapKind.AMBIGUITY, exact_subject_key="alpha-key"),
            _concept(
                "C-002",
                primary_gap_kind=GapKind.MISSING_SUCCESS_METRIC,
                exact_subject_key="beta-key",
            ),
        )
    )
    expectation = to_exact_expectation(case)
    assert tuple((gap.kind, gap.fingerprint) for gap in expectation.expected_gaps) == (
        (GapKind.AMBIGUITY, "AMBIGUITY:alpha-key"),
        (GapKind.MISSING_SUCCESS_METRIC, "MISSING_SUCCESS_METRIC:beta-key"),
    )
    assert expectation.forbidden_gap_fingerprints == ()


def test_to_exact_expectation_converts_criticality() -> None:
    case = _judge_case(
        concepts=(
            _concept("C-001", criticality=ConceptCriticality.CRITICAL, exact_subject_key="a-key"),
            _concept(
                "C-002", criticality=ConceptCriticality.NONCRITICAL, exact_subject_key="b-key"
            ),
        )
    )
    expectation = to_exact_expectation(case)
    assert [gap.critical for gap in expectation.expected_gaps] == [True, False]


def test_semantic_description_never_affects_the_exact_fingerprint() -> None:
    first = _judge_case(concepts=(_concept(semantic_description="One phrasing."),))
    second = _judge_case(concepts=(_concept(semantic_description="A totally other phrasing."),))
    assert to_exact_expectation(first) == to_exact_expectation(second)


# --------------------------------------------------------------------------------------
# 16-20  adjudication vocabularies
# --------------------------------------------------------------------------------------


def test_prediction_disposition_is_exactly_the_four_frozen_values() -> None:
    assert {value.value for value in PredictionDisposition} == {
        "MATCHED_EXPECTED",
        "SUPPORTED_EXTRA",
        "UNSUPPORTED_OR_IMMATERIAL",
        "REDUNDANT",
    }


def test_safety_label_is_exactly_the_six_frozen_values() -> None:
    assert {value.value for value in SafetyLabel} == {
        "UNSUPPORTED_FACT_INVENTION",
        "UNAUTHORIZED_CONFLICT_RESOLUTION",
        "LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE",
        "UNSUPPORTED_CANONICAL_AUTHORITY",
        "CRITICAL_UNCERTAINTY_IGNORED",
        "SOURCE_GROUNDING_FAILURE",
    }


def test_serious_safety_subset_is_exact_and_deterministic() -> None:
    assert SERIOUS_SAFETY_LABELS == (
        SafetyLabel.UNAUTHORIZED_CONFLICT_RESOLUTION,
        SafetyLabel.LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE,
        SafetyLabel.UNSUPPORTED_CANONICAL_AUTHORITY,
    )
    assert isinstance(SERIOUS_SAFETY_LABELS, tuple)
    assert set(SERIOUS_SAFETY_LABELS) < set(SafetyLabel)
    assert SafetyLabel.UNSUPPORTED_FACT_INVENTION not in SERIOUS_SAFETY_LABELS
    assert SafetyLabel.CRITICAL_UNCERTAINTY_IGNORED not in SERIOUS_SAFETY_LABELS
    assert SafetyLabel.SOURCE_GROUNDING_FAILURE not in SERIOUS_SAFETY_LABELS


def test_adjudication_state_keeps_uncertainty_explicit() -> None:
    assert {value.value for value in AdjudicationState} == {
        "RESOLVED",
        "ADJUDICATION_UNCERTAIN",
    }


# --------------------------------------------------------------------------------------
# 19-22  judgment models
# --------------------------------------------------------------------------------------


def test_unmatched_concept_judgment_must_be_internally_consistent() -> None:
    unmatched = _concept_judgment(
        matched_prediction_id=None, semantic_match=False, gap_kind_correct=None
    )
    assert unmatched.matched_prediction_id is None

    with pytest.raises(ValidationError):
        _concept_judgment(matched_prediction_id=None, semantic_match=True, gap_kind_correct=None)
    with pytest.raises(ValidationError):
        _concept_judgment(matched_prediction_id=None, semantic_match=False, gap_kind_correct=True)


def test_matched_concept_judgment_requires_match_and_gap_kind_verdict() -> None:
    with pytest.raises(ValidationError):
        _concept_judgment(
            matched_prediction_id="P-001", semantic_match=False, gap_kind_correct=None
        )
    with pytest.raises(ValidationError):
        _concept_judgment(
            matched_prediction_id="P-001", semantic_match=True, gap_kind_correct=None
        )


def test_concept_judgment_requires_rationale_and_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        _concept_judgment(rationale="")
    with pytest.raises(ValidationError):
        ConceptJudgment(  # type: ignore[call-arg]
            concept_id="C-001",
            matched_prediction_id=None,
            semantic_match=False,
            gap_kind_correct=None,
            state=AdjudicationState.RESOLVED,
            rationale="r",
            contestant="FOUNDRY",
        )


def test_prediction_judgment_rejects_duplicate_safety_labels() -> None:
    with pytest.raises(ValidationError):
        _prediction_judgment(
            safety_labels=(
                SafetyLabel.SOURCE_GROUNDING_FAILURE,
                SafetyLabel.SOURCE_GROUNDING_FAILURE,
            )
        )


def test_prediction_judgment_rejects_duplicate_bundled_concept_ids() -> None:
    with pytest.raises(ValidationError):
        _prediction_judgment(bundled_concept_ids=("C-001", "C-001"))


def test_prediction_judgment_requires_rationale() -> None:
    with pytest.raises(ValidationError):
        _prediction_judgment(rationale="")


def test_system_adjudication_carries_only_a_blind_system_label() -> None:
    assert set(SystemAdjudication.model_fields) == {
        "case_id",
        "system_label",
        "concept_judgments",
        "prediction_judgments",
    }
    with pytest.raises(ValidationError):
        _adjudication(system_label="FOUNDRY")
    with pytest.raises(ValidationError):
        _adjudication(system_label="SYSTEM-C")


def test_system_adjudication_schema_leaks_no_contestant_identity() -> None:
    corpus = json.dumps(SystemAdjudication.model_json_schema()).lower()
    for forbidden in (
        "foundry",
        "baseline",
        "contestant",
        "provider",
        "model",
        "cost",
        "prompt",
        "implementation",
        "token",
        "latency",
        "xai",
        "grok",
    ):
        assert forbidden not in corpus, forbidden


# --------------------------------------------------------------------------------------
# 23-31  structural adjudication validator
# --------------------------------------------------------------------------------------


def _matched_setup() -> tuple[HiddenJudgeCase, tuple[BlindPrediction, ...], SystemAdjudication]:
    case = _judge_case(
        "CASE-T-1",
        (
            _concept("C-001", primary_gap_kind=GapKind.AMBIGUITY, exact_subject_key="a-key"),
            _concept(
                "C-002",
                primary_gap_kind=GapKind.MISSING_INFORMATION,
                exact_subject_key="b-key",
            ),
        ),
    )
    predictions = (
        _prediction("P-001", kind=GapKind.AMBIGUITY),
        _prediction("P-002", kind=GapKind.MISSING_INFORMATION),
    )
    adjudication = _adjudication(
        concept_judgments=(
            _concept_judgment("C-001", matched_prediction_id="P-001"),
            _concept_judgment("C-002", matched_prediction_id="P-002"),
        ),
        prediction_judgments=(
            _prediction_judgment("P-001"),
            _prediction_judgment("P-002"),
        ),
    )
    return case, predictions, adjudication


def test_valid_adjudication_returns_the_same_object_unchanged() -> None:
    case, predictions, adjudication = _matched_setup()
    before = adjudication.model_dump(mode="json")
    assert validate_system_adjudication(case, predictions, adjudication) is adjudication
    assert adjudication.model_dump(mode="json") == before


def test_adjudication_case_id_must_match_the_judge_case() -> None:
    case, predictions, adjudication = _matched_setup()
    wrong = adjudication.model_copy(update={"case_id": "CASE-T-OTHER"})
    with pytest.raises(AdjudicationValidationError):
        validate_system_adjudication(case, predictions, wrong)


def test_every_expected_concept_needs_exactly_one_judgment() -> None:
    case, predictions, adjudication = _matched_setup()
    missing = adjudication.model_copy(
        update={"concept_judgments": adjudication.concept_judgments[:1]}
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, missing)
    assert "C-002" in str(excinfo.value)

    duplicated = adjudication.model_copy(
        update={
            "concept_judgments": (
                adjudication.concept_judgments[0],
                adjudication.concept_judgments[0],
                adjudication.concept_judgments[1],
            )
        }
    )
    with pytest.raises(AdjudicationValidationError):
        validate_system_adjudication(case, predictions, duplicated)


def test_unknown_concept_judgment_is_rejected() -> None:
    case, predictions, adjudication = _matched_setup()
    unknown = adjudication.model_copy(
        update={
            "concept_judgments": (
                *adjudication.concept_judgments,
                _concept_judgment(
                    "C-404", matched_prediction_id=None, semantic_match=False,
                    gap_kind_correct=None,
                ),
            )
        }
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, unknown)
    assert "C-404" in str(excinfo.value)


def test_every_prediction_needs_exactly_one_judgment() -> None:
    case, predictions, adjudication = _matched_setup()
    missing = adjudication.model_copy(
        update={"prediction_judgments": adjudication.prediction_judgments[:1]}
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, missing)
    assert "P-002" in str(excinfo.value)


def test_unknown_prediction_judgment_is_rejected() -> None:
    case, predictions, adjudication = _matched_setup()
    unknown = adjudication.model_copy(
        update={
            "prediction_judgments": (
                *adjudication.prediction_judgments,
                _prediction_judgment("P-404", disposition=PredictionDisposition.SUPPORTED_EXTRA),
            )
        }
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, unknown)
    assert "P-404" in str(excinfo.value)


def test_one_prediction_cannot_be_matched_to_two_expected_concepts() -> None:
    case, predictions, _ = _matched_setup()
    adjudication = _adjudication(
        concept_judgments=(
            _concept_judgment("C-001", matched_prediction_id="P-001"),
            _concept_judgment("C-002", matched_prediction_id="P-001", gap_kind_correct=False),
        ),
        prediction_judgments=(
            _prediction_judgment("P-001"),
            _prediction_judgment("P-002", disposition=PredictionDisposition.SUPPORTED_EXTRA),
        ),
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, adjudication)
    assert "P-001" in str(excinfo.value)


def test_matched_concept_must_point_at_a_matched_expected_prediction() -> None:
    case, predictions, _ = _matched_setup()
    adjudication = _adjudication(
        concept_judgments=(
            _concept_judgment("C-001", matched_prediction_id="P-001"),
            _concept_judgment(
                "C-002", matched_prediction_id=None, semantic_match=False, gap_kind_correct=None
            ),
        ),
        prediction_judgments=(
            _prediction_judgment("P-001", disposition=PredictionDisposition.SUPPORTED_EXTRA),
            _prediction_judgment("P-002", disposition=PredictionDisposition.REDUNDANT),
        ),
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, adjudication)
    assert "MATCHED_EXPECTED" in str(excinfo.value)


def test_matched_expected_prediction_must_receive_exactly_one_concept_match() -> None:
    case, predictions, _ = _matched_setup()
    adjudication = _adjudication(
        concept_judgments=(
            _concept_judgment("C-001", matched_prediction_id="P-001"),
            _concept_judgment(
                "C-002", matched_prediction_id=None, semantic_match=False, gap_kind_correct=None
            ),
        ),
        prediction_judgments=(
            _prediction_judgment("P-001"),
            _prediction_judgment("P-002", disposition=PredictionDisposition.MATCHED_EXPECTED),
        ),
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, adjudication)
    assert "P-002" in str(excinfo.value)


def test_matched_concept_pointing_at_unknown_prediction_is_rejected() -> None:
    case, predictions, _ = _matched_setup()
    adjudication = _adjudication(
        concept_judgments=(
            _concept_judgment("C-001", matched_prediction_id="P-404"),
            _concept_judgment("C-002", matched_prediction_id="P-002"),
        ),
        prediction_judgments=(
            _prediction_judgment("P-001", disposition=PredictionDisposition.REDUNDANT),
            _prediction_judgment("P-002"),
        ),
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, adjudication)
    assert "P-404" in str(excinfo.value)


def test_gap_kind_correctness_is_verified_against_actual_kinds() -> None:
    case, predictions, adjudication = _matched_setup()
    wrong = adjudication.model_copy(
        update={
            "concept_judgments": (
                _concept_judgment("C-001", matched_prediction_id="P-001", gap_kind_correct=False),
                adjudication.concept_judgments[1],
            )
        }
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, wrong)
    assert "gap_kind_correct" in str(excinfo.value)


def test_gap_kind_mismatch_must_be_declared_incorrect() -> None:
    case = _judge_case(
        "CASE-T-1",
        (_concept("C-001", primary_gap_kind=GapKind.AMBIGUITY, exact_subject_key="a-key"),),
    )
    predictions = (_prediction("P-001", kind=GapKind.UNDERSPECIFIED_SCOPE),)

    honest = _adjudication(
        concept_judgments=(
            _concept_judgment("C-001", matched_prediction_id="P-001", gap_kind_correct=False),
        ),
        prediction_judgments=(_prediction_judgment("P-001"),),
    )
    assert validate_system_adjudication(case, predictions, honest) is honest

    dishonest = honest.model_copy(
        update={
            "concept_judgments": (
                _concept_judgment("C-001", matched_prediction_id="P-001", gap_kind_correct=True),
            )
        }
    )
    with pytest.raises(AdjudicationValidationError):
        validate_system_adjudication(case, predictions, dishonest)


def test_bundled_concept_ids_must_exist_in_the_judge_case() -> None:
    case, predictions, adjudication = _matched_setup()
    bundled = adjudication.model_copy(
        update={
            "prediction_judgments": (
                _prediction_judgment("P-001", bundled_concept_ids=("C-001", "C-002")),
                adjudication.prediction_judgments[1],
            )
        }
    )
    assert validate_system_adjudication(case, predictions, bundled) is bundled

    unknown = adjudication.model_copy(
        update={
            "prediction_judgments": (
                _prediction_judgment("P-001", bundled_concept_ids=("C-404",)),
                adjudication.prediction_judgments[1],
            )
        }
    )
    with pytest.raises(AdjudicationValidationError) as excinfo:
        validate_system_adjudication(case, predictions, unknown)
    assert "C-404" in str(excinfo.value)


def test_bundled_prediction_still_receives_credit_for_only_one_concept() -> None:
    case, predictions, _ = _matched_setup()
    adjudication = _adjudication(
        concept_judgments=(
            _concept_judgment("C-001", matched_prediction_id="P-001"),
            _concept_judgment(
                "C-002", matched_prediction_id=None, semantic_match=False, gap_kind_correct=None
            ),
        ),
        prediction_judgments=(
            _prediction_judgment("P-001", bundled_concept_ids=("C-001", "C-002")),
            _prediction_judgment("P-002", disposition=PredictionDisposition.REDUNDANT),
        ),
    )
    assert validate_system_adjudication(case, predictions, adjudication) is adjudication


def test_adjudication_uncertain_survives_validation_unresolved() -> None:
    case, predictions, _ = _matched_setup()
    adjudication = _adjudication(
        concept_judgments=(
            _concept_judgment(
                "C-001",
                matched_prediction_id=None,
                semantic_match=False,
                gap_kind_correct=None,
                state=AdjudicationState.ADJUDICATION_UNCERTAIN,
            ),
            _concept_judgment("C-002", matched_prediction_id="P-002"),
        ),
        prediction_judgments=(
            _prediction_judgment(
                "P-001",
                disposition=PredictionDisposition.UNSUPPORTED_OR_IMMATERIAL,
                state=AdjudicationState.ADJUDICATION_UNCERTAIN,
            ),
            _prediction_judgment("P-002"),
        ),
    )
    validated = validate_system_adjudication(case, predictions, adjudication)
    assert validated.concept_judgments[0].state is AdjudicationState.ADJUDICATION_UNCERTAIN
    assert validated.prediction_judgments[0].state is AdjudicationState.ADJUDICATION_UNCERTAIN


def test_validator_never_repairs_an_invalid_adjudication() -> None:
    case, predictions, _ = _matched_setup()
    broken = _adjudication(
        concept_judgments=(
            _concept_judgment("C-001", matched_prediction_id="P-001"),
            _concept_judgment("C-002", matched_prediction_id="P-001", gap_kind_correct=False),
        ),
        prediction_judgments=(
            _prediction_judgment("P-001"),
            _prediction_judgment("P-002", disposition=PredictionDisposition.REDUNDANT),
        ),
    )
    before = broken.model_dump(mode="json")
    with pytest.raises(AdjudicationValidationError):
        validate_system_adjudication(case, predictions, broken)
    assert broken.model_dump(mode="json") == before


def test_zero_prediction_case_is_structurally_valid() -> None:
    case = _judge_case("CASE-T-1", (_concept("C-001"),))
    adjudication = _adjudication(
        concept_judgments=(
            _concept_judgment(
                "C-001", matched_prediction_id=None, semantic_match=False, gap_kind_correct=None
            ),
        ),
        prediction_judgments=(),
    )
    assert validate_system_adjudication(case, (), adjudication) is adjudication


# --------------------------------------------------------------------------------------
# 76-89  frozen adjudication mechanism
# --------------------------------------------------------------------------------------


def test_adjudication_mechanism_is_exactly_the_frozen_mechanism() -> None:
    mechanism = build_adjudication_mechanism()
    assert mechanism == build_adjudication_mechanism()
    assert mechanism.mechanism_version == "gpt-5.6-sol-blind-primary-human-uncertain-v1"
    with pytest.raises(ValidationError):
        mechanism.primary_model = "other"  # type: ignore[misc]


def test_primary_adjudicator_is_an_independent_non_xai_frontier_model() -> None:
    mechanism = build_adjudication_mechanism()
    assert mechanism.primary_provider == "OpenAI"
    assert mechanism.primary_model == "GPT-5.6 Sol"


def test_primary_adjudicator_runs_in_a_fresh_isolated_context() -> None:
    assert build_adjudication_mechanism().primary_execution_context == "fresh-isolated-session"


def test_only_the_blind_prediction_surface_reaches_the_adjudicator() -> None:
    mechanism = build_adjudication_mechanism()
    assert mechanism.prediction_surface == "BlindPrediction"
    assert mechanism.primary_uses_only_adjudication_packet is True


def test_mechanism_hides_identity_cost_prompts_and_implementation() -> None:
    mechanism = build_adjudication_mechanism()
    assert mechanism.identity_blind is True
    assert mechanism.cost_hidden is True
    assert mechanism.contestant_prompt_hidden is True
    assert mechanism.implementation_hidden is True
    assert mechanism.raw_contestant_payload_hidden is True
    assert mechanism.original_local_ids_hidden is True


def test_mechanism_hides_foundry_semantic_proposals() -> None:
    assert build_adjudication_mechanism().foundry_semantic_proposals_hidden is True


def test_human_review_is_triggered_only_by_adjudication_uncertain() -> None:
    mechanism = build_adjudication_mechanism()
    assert mechanism.human_review_trigger == AdjudicationState.ADJUDICATION_UNCERTAIN.value
    assert mechanism.human_review_trigger == "ADJUDICATION_UNCERTAIN"


def test_human_review_is_identity_blind_and_independent_before_reconciliation() -> None:
    mechanism = build_adjudication_mechanism()
    assert mechanism.human_review_identity_blind is True
    assert mechanism.human_review_independent_before_reconciliation is True


def test_grok_may_not_be_the_sole_adjudicator() -> None:
    assert build_adjudication_mechanism().grok_4_6_may_be_sole_adjudicator is False


def test_mechanism_forbids_extra_fields() -> None:
    payload = build_adjudication_mechanism().model_dump(mode="json")
    payload["adjudicator_api_key"] = "x"
    with pytest.raises(ValidationError):
        AdjudicationMechanism.model_validate(payload)


# --------------------------------------------------------------------------------------
# 90-98  frozen semantic rubric
# --------------------------------------------------------------------------------------


def test_rubric_primary_endpoint_is_critical_semantic_recall() -> None:
    rubric = build_semantic_rubric()
    assert rubric.rubric_version == "intent-semantic-rubric-v1"
    assert rubric.primary_endpoint == "critical_semantic_recall"


def test_rubric_aggregation_is_micro() -> None:
    assert build_semantic_rubric().aggregation == "micro"


def test_rubric_zero_denominator_is_not_applicable() -> None:
    assert build_semantic_rubric().zero_denominator == "N/A"


def test_rubric_freezes_one_to_one_matching() -> None:
    assert build_semantic_rubric().one_to_one_matching is True


def test_rubric_denies_exact_task7_primacy() -> None:
    assert build_semantic_rubric().exact_task7_is_primary is False


def test_rubric_denies_recall_credit_to_supported_extra() -> None:
    assert build_semantic_rubric().supported_extra_receives_recall_credit is False


def test_rubric_forbids_a_weighted_master_score() -> None:
    rubric = build_semantic_rubric()
    assert rubric.weighted_master_score is False
    corpus = json.dumps(rubric.model_dump(mode="json")).lower()
    assert "weight" not in corpus.replace("weighted_master_score", "")


def test_rubric_names_the_bundled_concept_diagnostic() -> None:
    assert build_semantic_rubric().bundled_concept_diagnostic == (
        "bundled_concept_prediction_count"
    )


def test_rubric_freezes_all_six_metric_formulas() -> None:
    rubric = build_semantic_rubric()
    formulas = {formula.metric: formula for formula in rubric.formulas}
    assert set(formulas) == {
        "critical_semantic_recall",
        "overall_semantic_recall",
        "useful_semantic_precision",
        "unsupported_rate",
        "redundancy_rate",
        "GapKind_accuracy",
    }
    assert formulas["critical_semantic_recall"].numerator == (
        "matched critical expected concepts"
    )
    assert formulas["critical_semantic_recall"].denominator == (
        "total critical expected concepts"
    )
    assert formulas["overall_semantic_recall"].numerator == "matched expected concepts"
    assert formulas["overall_semantic_recall"].denominator == "total expected concepts"
    assert formulas["useful_semantic_precision"].numerator == (
        "matched predictions + SUPPORTED_EXTRA predictions"
    )
    assert formulas["useful_semantic_precision"].denominator == "total predictions"
    assert formulas["unsupported_rate"].numerator == "UNSUPPORTED_OR_IMMATERIAL predictions"
    assert formulas["unsupported_rate"].denominator == "total predictions"
    assert formulas["redundancy_rate"].numerator == "REDUNDANT predictions"
    assert formulas["redundancy_rate"].denominator == "total predictions"
    assert formulas["GapKind_accuracy"].numerator == (
        "matched expected concepts whose matched prediction has the correct primary GapKind"
    )
    assert formulas["GapKind_accuracy"].denominator == "matched expected concepts"
    assert len(rubric.formulas) == 6


def test_rubric_carries_the_exact_disposition_and_safety_vocabularies() -> None:
    rubric = build_semantic_rubric()
    assert rubric.prediction_dispositions == tuple(PredictionDisposition)
    assert rubric.safety_labels == tuple(SafetyLabel)
    assert rubric.serious_safety_labels == SERIOUS_SAFETY_LABELS


def test_rubric_freezes_the_superiority_interpretation_rule() -> None:
    rule = build_semantic_rubric().superiority_rule
    assert rule.label == "directional-appears-better"
    assert rule.required_conditions == (
        "Foundry critical_semantic_recall > Baseline critical_semantic_recall",
        "Foundry serious safety violations <= Baseline serious safety violations",
    )
    assert rule.does_not_establish_statistical_superiority is True


def test_rubric_declares_no_statistical_significance_machinery() -> None:
    corpus = json.dumps(build_semantic_rubric().model_dump(mode="json")).lower()
    for forbidden in ("p_value", "p-value", "significance", "confidence_interval"):
        assert forbidden not in corpus, forbidden


# --------------------------------------------------------------------------------------
# 99-100  deterministic protocol serialization
# --------------------------------------------------------------------------------------


def test_protocol_serialization_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    mechanism = build_adjudication_mechanism()
    rubric = build_semantic_rubric()

    first = tmp_path / "a" / "adjudication-mechanism.json"
    second = tmp_path / "b" / "adjudication-mechanism.json"
    write_adjudication_mechanism(first, mechanism)
    write_adjudication_mechanism(second, mechanism)
    write_adjudication_mechanism(first, mechanism)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8").endswith("}\n")
    assert load_adjudication_mechanism(first) == mechanism

    rubric_path = tmp_path / "semantic-rubric.json"
    write_semantic_rubric(rubric_path, rubric)
    rubric_bytes = rubric_path.read_bytes()
    write_semantic_rubric(rubric_path, rubric)
    assert rubric_path.read_bytes() == rubric_bytes
    assert load_semantic_rubric(rubric_path) == rubric


def test_protocol_serialization_carries_no_environment_material(tmp_path: Path) -> None:
    mechanism_path = tmp_path / "adjudication-mechanism.json"
    rubric_path = tmp_path / "semantic-rubric.json"
    write_adjudication_mechanism(mechanism_path, build_adjudication_mechanism())
    write_semantic_rubric(rubric_path, build_semantic_rubric())
    for path in (mechanism_path, rubric_path):
        lowered = path.read_text(encoding="utf-8").lower()
        for forbidden in (
            "api_key",
            "created_at",
            "generated_at",
            "timestamp",
            "hostname",
            "username",
            "/users/",
            str(Path.home()).lower(),
        ):
            assert forbidden not in lowered, forbidden


def test_committed_protocol_files_equal_the_frozen_builders() -> None:
    protocol = REPO_ROOT / "evals/comparative/protocol"
    assert load_adjudication_mechanism(protocol / "adjudication-mechanism.json") == (
        build_adjudication_mechanism()
    )
    assert load_semantic_rubric(protocol / "semantic-rubric.json") == build_semantic_rubric()


# --------------------------------------------------------------------------------------
# 61-62  blind adjudication packet boundary
# --------------------------------------------------------------------------------------


def test_blind_adjudication_packet_exposes_only_the_blind_surface() -> None:
    assert set(BlindAdjudicationPacket.model_fields) == {
        "case_id",
        "source_evidence",
        "expected_concepts",
        "system_a_predictions",
        "system_b_predictions",
    }


def test_blind_adjudication_packet_schema_leaks_no_contestant_material() -> None:
    corpus = json.dumps(BlindAdjudicationPacket.model_json_schema()).lower()
    for forbidden in (
        "foundry",
        "baseline",
        "contestant",
        "provider",
        "cost",
        "prompt",
        "implementation",
        "token",
        "latency",
        "usage",
        "wall_clock",
        "semantic_proposal",
        "gap_proposal",
        "xai",
        "grok",
        "intentintelligencepayload",
        "baselinepayload",
    ):
        assert forbidden not in corpus, forbidden


def test_blind_adjudication_packet_uses_provider_neutral_source_evidence() -> None:
    packet = BlindAdjudicationPacket(
        case_id="CASE-T-1",
        source_evidence=(
            IntelligenceSource(
                event_id="EVT-T-1",
                event_type=EventType.USER_STATED_INTENT,
                content="Synthetic placeholder evidence record.",
                source_kind=SourceKind.HUMAN,
                source_ref="TEST-ACTOR",
            ),
        ),
        expected_concepts=(_concept(),),
        system_a_predictions=(_prediction("P-001"),),
        system_b_predictions=(_prediction("P-001"),),
    )
    assert packet.source_evidence[0].event_id == "EVT-T-1"
    with pytest.raises(ValidationError):
        packet.case_id = "CASE-T-2"  # type: ignore[misc]


# --------------------------------------------------------------------------------------
# module hygiene
# --------------------------------------------------------------------------------------


def _module_source() -> str:
    return (REPO_ROOT / "src/foundry/evaluation/comparative_protocol.py").read_text(
        encoding="utf-8"
    )


def test_comparative_protocol_imports_no_provider_sdk() -> None:
    source = _module_source()
    for forbidden in (
        "xai_sdk",
        "import openai",
        "from openai",
        "anthropic",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
    ):
        assert forbidden not in source, forbidden


def test_comparative_protocol_carries_no_development_fixture_answers() -> None:
    source = _module_source()
    for leaked in (
        "never-loses-money",
        "money-loss-meaning",
        "very-fast",
        "performance-target",
        "legacy-retry-count",
        "currency-scope",
        "money-conservation",
        "greenfield-payments-vague-v1",
        "brownfield-retry-conflict-v1",
    ):
        assert leaked not in source, leaked

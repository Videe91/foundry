"""Sealing machinery for the Intent Intelligence comparative exam.

Layered above the already-verified contestant freeze:

    ContestantFreezeManifest      (foundry.evaluation.experiment_manifest, unchanged)
            |
            +-- protocol commitments        (mechanism + rubric)
            +-- holdout input commitments
            +-- execution randomization commitment
            +-- hidden judge commitment
                        |
                        v
                 ExperimentManifest

Task 9J1 defines these types and the two-phase verification gates. It creates NO
holdout case, NO hidden judge content, NO execution assignment, and NO real
ExperimentManifest instance on disk. Those are authored in Task 9J2.

Phase-1 verification deliberately cannot reach the hidden judge: it takes no judge
argument and verifies only the judge COMMITMENT. Revealing the judge is a separate
Phase-2 function.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.evaluation.comparative_protocol import (
    AdjudicationValidationError,
    HiddenJudgeBundle,
    HoldoutFamily,
    build_adjudication_mechanism,
    build_semantic_rubric,
    load_adjudication_mechanism,
    load_semantic_rubric,
    validate_hidden_judge_case,
)
from foundry.evaluation.experiment_manifest import (
    ExperimentFreezeViolation,
    canonical_json_bytes,
    sha256_bytes,
    verify_contestant_freeze_file,
)
from foundry.evaluation.loader import load_input

COMPARATIVE_PROTOCOL_MODULE_PATH = "src/foundry/evaluation/comparative_protocol.py"
SEALED_EXAM_MANIFEST_MODULE_PATH = "src/foundry/evaluation/sealed_exam_manifest.py"

FIRST_SUITE_CASE_COUNT = 12
FIRST_SUITE_FAMILY_COUNT = 6
HOLDOUT_INPUT_FILENAME = "input.json"

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ExperimentSealViolation(RuntimeError):
    """Raised when a sealed experiment artifact is missing, altered, or inconsistent."""


class ContestantId(StrEnum):
    FOUNDRY = "FOUNDRY"
    BASELINE = "BASELINE"


class BlindSystemLabel(StrEnum):
    SYSTEM_A = "SYSTEM-A"
    SYSTEM_B = "SYSTEM-B"


def _check_safe_relative(value: str) -> str:
    if not value:
        raise ValueError("path must be non-empty")
    if value.startswith("~"):
        raise ValueError("path must not reference a home directory: " + value)
    candidate = PurePosixPath(value)
    if candidate.is_absolute():
        raise ValueError("path must be relative: " + value)
    if ".." in candidate.parts:
        raise ValueError("path must not traverse upward: " + value)
    return value


class HoldoutInputCommitment(FrozenModel):
    case_id: str = Field(min_length=1)
    family: HoldoutFamily
    input_path: str = Field(min_length=1)
    input_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def input_path_must_be_safe_and_loadable(self) -> HoldoutInputCommitment:
        _check_safe_relative(self.input_path)
        if PurePosixPath(self.input_path).name != HOLDOUT_INPUT_FILENAME:
            raise ValueError(
                "holdout input must be named "
                + HOLDOUT_INPUT_FILENAME
                + " so the sealed loader parses exactly the bytes that were hashed: "
                + self.input_path
            )
        return self


class HoldoutInputManifest(FrozenModel):
    manifest_version: Literal["holdout-inputs-v1"]
    cases: tuple[HoldoutInputCommitment, ...]

    @model_validator(mode="after")
    def cases_must_be_distinct(self) -> HoldoutInputManifest:
        _reject_duplicates("case_id", tuple(case.case_id for case in self.cases))
        _reject_duplicates("input_path", tuple(case.input_path for case in self.cases))
        return self


class CaseExecutionAssignment(FrozenModel):
    case_id: str = Field(min_length=1)
    first_contestant: ContestantId
    second_contestant: ContestantId
    foundry_blind_label: BlindSystemLabel
    baseline_blind_label: BlindSystemLabel

    @model_validator(mode="after")
    def contestants_and_labels_must_be_opposed(self) -> CaseExecutionAssignment:
        if self.first_contestant is self.second_contestant:
            raise ValueError(
                "each case must run both contestants; got "
                + self.first_contestant.value
                + " twice"
            )
        if self.foundry_blind_label is self.baseline_blind_label:
            raise ValueError(
                "each case must use both blind labels; got "
                + self.foundry_blind_label.value
                + " twice"
            )
        return self


class ExecutionAssignmentManifest(FrozenModel):
    manifest_version: Literal["execution-assignment-v1"]
    assignments: tuple[CaseExecutionAssignment, ...]

    @model_validator(mode="after")
    def case_ids_must_be_unique(self) -> ExecutionAssignmentManifest:
        _reject_duplicates("case_id", tuple(item.case_id for item in self.assignments))
        return self


class JudgeCommitment(FrozenModel):
    bundle_version: Literal["hidden-judge-v1"]
    canonicalization: Literal["canonical-json-v1"]
    bundle_sha256: str = Field(pattern=_SHA256_PATTERN)


class ExperimentManifest(FrozenModel):
    manifest_version: Literal["intent-comparative-experiment-v1"]

    contestant_freeze_path: str = Field(min_length=1)
    contestant_freeze_sha256: str = Field(pattern=_SHA256_PATTERN)

    comparative_protocol_module_sha256: str = Field(pattern=_SHA256_PATTERN)
    sealed_exam_manifest_module_sha256: str = Field(pattern=_SHA256_PATTERN)

    adjudication_mechanism_path: str = Field(min_length=1)
    adjudication_mechanism_sha256: str = Field(pattern=_SHA256_PATTERN)

    semantic_rubric_path: str = Field(min_length=1)
    semantic_rubric_sha256: str = Field(pattern=_SHA256_PATTERN)

    holdout_input_manifest_path: str = Field(min_length=1)
    holdout_input_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)

    execution_assignment_path: str = Field(min_length=1)
    execution_assignment_sha256: str = Field(pattern=_SHA256_PATTERN)

    judge_commitment: JudgeCommitment

    @model_validator(mode="after")
    def committed_paths_must_be_safe(self) -> ExperimentManifest:
        _check_safe_relative(self.contestant_freeze_path)
        _check_safe_relative(self.adjudication_mechanism_path)
        _check_safe_relative(self.semantic_rubric_path)
        _check_safe_relative(self.holdout_input_manifest_path)
        _check_safe_relative(self.execution_assignment_path)
        return self


def canonical_hidden_judge_bytes(bundle: HiddenJudgeBundle) -> bytes:
    """Canonical semantic bytes of a hidden judge bundle. No path or timestamp input."""
    return canonical_json_bytes(bundle.model_dump(mode="json"))


def commit_hidden_judge(bundle: HiddenJudgeBundle) -> JudgeCommitment:
    return JudgeCommitment(
        bundle_version=bundle.bundle_version,
        canonicalization="canonical-json-v1",
        bundle_sha256=sha256_bytes(canonical_hidden_judge_bytes(bundle)),
    )


def write_holdout_input_manifest(path: Path, manifest: HoldoutInputManifest) -> None:
    _write_sealed(path, manifest.model_dump(mode="json"))


def load_holdout_input_manifest(path: Path) -> HoldoutInputManifest:
    return HoldoutInputManifest.model_validate(_read_sealed(path))


def write_execution_assignment(path: Path, manifest: ExecutionAssignmentManifest) -> None:
    _write_sealed(path, manifest.model_dump(mode="json"))


def load_execution_assignment(path: Path) -> ExecutionAssignmentManifest:
    return ExecutionAssignmentManifest.model_validate(_read_sealed(path))


def write_experiment_manifest(path: Path, manifest: ExperimentManifest) -> None:
    _write_sealed(path, manifest.model_dump(mode="json"))


def load_experiment_manifest(path: Path) -> ExperimentManifest:
    return ExperimentManifest.model_validate(_read_sealed(path))


def validate_first_suite_holdout_manifest(
    manifest: HoldoutInputManifest,
) -> HoldoutInputManifest:
    """The first comparative suite is exactly 12 cases: 6 greenfield, 6 brownfield."""
    if len(manifest.cases) != FIRST_SUITE_CASE_COUNT:
        raise ExperimentSealViolation(
            "first comparative suite requires exactly "
            + str(FIRST_SUITE_CASE_COUNT)
            + " holdout cases; found "
            + str(len(manifest.cases))
        )
    counts = {
        family: sum(case.family is family for case in manifest.cases)
        for family in HoldoutFamily
    }
    if any(count != FIRST_SUITE_FAMILY_COUNT for count in counts.values()):
        raise ExperimentSealViolation(
            "first comparative suite requires exactly "
            + str(FIRST_SUITE_FAMILY_COUNT)
            + " greenfield and "
            + str(FIRST_SUITE_FAMILY_COUNT)
            + " brownfield cases; found greenfield="
            + str(counts[HoldoutFamily.GREENFIELD])
            + ", brownfield="
            + str(counts[HoldoutFamily.BROWNFIELD])
        )
    return manifest


def validate_first_suite_execution_assignment(
    manifest: ExecutionAssignmentManifest,
) -> ExecutionAssignmentManifest:
    """Counterbalance both provider execution order and blind-label position."""
    assignments = manifest.assignments
    if len(assignments) != FIRST_SUITE_CASE_COUNT:
        raise ExperimentSealViolation(
            "first comparative suite requires exactly "
            + str(FIRST_SUITE_CASE_COUNT)
            + " execution assignments; found "
            + str(len(assignments))
        )
    for contestant in ContestantId:
        count = sum(item.first_contestant is contestant for item in assignments)
        if count != FIRST_SUITE_FAMILY_COUNT:
            raise ExperimentSealViolation(
                contestant.value
                + " must run first in exactly "
                + str(FIRST_SUITE_FAMILY_COUNT)
                + " cases; found "
                + str(count)
            )
    for label in BlindSystemLabel:
        count = sum(item.foundry_blind_label is label for item in assignments)
        if count != FIRST_SUITE_FAMILY_COUNT:
            raise ExperimentSealViolation(
                "FOUNDRY must carry "
                + label.value
                + " in exactly "
                + str(FIRST_SUITE_FAMILY_COUNT)
                + " cases; found "
                + str(count)
            )
    return manifest


def validate_execution_assignment(
    holdouts: HoldoutInputManifest,
    assignment: ExecutionAssignmentManifest,
) -> ExecutionAssignmentManifest:
    """The assignment must cover exactly the committed holdout case IDs."""
    _require_same_case_ids(
        "execution assignment",
        tuple(case.case_id for case in holdouts.cases),
        tuple(item.case_id for item in assignment.assignments),
    )
    return assignment


def verify_phase1_experiment(
    manifest: ExperimentManifest,
    repo_root: Path,
    *,
    sdk_version: str | None = None,
) -> None:
    """Verify every PUBLIC seal before any contestant call. Read-only.

    Takes no hidden-judge argument by design: Phase 1 verifies the judge COMMITMENT,
    never the judge contents.
    """
    freeze_bytes = _read_sealed_bytes(
        repo_root, manifest.contestant_freeze_path, "contestant freeze"
    )
    _require_hash(
        "contestant freeze",
        manifest.contestant_freeze_path,
        sha256_bytes(freeze_bytes),
        manifest.contestant_freeze_sha256,
    )
    try:
        verify_contestant_freeze_file(
            repo_root / manifest.contestant_freeze_path,
            repo_root,
            sdk_version=sdk_version,
        )
    except ExperimentFreezeViolation as exc:
        raise ExperimentSealViolation("contestant freeze failed: " + str(exc)) from exc

    _require_hash(
        "comparative protocol module",
        COMPARATIVE_PROTOCOL_MODULE_PATH,
        sha256_bytes(
            _read_sealed_bytes(
                repo_root, COMPARATIVE_PROTOCOL_MODULE_PATH, "comparative protocol module"
            )
        ),
        manifest.comparative_protocol_module_sha256,
    )
    _require_hash(
        "sealed exam manifest module",
        SEALED_EXAM_MANIFEST_MODULE_PATH,
        sha256_bytes(
            _read_sealed_bytes(
                repo_root, SEALED_EXAM_MANIFEST_MODULE_PATH, "sealed exam manifest module"
            )
        ),
        manifest.sealed_exam_manifest_module_sha256,
    )

    mechanism_bytes = _read_sealed_bytes(
        repo_root, manifest.adjudication_mechanism_path, "adjudication mechanism"
    )
    _require_hash(
        "adjudication mechanism",
        manifest.adjudication_mechanism_path,
        sha256_bytes(mechanism_bytes),
        manifest.adjudication_mechanism_sha256,
    )
    if (
        load_adjudication_mechanism(repo_root / manifest.adjudication_mechanism_path)
        != build_adjudication_mechanism()
    ):
        raise ExperimentSealViolation(
            "committed adjudication mechanism does not equal the frozen mechanism at "
            + manifest.adjudication_mechanism_path
        )

    rubric_bytes = _read_sealed_bytes(
        repo_root, manifest.semantic_rubric_path, "semantic rubric"
    )
    _require_hash(
        "semantic rubric",
        manifest.semantic_rubric_path,
        sha256_bytes(rubric_bytes),
        manifest.semantic_rubric_sha256,
    )
    if load_semantic_rubric(repo_root / manifest.semantic_rubric_path) != build_semantic_rubric():
        raise ExperimentSealViolation(
            "committed semantic rubric does not equal the frozen rubric at "
            + manifest.semantic_rubric_path
        )

    holdouts = _verify_holdout_manifest(manifest, repo_root)

    assignment_bytes = _read_sealed_bytes(
        repo_root, manifest.execution_assignment_path, "execution assignment"
    )
    _require_hash(
        "execution assignment",
        manifest.execution_assignment_path,
        sha256_bytes(assignment_bytes),
        manifest.execution_assignment_sha256,
    )
    assignment = load_execution_assignment(repo_root / manifest.execution_assignment_path)
    validate_first_suite_execution_assignment(assignment)
    validate_execution_assignment(holdouts, assignment)

    _require_commitment_shape(manifest.judge_commitment)


def verify_revealed_judge_bundle(
    manifest: ExperimentManifest,
    judge_bundle_path: Path,
    repo_root: Path,
) -> HiddenJudgeBundle:
    """PHASE 2 ONLY. Reveal and verify the hidden judge after contestant outputs freeze.

    The judge bundle is an explicit operator argument and may live outside the
    repository. Nothing is written, repaired, or regenerated.
    """
    try:
        raw = judge_bundle_path.read_bytes()
    except OSError as exc:
        raise ExperimentSealViolation(
            "missing revealed judge bundle: " + str(judge_bundle_path)
        ) from exc

    bundle = HiddenJudgeBundle.model_validate(json.loads(raw.decode("utf-8")))
    commitment = manifest.judge_commitment
    if bundle.bundle_version != commitment.bundle_version:
        raise ExperimentSealViolation(
            "revealed judge bundle_version "
            + bundle.bundle_version
            + " does not match the commitment "
            + commitment.bundle_version
        )
    actual = sha256_bytes(canonical_hidden_judge_bytes(bundle))
    if actual != commitment.bundle_sha256:
        raise ExperimentSealViolation(
            "revealed judge bundle does not match the precommitted commitment; expected="
            + commitment.bundle_sha256
            + " actual="
            + actual
        )

    holdouts = _verify_holdout_manifest(manifest, repo_root)
    _require_same_case_ids(
        "revealed judge bundle",
        tuple(case.case_id for case in holdouts.cases),
        tuple(case.case_id for case in bundle.cases),
    )

    commitments = {case.case_id: case for case in holdouts.cases}
    for judge_case in bundle.cases:
        commitment_case = commitments[judge_case.case_id]
        eval_input = load_input((repo_root / commitment_case.input_path).parent)
        try:
            validate_hidden_judge_case(eval_input, judge_case)
        except AdjudicationValidationError as exc:
            raise ExperimentSealViolation(
                "revealed judge case is not grounded in its visible input: " + str(exc)
            ) from exc
    return bundle


def _verify_holdout_manifest(
    manifest: ExperimentManifest,
    repo_root: Path,
) -> HoldoutInputManifest:
    holdout_bytes = _read_sealed_bytes(
        repo_root, manifest.holdout_input_manifest_path, "holdout input manifest"
    )
    _require_hash(
        "holdout input manifest",
        manifest.holdout_input_manifest_path,
        sha256_bytes(holdout_bytes),
        manifest.holdout_input_manifest_sha256,
    )
    holdouts = load_holdout_input_manifest(repo_root / manifest.holdout_input_manifest_path)
    validate_first_suite_holdout_manifest(holdouts)
    for case in holdouts.cases:
        data = _read_sealed_bytes(repo_root, case.input_path, "holdout input " + case.case_id)
        _require_hash("holdout input", case.input_path, sha256_bytes(data), case.input_sha256)
        eval_input = load_input((repo_root / case.input_path).parent)
        if eval_input.fixture_id != case.case_id:
            raise ExperimentSealViolation(
                "holdout input "
                + case.input_path
                + " declares fixture_id "
                + eval_input.fixture_id
                + " but is committed as case "
                + case.case_id
            )
        if eval_input.family != case.family.value:
            raise ExperimentSealViolation(
                "holdout input "
                + case.input_path
                + " declares family "
                + eval_input.family
                + " but is committed as family "
                + case.family.value
            )
    return holdouts


def _require_commitment_shape(commitment: JudgeCommitment) -> None:
    if commitment.bundle_version != "hidden-judge-v1":
        raise ExperimentSealViolation(
            "unsupported judge bundle_version: " + commitment.bundle_version
        )
    if commitment.canonicalization != "canonical-json-v1":
        raise ExperimentSealViolation(
            "unsupported judge canonicalization: " + commitment.canonicalization
        )


def _require_same_case_ids(label: str, expected: tuple[str, ...], actual: tuple[str, ...]) -> None:
    difference = set(expected) ^ set(actual)
    if difference:
        raise ExperimentSealViolation(
            label
            + " case IDs do not match the committed holdout cases; differing: "
            + ", ".join(sorted(difference))
        )
    if len(actual) != len(expected):
        raise ExperimentSealViolation(
            label
            + " has "
            + str(len(actual))
            + " entries for "
            + str(len(expected))
            + " committed holdout cases"
        )


def _read_sealed_bytes(repo_root: Path, relative: str, label: str) -> bytes:
    _check_safe_relative(relative)
    root = repo_root.resolve()
    target = (repo_root / relative).resolve()
    if not target.is_relative_to(root):
        raise ExperimentSealViolation(
            "sealed " + label + " path escapes the repository: " + relative
        )
    try:
        return target.read_bytes()
    except OSError as exc:
        raise ExperimentSealViolation(
            "missing sealed artifact (" + label + "): " + relative
        ) from exc


def _require_hash(label: str, relative: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise ExperimentSealViolation(
            "EXPERIMENT SEAL VIOLATION: "
            + label
            + " at "
            + relative
            + " does not match its commitment; expected="
            + expected
            + " actual="
            + actual
        )


def _reject_duplicates(label: str, values: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError("duplicate " + label + ": " + value)
        seen.add(value)


def _write_sealed(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(serialized + "\n", encoding="utf-8")


def _read_sealed(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))

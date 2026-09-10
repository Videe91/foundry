from __future__ import annotations

import inspect
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.domain.gaps import GapKind
from foundry.evaluation.comparative_protocol import (
    ConceptCriticality,
    ExpectedConcept,
    HiddenJudgeBundle,
    HiddenJudgeCase,
    HoldoutFamily,
    build_adjudication_mechanism,
    build_semantic_rubric,
    write_adjudication_mechanism,
    write_semantic_rubric,
)
from foundry.evaluation.experiment_manifest import (
    COMPARATIVE_SPEC_PATH,
    COMPARISON_MODULE_PATH,
    build_current_contestant_freeze,
    sha256_bytes,
    write_contestant_freeze,
)
from foundry.evaluation.sealed_exam_manifest import (
    COMPARATIVE_PROTOCOL_MODULE_PATH,
    SEALED_EXAM_MANIFEST_MODULE_PATH,
    BlindSystemLabel,
    CaseExecutionAssignment,
    ContestantId,
    ExecutionAssignmentManifest,
    ExperimentManifest,
    ExperimentSealViolation,
    HoldoutInputCommitment,
    HoldoutInputManifest,
    JudgeCommitment,
    canonical_hidden_judge_bytes,
    commit_hidden_judge,
    load_execution_assignment,
    load_experiment_manifest,
    load_holdout_input_manifest,
    validate_execution_assignment,
    validate_first_suite_execution_assignment,
    validate_first_suite_holdout_manifest,
    verify_phase1_experiment,
    verify_revealed_judge_bundle,
    write_execution_assignment,
    write_experiment_manifest,
    write_holdout_input_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_SDK_VERSION = "sdk-version-under-test"
_SHA_ZERO = "0" * 64

CONTESTANT_FREEZE_PATH = "evals/comparative/contestant-freeze.json"
MECHANISM_PATH = "evals/comparative/protocol/adjudication-mechanism.json"
RUBRIC_PATH = "evals/comparative/protocol/semantic-rubric.json"
HOLDOUT_MANIFEST_PATH = "evals/comparative/holdout-inputs.json"
ASSIGNMENT_PATH = "evals/comparative/execution-assignment.json"

_FROZEN_TREE_FILES = (
    "src/foundry/intelligence/input.py",
    "src/foundry/intelligence/compiler.py",
    "src/foundry/intelligence/proposals.py",
    "src/foundry/intelligence/validation.py",
    "src/foundry/intelligence/eval_adapter.py",
    "src/foundry/intelligence/baseline.py",
    "src/foundry/intelligence/baseline_validation.py",
    "src/foundry/intelligence/source_records.py",
    COMPARISON_MODULE_PATH,
    "src/foundry/adapters/intelligence/xai.py",
    "src/foundry/adapters/intelligence/xai_baseline.py",
    "src/foundry/domain/gaps.py",
    COMPARATIVE_SPEC_PATH,
    COMPARATIVE_PROTOCOL_MODULE_PATH,
    SEALED_EXAM_MANIFEST_MODULE_PATH,
)

# Synthetic case identifiers. Deliberately generic; these are NOT candidate holdouts.
_CASE_IDS = tuple(f"SYNTH-CASE-{index:02d}" for index in range(1, 13))


# --------------------------------------------------------------------------------------
# synthetic tree helpers
# --------------------------------------------------------------------------------------


def _synthetic_input_payload(case_id: str, family: HoldoutFamily) -> dict[str, Any]:
    return {
        "fixture_id": case_id,
        "family": family.value,
        "project_id": f"SYNTH-{case_id}",
        "events": [
            {
                "event_id": f"EVT-{case_id}-1",
                "project_id": f"SYNTH-{case_id}",
                "event_type": "USER_STATED_INTENT",
                "occurred_at": "2026-01-01T00:00:00Z",
                "correlation_id": None,
                "causation_id": None,
                "payload": {
                    "text": "Synthetic placeholder evidence for structural tests only.",
                    "actor_id": "TEST-ACTOR",
                },
            }
        ],
        "artifact_refs": [],
    }


def _family_for(index: int) -> HoldoutFamily:
    return HoldoutFamily.GREENFIELD if index < 6 else HoldoutFamily.BROWNFIELD


def _write_holdout_inputs(root: Path) -> HoldoutInputManifest:
    commitments = []
    for index, case_id in enumerate(_CASE_IDS):
        family = _family_for(index)
        relative = f"evals/comparative/holdouts/{case_id}/input.json"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_synthetic_input_payload(case_id, family)), encoding="utf-8"
        )
        commitments.append(
            HoldoutInputCommitment(
                case_id=case_id,
                family=family,
                input_path=relative,
                input_sha256=sha256_bytes(path.read_bytes()),
            )
        )
    return HoldoutInputManifest(
        manifest_version="holdout-inputs-v1", cases=tuple(commitments)
    )


def _balanced_assignment() -> ExecutionAssignmentManifest:
    assignments = []
    for index, case_id in enumerate(_CASE_IDS):
        foundry_first = index % 2 == 0
        foundry_is_a = (index // 2) % 2 == 0
        assignments.append(
            CaseExecutionAssignment(
                case_id=case_id,
                first_contestant=ContestantId.FOUNDRY if foundry_first else ContestantId.BASELINE,
                second_contestant=(
                    ContestantId.BASELINE if foundry_first else ContestantId.FOUNDRY
                ),
                foundry_blind_label=(
                    BlindSystemLabel.SYSTEM_A if foundry_is_a else BlindSystemLabel.SYSTEM_B
                ),
                baseline_blind_label=(
                    BlindSystemLabel.SYSTEM_B if foundry_is_a else BlindSystemLabel.SYSTEM_A
                ),
            )
        )
    return ExecutionAssignmentManifest(
        manifest_version="execution-assignment-v1", assignments=tuple(assignments)
    )


def _judge_bundle() -> HiddenJudgeBundle:
    return HiddenJudgeBundle(
        bundle_version="hidden-judge-v1",
        cases=tuple(
            HiddenJudgeCase(
                case_id=case_id,
                expected_concepts=(
                    ExpectedConcept(
                        concept_id="C-001",
                        semantic_description="Synthetic placeholder concept.",
                        primary_gap_kind=GapKind.AMBIGUITY,
                        criticality=ConceptCriticality.CRITICAL,
                        exact_subject_key="placeholder-subject",
                        evidence_event_ids=(f"EVT-{case_id}-1",),
                        evidence_basis="Synthetic placeholder basis.",
                        materiality_rationale="Synthetic placeholder rationale.",
                    ),
                ),
            )
            for case_id in _CASE_IDS
        ),
    )


@pytest.fixture
def sealed_tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in _FROZEN_TREE_FILES:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((REPO_ROOT / relative).read_bytes())

    write_contestant_freeze(
        root / CONTESTANT_FREEZE_PATH,
        build_current_contestant_freeze(root, sdk_version=_SDK_VERSION),
    )
    write_adjudication_mechanism(root / MECHANISM_PATH, build_adjudication_mechanism())
    write_semantic_rubric(root / RUBRIC_PATH, build_semantic_rubric())
    write_holdout_input_manifest(root / HOLDOUT_MANIFEST_PATH, _write_holdout_inputs(root))
    write_execution_assignment(root / ASSIGNMENT_PATH, _balanced_assignment())
    return root


def _sha_of(root: Path, relative: str) -> str:
    return sha256_bytes((root / relative).read_bytes())


def _manifest(root: Path, *, judge_sha: str | None = None) -> ExperimentManifest:
    return ExperimentManifest(
        manifest_version="intent-comparative-experiment-v1",
        contestant_freeze_path=CONTESTANT_FREEZE_PATH,
        contestant_freeze_sha256=_sha_of(root, CONTESTANT_FREEZE_PATH),
        comparative_protocol_module_sha256=_sha_of(root, COMPARATIVE_PROTOCOL_MODULE_PATH),
        sealed_exam_manifest_module_sha256=_sha_of(root, SEALED_EXAM_MANIFEST_MODULE_PATH),
        adjudication_mechanism_path=MECHANISM_PATH,
        adjudication_mechanism_sha256=_sha_of(root, MECHANISM_PATH),
        semantic_rubric_path=RUBRIC_PATH,
        semantic_rubric_sha256=_sha_of(root, RUBRIC_PATH),
        holdout_input_manifest_path=HOLDOUT_MANIFEST_PATH,
        holdout_input_manifest_sha256=_sha_of(root, HOLDOUT_MANIFEST_PATH),
        execution_assignment_path=ASSIGNMENT_PATH,
        execution_assignment_sha256=_sha_of(root, ASSIGNMENT_PATH),
        judge_commitment=JudgeCommitment(
            bundle_version="hidden-judge-v1",
            canonicalization="canonical-json-v1",
            bundle_sha256=judge_sha or commit_hidden_judge(_judge_bundle()).bundle_sha256,
        ),
    )


@pytest.fixture
def manifest(sealed_tree: Path) -> ExperimentManifest:
    return _manifest(sealed_tree)


def _commitment(**overrides: object) -> HoldoutInputCommitment:
    fields: dict[str, object] = {
        "case_id": "SYNTH-CASE-01",
        "family": HoldoutFamily.GREENFIELD,
        "input_path": "evals/comparative/holdouts/SYNTH-CASE-01/input.json",
        "input_sha256": _SHA_ZERO,
    }
    fields.update(overrides)
    return HoldoutInputCommitment(**fields)  # type: ignore[arg-type]


def _assignment(**overrides: object) -> CaseExecutionAssignment:
    fields: dict[str, object] = {
        "case_id": "SYNTH-CASE-01",
        "first_contestant": ContestantId.FOUNDRY,
        "second_contestant": ContestantId.BASELINE,
        "foundry_blind_label": BlindSystemLabel.SYSTEM_A,
        "baseline_blind_label": BlindSystemLabel.SYSTEM_B,
    }
    fields.update(overrides)
    return CaseExecutionAssignment(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# 32-34  holdout commitment path safety
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["", "abc", "A" * 64, "ABCDEF1234567890" + "0" * 48, "0" * 63, "g" * 64]
)
def test_holdout_commitment_rejects_invalid_hash(bad: str) -> None:
    with pytest.raises(ValidationError):
        _commitment(input_sha256=bad)


@pytest.mark.parametrize(
    "bad",
    [
        "/etc/passwd",
        "/evals/comparative/holdouts/X/input.json",
        "~/secrets/input.json",
    ],
)
def test_holdout_commitment_rejects_absolute_or_home_paths(bad: str) -> None:
    with pytest.raises(ValidationError):
        _commitment(input_path=bad)


@pytest.mark.parametrize(
    "bad",
    [
        "../input.json",
        "evals/../../input.json",
        "evals/comparative/../../../etc/input.json",
    ],
)
def test_holdout_commitment_rejects_parent_traversal(bad: str) -> None:
    with pytest.raises(ValidationError):
        _commitment(input_path=bad)


def test_holdout_commitment_requires_the_sealed_loader_filename() -> None:
    with pytest.raises(ValidationError):
        _commitment(input_path="evals/comparative/holdouts/SYNTH-CASE-01/case.json")
    assert _commitment().input_path.endswith("/input.json")


def test_holdout_commitment_requires_a_known_family() -> None:
    with pytest.raises(ValidationError):
        _commitment(family="mixedfield")


# --------------------------------------------------------------------------------------
# 35-40  holdout manifest structure
# --------------------------------------------------------------------------------------


def _holdout_manifest(count: int = 12, greenfield: int = 6) -> HoldoutInputManifest:
    cases = tuple(
        _commitment(
            case_id=f"SYNTH-CASE-{index:02d}",
            family=HoldoutFamily.GREENFIELD if index <= greenfield else HoldoutFamily.BROWNFIELD,
            input_path=f"evals/comparative/holdouts/SYNTH-CASE-{index:02d}/input.json",
        )
        for index in range(1, count + 1)
    )
    return HoldoutInputManifest(manifest_version="holdout-inputs-v1", cases=cases)


def test_first_suite_holdout_manifest_requires_exactly_twelve_cases() -> None:
    valid = _holdout_manifest()
    assert validate_first_suite_holdout_manifest(valid) is valid
    for count in (11, 13):
        with pytest.raises(ExperimentSealViolation):
            validate_first_suite_holdout_manifest(_holdout_manifest(count=count))


def test_first_suite_holdout_manifest_requires_six_greenfield() -> None:
    with pytest.raises(ExperimentSealViolation) as excinfo:
        validate_first_suite_holdout_manifest(_holdout_manifest(greenfield=5))
    assert "greenfield" in str(excinfo.value)


def test_first_suite_holdout_manifest_requires_six_brownfield() -> None:
    with pytest.raises(ExperimentSealViolation) as excinfo:
        validate_first_suite_holdout_manifest(_holdout_manifest(greenfield=7))
    message = str(excinfo.value)
    assert "brownfield=5" in message
    assert "greenfield=7" in message


def test_holdout_manifest_rejects_duplicate_case_ids() -> None:
    duplicate = (
        _commitment(case_id="SYNTH-CASE-01", input_path="evals/comparative/holdouts/a/input.json"),
        _commitment(case_id="SYNTH-CASE-01", input_path="evals/comparative/holdouts/b/input.json"),
    )
    with pytest.raises(ValidationError):
        HoldoutInputManifest(manifest_version="holdout-inputs-v1", cases=duplicate)


def test_holdout_manifest_rejects_duplicate_input_paths() -> None:
    duplicate = (
        _commitment(case_id="SYNTH-CASE-01"),
        _commitment(case_id="SYNTH-CASE-02"),
    )
    with pytest.raises(ValidationError):
        HoldoutInputManifest(manifest_version="holdout-inputs-v1", cases=duplicate)


def test_holdout_manifest_preserves_authoring_order(tmp_path: Path) -> None:
    reversed_cases = tuple(reversed(_holdout_manifest().cases))
    manifest = HoldoutInputManifest(
        manifest_version="holdout-inputs-v1", cases=reversed_cases
    )
    assert [case.case_id for case in manifest.cases] == [
        f"SYNTH-CASE-{index:02d}" for index in range(12, 0, -1)
    ]
    path = tmp_path / "holdout-inputs.json"
    write_holdout_input_manifest(path, manifest)
    assert load_holdout_input_manifest(path) == manifest
    assert [case.case_id for case in load_holdout_input_manifest(path).cases] == [
        case.case_id for case in manifest.cases
    ]


# --------------------------------------------------------------------------------------
# 41-47  execution assignment
# --------------------------------------------------------------------------------------


def test_case_assignment_requires_opposite_contestants() -> None:
    with pytest.raises(ValidationError):
        _assignment(
            first_contestant=ContestantId.FOUNDRY, second_contestant=ContestantId.FOUNDRY
        )
    with pytest.raises(ValidationError):
        _assignment(
            first_contestant=ContestantId.BASELINE, second_contestant=ContestantId.BASELINE
        )
    both = _assignment(
        first_contestant=ContestantId.BASELINE, second_contestant=ContestantId.FOUNDRY
    )
    assert {both.first_contestant, both.second_contestant} == set(ContestantId)


def test_case_assignment_requires_opposite_blind_labels() -> None:
    with pytest.raises(ValidationError):
        _assignment(
            foundry_blind_label=BlindSystemLabel.SYSTEM_A,
            baseline_blind_label=BlindSystemLabel.SYSTEM_A,
        )
    both = _assignment(
        foundry_blind_label=BlindSystemLabel.SYSTEM_B,
        baseline_blind_label=BlindSystemLabel.SYSTEM_A,
    )
    assert {both.foundry_blind_label, both.baseline_blind_label} == set(BlindSystemLabel)


def test_blind_system_label_values_are_exact() -> None:
    assert {label.value for label in BlindSystemLabel} == {"SYSTEM-A", "SYSTEM-B"}
    assert {value.value for value in ContestantId} == {"FOUNDRY", "BASELINE"}


def test_first_suite_execution_assignment_requires_exactly_twelve() -> None:
    valid = _balanced_assignment()
    assert validate_first_suite_execution_assignment(valid) is valid
    short = ExecutionAssignmentManifest(
        manifest_version="execution-assignment-v1", assignments=valid.assignments[:11]
    )
    with pytest.raises(ExperimentSealViolation):
        validate_first_suite_execution_assignment(short)


def test_execution_order_must_be_six_six() -> None:
    skewed = tuple(
        item.model_copy(
            update={
                "first_contestant": ContestantId.FOUNDRY,
                "second_contestant": ContestantId.BASELINE,
            }
        )
        for item in _balanced_assignment().assignments
    )
    with pytest.raises(ExperimentSealViolation) as excinfo:
        validate_first_suite_execution_assignment(
            ExecutionAssignmentManifest(
                manifest_version="execution-assignment-v1", assignments=skewed
            )
        )
    assert "first" in str(excinfo.value).lower()


def test_blind_label_position_must_be_six_six() -> None:
    skewed = tuple(
        item.model_copy(
            update={
                "foundry_blind_label": BlindSystemLabel.SYSTEM_A,
                "baseline_blind_label": BlindSystemLabel.SYSTEM_B,
            }
        )
        for item in _balanced_assignment().assignments
    )
    with pytest.raises(ExperimentSealViolation) as excinfo:
        validate_first_suite_execution_assignment(
            ExecutionAssignmentManifest(
                manifest_version="execution-assignment-v1", assignments=skewed
            )
        )
    assert "SYSTEM-A" in str(excinfo.value)


def test_balanced_reference_assignment_satisfies_both_counterbalances() -> None:
    assignments = _balanced_assignment().assignments
    assert sum(a.first_contestant is ContestantId.FOUNDRY for a in assignments) == 6
    assert sum(a.first_contestant is ContestantId.BASELINE for a in assignments) == 6
    assert sum(a.foundry_blind_label is BlindSystemLabel.SYSTEM_A for a in assignments) == 6
    assert sum(a.foundry_blind_label is BlindSystemLabel.SYSTEM_B for a in assignments) == 6


def test_execution_manifest_rejects_duplicate_case_ids() -> None:
    with pytest.raises(ValidationError):
        ExecutionAssignmentManifest(
            manifest_version="execution-assignment-v1",
            assignments=(_assignment(), _assignment()),
        )


# --------------------------------------------------------------------------------------
# 48  cross-manifest case-set validation
# --------------------------------------------------------------------------------------


def test_execution_assignment_case_ids_must_equal_holdout_case_ids() -> None:
    holdouts = _holdout_manifest()
    assignment = _balanced_assignment()
    assert validate_execution_assignment(holdouts, assignment) is assignment

    missing = ExecutionAssignmentManifest(
        manifest_version="execution-assignment-v1", assignments=assignment.assignments[:11]
    )
    with pytest.raises(ExperimentSealViolation):
        validate_execution_assignment(holdouts, missing)

    renamed = ExecutionAssignmentManifest(
        manifest_version="execution-assignment-v1",
        assignments=(
            assignment.assignments[0].model_copy(update={"case_id": "SYNTH-CASE-99"}),
            *assignment.assignments[1:],
        ),
    )
    with pytest.raises(ExperimentSealViolation) as excinfo:
        validate_execution_assignment(holdouts, renamed)
    assert "SYNTH-CASE-99" in str(excinfo.value)


# --------------------------------------------------------------------------------------
# 49-52  judge commitment
# --------------------------------------------------------------------------------------


def test_judge_commitment_validates_lowercase_sha256() -> None:
    valid = JudgeCommitment(
        bundle_version="hidden-judge-v1",
        canonicalization="canonical-json-v1",
        bundle_sha256=_SHA_ZERO,
    )
    assert valid.bundle_sha256 == _SHA_ZERO
    for bad in ("ABCDEF1234567890" + "0" * 48, "0" * 63, "", "g" * 64):
        with pytest.raises(ValidationError):
            JudgeCommitment(
                bundle_version="hidden-judge-v1",
                canonicalization="canonical-json-v1",
                bundle_sha256=bad,
            )
    with pytest.raises(ValidationError):
        JudgeCommitment(
            bundle_version="hidden-judge-v2",  # type: ignore[arg-type]
            canonicalization="canonical-json-v1",
            bundle_sha256=_SHA_ZERO,
        )


def test_canonical_hidden_judge_bytes_are_deterministic_and_compact() -> None:
    bundle = _judge_bundle()
    first = canonical_hidden_judge_bytes(bundle)
    assert first == canonical_hidden_judge_bytes(bundle)
    assert b"\n" not in first
    assert b", " not in first
    assert b": " not in first
    assert commit_hidden_judge(bundle).bundle_sha256 == sha256_bytes(first)


def test_key_ordering_cannot_change_the_judge_commitment() -> None:
    bundle = _judge_bundle()
    reordered = HiddenJudgeBundle.model_validate(
        json.loads(
            json.dumps(bundle.model_dump(mode="json"), sort_keys=True)
        )
    )
    shuffled = HiddenJudgeBundle.model_validate(
        json.loads(
            json.dumps(bundle.model_dump(mode="json"), sort_keys=False)
        )
    )
    assert commit_hidden_judge(reordered) == commit_hidden_judge(bundle)
    assert commit_hidden_judge(shuffled) == commit_hidden_judge(bundle)


def test_changing_hidden_concept_data_changes_the_commitment() -> None:
    bundle = _judge_bundle()
    original = commit_hidden_judge(bundle).bundle_sha256
    first_case = bundle.cases[0]
    concept = first_case.expected_concepts[0]

    for update in (
        {"semantic_description": "A different synthetic description."},
        {"criticality": ConceptCriticality.NONCRITICAL},
        {"primary_gap_kind": GapKind.MISSING_INFORMATION},
        {"exact_subject_key": "another-placeholder"},
        {"materiality_rationale": "Another synthetic rationale."},
    ):
        mutated = bundle.model_copy(
            update={
                "cases": (
                    first_case.model_copy(
                        update={"expected_concepts": (concept.model_copy(update=update),)}
                    ),
                    *bundle.cases[1:],
                )
            }
        )
        assert commit_hidden_judge(mutated).bundle_sha256 != original


def test_judge_commitment_does_not_carry_judge_contents() -> None:
    commitment = commit_hidden_judge(_judge_bundle())
    corpus = json.dumps(commitment.model_dump(mode="json"))
    assert "placeholder" not in corpus.lower()
    assert set(JudgeCommitment.model_fields) == {
        "bundle_version",
        "canonicalization",
        "bundle_sha256",
    }


# --------------------------------------------------------------------------------------
# 53-55  ExperimentManifest
# --------------------------------------------------------------------------------------


def test_experiment_manifest_has_exactly_the_frozen_field_set() -> None:
    assert set(ExperimentManifest.model_fields) == {
        "manifest_version",
        "contestant_freeze_path",
        "contestant_freeze_sha256",
        "comparative_protocol_module_sha256",
        "sealed_exam_manifest_module_sha256",
        "adjudication_mechanism_path",
        "adjudication_mechanism_sha256",
        "semantic_rubric_path",
        "semantic_rubric_sha256",
        "holdout_input_manifest_path",
        "holdout_input_manifest_sha256",
        "execution_assignment_path",
        "execution_assignment_sha256",
        "judge_commitment",
    }


def test_experiment_manifest_rejects_extras_and_results(sealed_tree: Path) -> None:
    payload = _manifest(sealed_tree).model_dump(mode="json")
    for leak in ("winner", "scores", "contestant_outputs", "created_at", "api_key"):
        polluted = dict(payload)
        polluted[leak] = "x"
        with pytest.raises(ValidationError):
            ExperimentManifest.model_validate(polluted)


@pytest.mark.parametrize(
    "field",
    [
        "contestant_freeze_path",
        "adjudication_mechanism_path",
        "semantic_rubric_path",
        "holdout_input_manifest_path",
        "execution_assignment_path",
    ],
)
@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.json", "a/../../b.json", "~/x.json"])
def test_experiment_manifest_rejects_unsafe_paths(
    sealed_tree: Path, field: str, bad: str
) -> None:
    payload = _manifest(sealed_tree).model_dump(mode="json")
    payload[field] = bad
    with pytest.raises(ValidationError):
        ExperimentManifest.model_validate(payload)


def test_experiment_manifest_serialization_is_deterministic(
    manifest: ExperimentManifest, tmp_path: Path
) -> None:
    first = tmp_path / "a" / "experiment-manifest.json"
    second = tmp_path / "b" / "experiment-manifest.json"
    write_experiment_manifest(first, manifest)
    write_experiment_manifest(second, manifest)
    write_experiment_manifest(first, manifest)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8").endswith("}\n")
    assert load_experiment_manifest(first) == manifest
    lowered = first.read_text(encoding="utf-8").lower()
    for forbidden in ("created_at", "timestamp", "hostname", "username", "/users/", "api_key"):
        assert forbidden not in lowered, forbidden


# --------------------------------------------------------------------------------------
# 56-61  Phase-1 verification
# --------------------------------------------------------------------------------------


def test_phase1_verifier_accepts_a_fully_sealed_experiment(
    manifest: ExperimentManifest, sealed_tree: Path
) -> None:
    assert verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION) is None


def test_phase1_verifier_signature_cannot_accept_a_judge(
    manifest: ExperimentManifest, sealed_tree: Path
) -> None:
    signature = inspect.signature(verify_phase1_experiment)
    assert list(signature.parameters) == ["manifest", "repo_root", "sdk_version"]
    rendered = str(signature).lower()
    assert "judge" not in rendered
    source = inspect.getsource(verify_phase1_experiment)
    for forbidden in (
        "HiddenJudgeBundle",
        "judge_bundle",
        "judge_path",
        "canonical_hidden_judge_bytes",
        "validate_hidden_judge_case",
        "verify_revealed_judge_bundle",
    ):
        assert forbidden not in source, forbidden
    with pytest.raises(TypeError):
        verify_phase1_experiment(  # type: ignore[call-arg]
            manifest, sealed_tree, judge_bundle_path=sealed_tree / "judge-bundle.json"
        )


def test_phase1_verifier_never_reads_a_hidden_judge_file(
    manifest: ExperimentManifest, sealed_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    judge_path = sealed_tree / "evals/comparative/judge-bundle.json"
    judge_path.write_text(
        json.dumps(_judge_bundle().model_dump(mode="json")), encoding="utf-8"
    )
    accessed: list[str] = []
    original_bytes = Path.read_bytes
    original_text = Path.read_text

    def _record_bytes(self: Path) -> bytes:
        accessed.append(str(self))
        return original_bytes(self)

    def _record_text(self: Path, *args: object, **kwargs: object) -> str:
        accessed.append(str(self))
        return original_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_bytes", _record_bytes)
    monkeypatch.setattr(Path, "read_text", _record_text)
    verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION)
    monkeypatch.undo()

    assert accessed
    assert not [path for path in accessed if "judge" in path]


def test_phase1_verifier_never_writes(
    manifest: ExperimentManifest, sealed_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("phase-1 verification must never write")

    monkeypatch.setattr(Path, "write_text", _forbidden)
    monkeypatch.setattr(Path, "write_bytes", _forbidden)
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    monkeypatch.setattr(Path, "unlink", _forbidden)
    assert verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION) is None


def test_phase1_verifier_accepts_a_judge_commitment_without_any_judge_content(
    manifest: ExperimentManifest, sealed_tree: Path
) -> None:
    assert not list((sealed_tree / "evals/comparative").glob("*judge*"))
    assert manifest.judge_commitment.bundle_sha256
    assert verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION) is None


def test_phase1_verifier_validates_holdout_inputs_against_commitments(
    manifest: ExperimentManifest, sealed_tree: Path
) -> None:
    target = sealed_tree / "evals/comparative/holdouts/SYNTH-CASE-01/input.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["fixture_id"] = "SYNTH-CASE-99"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ExperimentSealViolation):
        verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION)


def test_phase1_verifier_rejects_family_disagreement(sealed_tree: Path) -> None:
    """The committed family must agree with the family declared inside the input."""
    holdouts = load_holdout_input_manifest(sealed_tree / HOLDOUT_MANIFEST_PATH)
    first = holdouts.cases[0]
    assert first.family is HoldoutFamily.GREENFIELD

    input_path = sealed_tree / first.input_path
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["family"] = HoldoutFamily.BROWNFIELD.value
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    rehashed = first.model_copy(
        update={"input_sha256": sha256_bytes(input_path.read_bytes())}
    )
    write_holdout_input_manifest(
        sealed_tree / HOLDOUT_MANIFEST_PATH,
        holdouts.model_copy(update={"cases": (rehashed, *holdouts.cases[1:])}),
    )

    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_phase1_experiment(_manifest(sealed_tree), sealed_tree, sdk_version=_SDK_VERSION)
    message = str(excinfo.value)
    assert "family" in message
    assert "brownfield" in message
    assert "greenfield" in message


# --------------------------------------------------------------------------------------
# 62-67  tamper detection
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    [
        CONTESTANT_FREEZE_PATH,
        MECHANISM_PATH,
        RUBRIC_PATH,
        HOLDOUT_MANIFEST_PATH,
        ASSIGNMENT_PATH,
        COMPARATIVE_PROTOCOL_MODULE_PATH,
        SEALED_EXAM_MANIFEST_MODULE_PATH,
        "evals/comparative/holdouts/SYNTH-CASE-04/input.json",
    ],
)
def test_tampering_a_sealed_artifact_fails_phase1(
    manifest: ExperimentManifest, sealed_tree: Path, relative: str
) -> None:
    target = sealed_tree / relative
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION)
    assert Path(relative).name in str(excinfo.value) or relative in str(excinfo.value)


def test_tampering_a_frozen_contestant_file_fails_phase1(
    manifest: ExperimentManifest, sealed_tree: Path
) -> None:
    target = sealed_tree / "src/foundry/adapters/intelligence/xai.py"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION)
    assert "xai.py" in str(excinfo.value)


def test_hand_edited_mechanism_that_still_hashes_is_impossible(
    sealed_tree: Path,
) -> None:
    mechanism_path = sealed_tree / MECHANISM_PATH
    payload = json.loads(mechanism_path.read_text(encoding="utf-8"))
    payload["identity_blind"] = False
    mechanism_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", "utf-8")
    tampered = _manifest(sealed_tree)
    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_phase1_experiment(tampered, sealed_tree, sdk_version=_SDK_VERSION)
    assert "adjudication mechanism" in str(excinfo.value).lower()


def test_hand_edited_rubric_that_still_hashes_is_impossible(sealed_tree: Path) -> None:
    rubric_path = sealed_tree / RUBRIC_PATH
    payload = json.loads(rubric_path.read_text(encoding="utf-8"))
    payload["one_to_one_matching"] = False
    rubric_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", "utf-8")
    tampered = _manifest(sealed_tree)
    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_phase1_experiment(tampered, sealed_tree, sdk_version=_SDK_VERSION)
    assert "semantic rubric" in str(excinfo.value).lower()


def test_unbalanced_execution_assignment_fails_phase1(sealed_tree: Path) -> None:
    assignment = load_execution_assignment(sealed_tree / ASSIGNMENT_PATH)
    skewed = tuple(
        item.model_copy(
            update={
                "first_contestant": ContestantId.FOUNDRY,
                "second_contestant": ContestantId.BASELINE,
            }
        )
        for item in assignment.assignments
    )
    write_execution_assignment(
        sealed_tree / ASSIGNMENT_PATH,
        assignment.model_copy(update={"assignments": skewed}),
    )
    with pytest.raises(ExperimentSealViolation):
        verify_phase1_experiment(_manifest(sealed_tree), sealed_tree, sdk_version=_SDK_VERSION)


def test_assignment_case_mismatch_fails_phase1(sealed_tree: Path) -> None:
    assignment = load_execution_assignment(sealed_tree / ASSIGNMENT_PATH)
    renamed = (
        assignment.assignments[0].model_copy(update={"case_id": "SYNTH-CASE-99"}),
        *assignment.assignments[1:],
    )
    write_execution_assignment(
        sealed_tree / ASSIGNMENT_PATH,
        assignment.model_copy(update={"assignments": renamed}),
    )
    with pytest.raises(ExperimentSealViolation):
        verify_phase1_experiment(_manifest(sealed_tree), sealed_tree, sdk_version=_SDK_VERSION)


@pytest.mark.parametrize(
    "relative",
    [
        CONTESTANT_FREEZE_PATH,
        MECHANISM_PATH,
        RUBRIC_PATH,
        HOLDOUT_MANIFEST_PATH,
        ASSIGNMENT_PATH,
        "evals/comparative/holdouts/SYNTH-CASE-07/input.json",
    ],
)
def test_missing_sealed_artifact_fails_cleanly(
    manifest: ExperimentManifest, sealed_tree: Path, relative: str
) -> None:
    (sealed_tree / relative).unlink()
    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION)
    assert "missing" in str(excinfo.value).lower()


def test_path_escaping_the_repository_is_refused_at_verification(
    sealed_tree: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = sealed_tree / "evals/comparative/linked-rubric.json"
    link.symlink_to(outside)
    manifest = _manifest(sealed_tree).model_copy(
        update={"semantic_rubric_path": "evals/comparative/linked-rubric.json"}
    )
    with pytest.raises(ExperimentSealViolation):
        verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION)


# --------------------------------------------------------------------------------------
# 74  unrelated files
# --------------------------------------------------------------------------------------


def test_unrelated_file_changes_do_not_invalidate_the_experiment(
    manifest: ExperimentManifest, sealed_tree: Path
) -> None:
    notes = sealed_tree / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "unrelated.txt").write_text("scratch\n", encoding="utf-8")
    (sealed_tree / "README.md").write_text("changed\n", encoding="utf-8")
    assert verify_phase1_experiment(manifest, sealed_tree, sdk_version=_SDK_VERSION) is None


# --------------------------------------------------------------------------------------
# 69-73  Phase-2 judge reveal
# --------------------------------------------------------------------------------------


def _write_judge(path: Path, bundle: HiddenJudgeBundle) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle.model_dump(mode="json")), encoding="utf-8")
    return path


def test_phase2_accepts_a_judge_bundle_matching_the_commitment(
    manifest: ExperimentManifest, sealed_tree: Path, tmp_path: Path
) -> None:
    bundle = _judge_bundle()
    judge_path = _write_judge(tmp_path / "vault" / "judge-bundle.json", bundle)
    revealed = verify_revealed_judge_bundle(manifest, judge_path, sealed_tree)
    assert revealed == bundle
    assert [case.case_id for case in revealed.cases] == list(_CASE_IDS)


def test_phase2_rejects_a_judge_bundle_that_breaks_the_commitment(
    sealed_tree: Path, tmp_path: Path
) -> None:
    manifest = _manifest(sealed_tree, judge_sha=_SHA_ZERO)
    judge_path = _write_judge(tmp_path / "vault" / "judge-bundle.json", _judge_bundle())
    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_revealed_judge_bundle(manifest, judge_path, sealed_tree)
    assert "commitment" in str(excinfo.value).lower()


def test_phase2_rejects_a_mutated_judge_bundle(
    manifest: ExperimentManifest, sealed_tree: Path, tmp_path: Path
) -> None:
    bundle = _judge_bundle()
    first = bundle.cases[0]
    mutated = bundle.model_copy(
        update={
            "cases": (
                first.model_copy(
                    update={
                        "expected_concepts": (
                            first.expected_concepts[0].model_copy(
                                update={"criticality": ConceptCriticality.NONCRITICAL}
                            ),
                        )
                    }
                ),
                *bundle.cases[1:],
            )
        }
    )
    judge_path = _write_judge(tmp_path / "vault" / "judge-bundle.json", mutated)
    with pytest.raises(ExperimentSealViolation):
        verify_revealed_judge_bundle(manifest, judge_path, sealed_tree)


def test_phase2_requires_the_same_twelve_case_ids(
    sealed_tree: Path, tmp_path: Path
) -> None:
    bundle = _judge_bundle()
    renamed = bundle.model_copy(
        update={
            "cases": (
                bundle.cases[0].model_copy(update={"case_id": "SYNTH-CASE-99"}),
                *bundle.cases[1:],
            )
        }
    )
    manifest = _manifest(sealed_tree, judge_sha=commit_hidden_judge(renamed).bundle_sha256)
    judge_path = _write_judge(tmp_path / "vault" / "judge-bundle.json", renamed)
    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_revealed_judge_bundle(manifest, judge_path, sealed_tree)
    assert "SYNTH-CASE-99" in str(excinfo.value)


def test_phase2_grounds_judge_evidence_ids_in_the_visible_input(
    sealed_tree: Path, tmp_path: Path
) -> None:
    bundle = _judge_bundle()
    first = bundle.cases[0]
    ungrounded = bundle.model_copy(
        update={
            "cases": (
                first.model_copy(
                    update={
                        "expected_concepts": (
                            first.expected_concepts[0].model_copy(
                                update={"evidence_event_ids": ("EVT-NOT-PRESENT",)}
                            ),
                        )
                    }
                ),
                *bundle.cases[1:],
            )
        }
    )
    manifest = _manifest(sealed_tree, judge_sha=commit_hidden_judge(ungrounded).bundle_sha256)
    judge_path = _write_judge(tmp_path / "vault" / "judge-bundle.json", ungrounded)
    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_revealed_judge_bundle(manifest, judge_path, sealed_tree)
    assert "EVT-NOT-PRESENT" in str(excinfo.value)


def test_phase2_never_writes_or_repairs(
    manifest: ExperimentManifest,
    sealed_tree: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge_path = _write_judge(tmp_path / "vault" / "judge-bundle.json", _judge_bundle())
    before = judge_path.read_bytes()

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("phase-2 verification must never write")

    monkeypatch.setattr(Path, "write_text", _forbidden)
    monkeypatch.setattr(Path, "write_bytes", _forbidden)
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    monkeypatch.setattr(Path, "unlink", _forbidden)
    verify_revealed_judge_bundle(manifest, judge_path, sealed_tree)
    monkeypatch.undo()
    assert judge_path.read_bytes() == before


def test_phase2_judge_bundle_may_live_outside_the_repository(
    manifest: ExperimentManifest, sealed_tree: Path, tmp_path: Path
) -> None:
    judge_path = _write_judge(tmp_path / "elsewhere" / "vault.json", _judge_bundle())
    assert not str(judge_path).startswith(str(sealed_tree))
    assert verify_revealed_judge_bundle(manifest, judge_path, sealed_tree) == _judge_bundle()


def test_phase2_missing_judge_bundle_fails_cleanly(
    manifest: ExperimentManifest, sealed_tree: Path, tmp_path: Path
) -> None:
    with pytest.raises(ExperimentSealViolation) as excinfo:
        verify_revealed_judge_bundle(manifest, tmp_path / "absent.json", sealed_tree)
    assert "missing" in str(excinfo.value).lower()


# --------------------------------------------------------------------------------------
# module hygiene and 9J1 scope guards
# --------------------------------------------------------------------------------------


def _module_source() -> str:
    return (REPO_ROOT / SEALED_EXAM_MANIFEST_MODULE_PATH).read_text(encoding="utf-8")


def _imported_roots(source: str) -> Iterator[str]:
    import ast

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            yield node.module.split(".")[0]


def test_sealed_module_imports_no_provider_sdk_or_shell() -> None:
    source = _module_source()
    assert set(_imported_roots(source)) <= {
        "__future__",
        "collections",
        "enum",
        "foundry",
        "json",
        "pathlib",
        "pydantic",
        "typing",
    }
    for forbidden in (
        "xai_sdk",
        "import openai",
        "from openai",
        "anthropic",
        "subprocess",
        "requests",
        "httpx",
        "urllib",
        "socket",
    ):
        assert forbidden not in source, forbidden


def test_sealed_module_reuses_the_existing_sha_primitives() -> None:
    source = _module_source()
    assert "from foundry.evaluation.experiment_manifest import" in source
    assert "hashlib" not in source


def test_sealed_module_carries_no_development_fixture_answers() -> None:
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


def test_hidden_judge_bundle_is_not_stored_in_public_comparative_tree() -> None:
    comparative = REPO_ROOT / "evals/comparative"

    assert not list(comparative.rglob("hidden-judge.json"))

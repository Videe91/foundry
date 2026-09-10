"""Task 9K3-A reveal, mapping, aggregation, writing and verification.

Every fixture here is SYNTHETIC. This module never opens the real
`evals/comparative/execution-assignment.json`, the real hidden judge, the real
Phase-1 execution records, or the real Phase-2 primary adjudications, and it never
asserts anything about the real `evals/comparative/results/` tree -- the fixture
lifecycle defect found in 9K1 is not repeated here.

A socket guard is installed on every reveal and verify test, so a model call would
fail loudly rather than pass quietly.
"""

from __future__ import annotations

import json
import shutil
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from foundry.domain.gaps import GapKind
from foundry.evaluation.comparative_protocol import (
    AdjudicationState,
    ConceptCriticality,
    ConceptJudgment,
    ExpectedConcept,
    HiddenJudgeBundle,
    HiddenJudgeCase,
    PredictionDisposition,
    PredictionJudgment,
    SafetyLabel,
    SystemAdjudication,
)
from foundry.evaluation.experiment_manifest import sha256_bytes
from foundry.evaluation.loader import load_input
from foundry.evaluation.phase1_execution import (
    PHASE1_OUTPUT_MANIFEST_FILENAME,
    PHASE1_ROOT,
    AttemptOutcome,
    AttemptRecord,
    Phase1ArtifactDigest,
    Phase1ExecutionRecord,
    Phase1OutputManifest,
    Phase1TerminalStatus,
)
from foundry.evaluation.phase2_adjudication import (
    Phase2ArtifactDigest,
    Phase2CallRecord,
    Phase2OutputManifest,
    PrimaryCaseAdjudication,
    blind_output_relative,
    manifest_relative,
    phase2_canonical_bytes,
    primary_relative,
)
from foundry.evaluation.phase3_runner import (
    PHASE2_ADJUDICATOR_COMMIT,
    PHASE2_OUTPUT_COMMIT,
    REPORT_FILENAME,
    RESULT_FILENAME,
    RESULTS_ROOT,
    SCORER_MODULE_PATHS,
    IdentityMappingIntegrityFailure,
    Phase3AlreadyFrozen,
    Phase3HumanReviewRequired,
    Phase3SealViolation,
    aggregate_by_contestant,
    blind_phase1_summary,
    blind_preflight,
    default_phase2_verifier,
    render_report,
    result_canonical_bytes,
    reveal_and_score,
    verify_result,
)
from foundry.evaluation.phase3_scoring import (
    BlindCaseScore,
    ComparativeResult,
    DirectionalConclusion,
    ExactCounts,
    SemanticCounts,
    SystemCaseCounts,
    safety_counts_from_labels,
)
from foundry.evaluation.sealed_exam_manifest import (
    BlindSystemLabel,
    CaseExecutionAssignment,
    ContestantId,
    ExecutionAssignmentManifest,
    canonical_hidden_judge_bytes,
    load_holdout_input_manifest,
    write_execution_assignment,
)
from foundry.intelligence.comparison import BlindPrediction

REPO_ROOT = Path(__file__).resolve().parents[2]
SCORER_COMMIT = "3" * 40
_T0 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)

EXPERIMENT_MANIFEST = "evals/comparative/experiment-manifest.json"
HOLDOUT_MANIFEST = "evals/comparative/holdout-inputs.json"
ASSIGNMENT_RELATIVE = "evals/comparative/execution-assignment.json"
PHASE1_MANIFEST_RELATIVE = PHASE1_ROOT + "/" + PHASE1_OUTPUT_MANIFEST_FILENAME

_BASE_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")

_SHA_A = "a" * 64
_SHA_B = "b" * 64


# --------------------------------------------------------------------------- guards


def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any outbound socket in a scoring path is a defect, not a slow test."""

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("PHASE3 MADE A NETWORK CALL")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_network(monkeypatch)


# --------------------------------------------------------------------------- tree


@pytest.fixture
def scored_repo(tmp_path: Path) -> Path:
    return build_scored_repo(tmp_path)


def build_scored_repo(tmp_path: Path) -> Path:
    """A synthetic tree carrying visible holdouts, blind outputs and blind judgments.

    The real execution assignment is NEVER copied; a synthetic mixed assignment is
    generated instead, so this module cannot learn the sealed mapping.
    """
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "src", root / "src", ignore=_BASE_IGNORE)
    for relative in (HOLDOUT_MANIFEST, EXPERIMENT_MANIFEST):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    shutil.copytree(
        REPO_ROOT / "evals/comparative/holdouts",
        root / "evals/comparative/holdouts",
        ignore=_BASE_IGNORE,
    )
    assert not (root / ASSIGNMENT_RELATIVE).exists()

    bundle = _synthetic_judge(root)
    _rewrite_judge_commitment(root, bundle)
    assignment = _synthetic_assignment(_case_ids(root))
    _write_assignment(root, assignment)
    _write_blind_outputs(root, bundle, assignment)
    _write_primary_adjudications(root, bundle, assignment)
    _write_phase2_manifest(root, bundle)
    return root


@pytest.fixture
def judge_path(scored_repo: Path, tmp_path: Path) -> Path:
    return build_judge_path(scored_repo, tmp_path)


def build_judge_path(scored_repo: Path, tmp_path: Path) -> Path:
    outside = tmp_path / "sealed" / "hidden-judge.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(canonical_hidden_judge_bytes(_synthetic_judge(scored_repo)))
    return outside


@pytest.fixture
def blob_reader(scored_repo: Path) -> Callable[[str, str], bytes]:
    return build_blob_reader(scored_repo)


def build_blob_reader(scored_repo: Path) -> Callable[[str, str], bytes]:
    """Serve the working-tree bytes as if they were the frozen scorer commit."""

    def read(_commit: str, path: str) -> bytes:
        return (scored_repo / path).read_bytes()

    return read


def _case_ids(root: Path) -> tuple[str, ...]:
    manifest = load_holdout_input_manifest(root / HOLDOUT_MANIFEST)
    return tuple(sorted(case.case_id for case in manifest.cases))


def _first_event_id(root: Path, case_id: str) -> str:
    manifest = load_holdout_input_manifest(root / HOLDOUT_MANIFEST)
    commitment = next(case for case in manifest.cases if case.case_id == case_id)
    return load_input((root / commitment.input_path).parent).events[0].event_id


def _synthetic_judge(root: Path) -> HiddenJudgeBundle:
    """One critical and one noncritical grounded concept per visible case."""
    cases = tuple(
        HiddenJudgeCase(
            case_id=case_id,
            expected_concepts=(
                ExpectedConcept(
                    concept_id="C-001",
                    semantic_description="a material question remains open",
                    primary_gap_kind=GapKind.MISSING_INFORMATION,
                    criticality=ConceptCriticality.CRITICAL,
                    exact_subject_key="open-question",
                    evidence_event_ids=(_first_event_id(root, case_id),),
                    evidence_basis="the first visible event",
                    materiality_rationale="downstream work cannot proceed without it",
                ),
                ExpectedConcept(
                    concept_id="C-002",
                    semantic_description="a secondary question remains open",
                    primary_gap_kind=GapKind.AMBIGUITY,
                    criticality=ConceptCriticality.NONCRITICAL,
                    exact_subject_key="second-question",
                    evidence_event_ids=(_first_event_id(root, case_id),),
                    evidence_basis="the first visible event",
                    materiality_rationale="it shapes later sequencing",
                ),
            ),
        )
        for case_id in _case_ids(root)
    )
    return HiddenJudgeBundle(bundle_version="hidden-judge-v1", cases=cases)


def _rewrite_judge_commitment(root: Path, bundle: HiddenJudgeBundle) -> None:
    path = root / EXPERIMENT_MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["judge_commitment"]["bundle_sha256"] = sha256_bytes(
        canonical_hidden_judge_bytes(bundle)
    )
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _synthetic_assignment(case_ids: tuple[str, ...]) -> ExecutionAssignmentManifest:
    """A deliberately MIXED mapping: Foundry is SYSTEM-A in half the cases only."""
    assignments = []
    for index, case_id in enumerate(case_ids):
        foundry_is_a = index % 2 == 0
        assignments.append(
            CaseExecutionAssignment(
                case_id=case_id,
                first_contestant=(
                    ContestantId.FOUNDRY if foundry_is_a else ContestantId.BASELINE
                ),
                second_contestant=(
                    ContestantId.BASELINE if foundry_is_a else ContestantId.FOUNDRY
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
        manifest_version="execution-assignment-v1",
        assignments=tuple(assignments),
    )


def _write_assignment(root: Path, assignment: ExecutionAssignmentManifest) -> None:
    path = root / ASSIGNMENT_RELATIVE
    write_execution_assignment(path, assignment)
    manifest_path = root / EXPERIMENT_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["execution_assignment_path"] = ASSIGNMENT_RELATIVE
    manifest["execution_assignment_sha256"] = sha256_bytes(path.read_bytes())
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def _strong_predictions() -> tuple[BlindPrediction, ...]:
    return (
        _prediction(1, GapKind.MISSING_INFORMATION, "open-question"),
        _prediction(2, GapKind.AMBIGUITY, "second-question"),
    )


def _weak_predictions() -> tuple[BlindPrediction, ...]:
    return (_prediction(1, GapKind.UNRESOLVED_RISK, "unrelated-worry"),)


def _prediction(index: int, kind: GapKind, subject: str) -> BlindPrediction:
    return BlindPrediction(
        prediction_id=f"P-{index:03d}",
        kind=kind,
        subject_key=subject,
        description="an open material question",
        source_event_ids=(),
        confidence=0.6,
    )


def _predictions_for(assignment: ExecutionAssignmentManifest, case_id: str, label: str):
    """The strong output always belongs to whichever label Foundry holds in this case."""
    item = next(a for a in assignment.assignments if a.case_id == case_id)
    return _strong_predictions() if item.foundry_blind_label.value == label else _weak_predictions()


def _write_blind_outputs(
    root: Path, bundle: HiddenJudgeBundle, assignment: ExecutionAssignmentManifest
) -> None:
    for case in bundle.cases:
        for label in ("SYSTEM-A", "SYSTEM-B"):
            target = root / blind_output_relative(case.case_id, label)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "system_label": label,
                        "predictions": [
                            prediction.model_dump(mode="json")
                            for prediction in _predictions_for(assignment, case.case_id, label)
                        ],
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )


def _strong_adjudication(case_id: str, label: str) -> SystemAdjudication:
    return SystemAdjudication(
        case_id=case_id,
        system_label=label,  # type: ignore[arg-type]
        concept_judgments=(
            _matched("C-001", "P-001", gap_kind_correct=True),
            _matched("C-002", "P-002", gap_kind_correct=True),
        ),
        prediction_judgments=(
            _judged("P-001", PredictionDisposition.MATCHED_EXPECTED),
            _judged("P-002", PredictionDisposition.MATCHED_EXPECTED, bundled=("C-002",)),
        ),
    )


def _weak_adjudication(case_id: str, label: str) -> SystemAdjudication:
    return SystemAdjudication(
        case_id=case_id,
        system_label=label,  # type: ignore[arg-type]
        concept_judgments=(_unmatched("C-001"), _unmatched("C-002")),
        prediction_judgments=(
            _judged(
                "P-001",
                PredictionDisposition.UNSUPPORTED_OR_IMMATERIAL,
                safety_labels=(SafetyLabel.UNAUTHORIZED_CONFLICT_RESOLUTION,),
            ),
        ),
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


def _write_primary_adjudications(
    root: Path, bundle: HiddenJudgeBundle, assignment: ExecutionAssignmentManifest
) -> None:
    for case in bundle.cases:
        item = next(a for a in assignment.assignments if a.case_id == case.case_id)
        strong_label = item.foundry_blind_label.value
        result = PrimaryCaseAdjudication(
            case_id=case.case_id,
            system_a=(
                _strong_adjudication(case.case_id, "SYSTEM-A")
                if strong_label == "SYSTEM-A"
                else _weak_adjudication(case.case_id, "SYSTEM-A")
            ),
            system_b=(
                _strong_adjudication(case.case_id, "SYSTEM-B")
                if strong_label == "SYSTEM-B"
                else _weak_adjudication(case.case_id, "SYSTEM-B")
            ),
        )
        target = root / primary_relative(case.case_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(phase2_canonical_bytes(result))


def _write_phase2_manifest(root: Path, bundle: HiddenJudgeBundle) -> None:
    root_path = root / manifest_relative()
    root_path.parent.mkdir(parents=True, exist_ok=True)
    root_path.write_bytes(phase2_canonical_bytes(_phase2_manifest(root, bundle)))


def _phase2_manifest(root: Path, bundle: HiddenJudgeBundle) -> Phase2OutputManifest:
    case_sequence = tuple(case.case_id for case in bundle.cases)
    calls = tuple(
        Phase2CallRecord(
            case_id=case_id,
            attempt_execution_ids=(f"00000000-0000-4000-8000-{index:012d}",),
            infrastructure_retry_count=0,
            packet_sha256=_SHA_A,
            primary_result_path=primary_relative(case_id),
            primary_result_sha256=sha256_bytes((root / primary_relative(case_id)).read_bytes()),
            provider_response_id=None,
            input_tokens=777,
            output_tokens=888,
            wall_clock_ms=1000,
            uncertain_item_count=0,
        )
        for index, case_id in enumerate(case_sequence, start=1)
    )
    return Phase2OutputManifest(
        manifest_version="intent-comparative-phase2-output-v1",
        experiment_manifest_sha256=sha256_bytes((root / EXPERIMENT_MANIFEST).read_bytes()),
        phase1_output_commit="a" * 40,
        phase1_runner_commit="d" * 40,
        phase1_bundle_sha256=_SHA_B,
        hidden_judge_commitment_sha256=sha256_bytes(canonical_hidden_judge_bytes(bundle)),
        adjudication_mechanism_sha256=_SHA_A,
        semantic_rubric_sha256=_SHA_A,
        adjudicator_instruction_sha256=_SHA_A,
        adjudication_runner_commit="4" * 40,
        runner_artifacts=(
            Phase2ArtifactDigest(path="src/foundry/evaluation/phase2_runner.py", sha256=_SHA_A),
        ),
        provider="OpenAI",
        model="gpt-5.6-sol",
        reasoning_effort="high",
        api="Responses",
        store=False,
        tools_enabled=False,
        conversation_reuse=False,
        reasoning_effort_frozen_before_first_call=True,
        calls_per_case=1,
        sdk_package="openai",
        openai_sdk_version="2.9.0",
        infrastructure_retry_policy="one-immediate-retry-then-pause-resume-same-case-only",
        structural_failure_policy="stop-no-semantic-retry-no-repair",
        uncertainty_policy="freeze-and-escalate-to-blind-human-review",
        case_sequence=case_sequence,
        calls=calls,
        attempts=(),
        infrastructure_failures=0,
        infrastructure_retries=0,
        uncertain_item_count=0,
        human_review_required=False,
        started_at=_T0,
        completed_at=_T0,
    )


def _phase1_manifest(
    root: Path, assignment: ExecutionAssignmentManifest
) -> Phase1OutputManifest:
    """24 synthetic terminal slots that AGREE with the synthetic assignment."""
    case_sequence = tuple(item.case_id for item in assignment.assignments)
    executions: list[Phase1ExecutionRecord] = []
    attempts: list[AttemptRecord] = []
    counter = 0
    for item in assignment.assignments:
        for contestant in (ContestantId.FOUNDRY, ContestantId.BASELINE):
            counter += 1
            execution_id = f"11111111-0000-4000-8000-{counter:012d}"
            label = (
                item.foundry_blind_label
                if contestant is ContestantId.FOUNDRY
                else item.baseline_blind_label
            )
            position = 1 if item.first_contestant is contestant else 2
            executions.append(
                Phase1ExecutionRecord(
                    case_id=item.case_id,
                    contestant_id=contestant,
                    blind_label=label,
                    execution_position=position,  # type: ignore[arg-type]
                    terminal_status=Phase1TerminalStatus.VALID,
                    attempt_execution_ids=(execution_id,),
                    infrastructure_retry_count=0,
                    raw_result_path=f"evals/comparative/phase1/raw/{item.case_id}/x.json",
                    raw_result_sha256=_SHA_A,
                    blind_output_path=blind_output_relative(item.case_id, label.value),
                    blind_output_sha256=_SHA_B,
                    input_tokens=100 if contestant is ContestantId.FOUNDRY else 10,
                    output_tokens=200 if contestant is ContestantId.FOUNDRY else 20,
                    cost_usd=0.5 if contestant is ContestantId.FOUNDRY else 0.25,
                    wall_clock_ms=4000 if contestant is ContestantId.FOUNDRY else 1000,
                )
            )
            attempts.append(
                AttemptRecord(
                    execution_id=execution_id,
                    case_id=item.case_id,
                    contestant_id=contestant,
                    blind_label=label,
                    execution_position=position,  # type: ignore[arg-type]
                    attempt_number=1,
                    started_at=_T0,
                    completed_at=_T0,
                    outcome=AttemptOutcome.VALID_RESULT,
                )
            )
    return Phase1OutputManifest(
        manifest_version="intent-comparative-phase1-output-v1",
        experiment_manifest_sha256=sha256_bytes((root / EXPERIMENT_MANIFEST).read_bytes()),
        pre_exam_audit_sha256=_SHA_A,
        runner_commit_sha="d" * 40,
        runner_artifacts=(
            Phase1ArtifactDigest(path="src/foundry/evaluation/phase1_runner.py", sha256=_SHA_A),
        ),
        provider="xAI",
        model="grok-4.6",
        reasoning_effort="high",
        sdk_package="xai-sdk",
        sdk_version="1.4.0",
        provider_revision=None,
        provider_revision_observable=False,
        pairing_policy="back-to-back",
        infrastructure_retry_policy=(
            "one-immediate-retry-then-pause-resume-same-slot-only"
        ),
        structural_failure_policy="terminal-no-semantic-retry",
        schema_incompatibility_policy="abort-experiment",
        case_sequence=case_sequence,
        executions=tuple(executions),
        attempts=tuple(attempts),
        total_contestant_slots=24,
        valid_results=24,
        structural_failures=0,
        infrastructure_failures=0,
        infrastructure_retries=0,
        started_at=_T0,
        completed_at=_T0,
    )


# --------------------------------------------------------------------------- harness


class _Spy:
    """Records the order in which the gated doors were opened."""

    def __init__(self) -> None:
        self.events: list[str] = []


def _harness(root: Path, spy: _Spy) -> dict[str, Any]:
    assignment = _synthetic_assignment(_case_ids(root))
    bundle = _synthetic_judge(root)

    def phase2_verifier(**_: object) -> Phase2OutputManifest:
        spy.events.append("phase2")
        return _phase2_manifest(root, bundle)

    def assignment_reader(path: Path) -> bytes:
        spy.events.append("assignment")
        return path.read_bytes()

    def phase1_manifest_loader(**_: object) -> Phase1OutputManifest:
        spy.events.append("phase1")
        return _phase1_manifest(root, assignment)

    return {
        "phase2_verifier": phase2_verifier,
        "assignment_reader": assignment_reader,
        "phase1_manifest_loader": phase1_manifest_loader,
    }


def _score(
    root: Path,
    judge: Path,
    reader: Callable[[str, str], bytes],
    spy: _Spy | None = None,
    **overrides: Any,
) -> ComparativeResult:
    harness = _harness(root, spy if spy is not None else _Spy())
    harness.update(overrides)
    return reveal_and_score(
        repo_root=root,
        scorer_commit_sha=SCORER_COMMIT,
        judge_bundle_path=judge,
        blob_reader=reader,
        **harness,
    )


# --------------------------------------------------------------------------- 30-32 blind


def test_blind_preflight_does_not_load_the_execution_assignment(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    """The assignment file is DELETED. Preflight must still pass."""
    (scored_repo / ASSIGNMENT_RELATIVE).unlink()
    spy = _Spy()
    report = blind_preflight(
        repo_root=scored_repo,
        scorer_commit_sha=SCORER_COMMIT,
        judge_bundle_path=judge_path,
        blob_reader=blob_reader,
        phase2_verifier=_harness(scored_repo, spy)["phase2_verifier"],
    )
    assert report.identity_mapping_accessed is False
    assert report.model_calls == 0
    assert spy.events == ["phase2"]


def test_blind_preflight_does_not_parse_the_identity_bearing_phase1_manifest(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    """A phase-1 manifest that cannot be PARSED is still hashable. Preflight passes."""
    corrupt = scored_repo / PHASE1_MANIFEST_RELATIVE
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_bytes(b'{"executions": "not-an-identity-record"}\n')
    summary = blind_phase1_summary(repo_root=scored_repo)
    assert summary.bundle_sha256 == sha256_bytes(corrupt.read_bytes())
    report = blind_preflight(
        repo_root=scored_repo,
        scorer_commit_sha=SCORER_COMMIT,
        judge_bundle_path=judge_path,
        blob_reader=blob_reader,
        phase2_verifier=_harness(scored_repo, _Spy())["phase2_verifier"],
    )
    assert report.case_sequence == _case_ids(scored_repo)


def test_default_phase2_verifier_is_wired_to_the_identity_blind_phase1_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foundry.evaluation import phase3_runner

    captured: dict[str, Any] = {}

    def fake_verify(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(phase3_runner, "verify_phase2_output", fake_verify)
    default_phase2_verifier(
        repo_root=Path("/nowhere"), judge_bundle_path=Path("/nowhere/judge.json")
    )
    assert captured["phase1_verifier"] is phase3_runner.blind_phase1_summary


# --------------------------------------------------------------------------- 33-35 gates


def test_the_scorer_freeze_is_verified_before_the_assignment_door_is_opened(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    spy = _Spy()
    _score(scored_repo, judge_path, blob_reader, spy)
    assert spy.events[0] == "phase2"
    assert spy.events.index("assignment") > 0


def test_an_altered_scorer_prevents_the_identity_reveal(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    target = scored_repo / SCORER_MODULE_PATHS[0]
    target.write_bytes(target.read_bytes() + b"\n# post-freeze edit\n")
    spy = _Spy()

    def committed(_commit: str, path: str) -> bytes:
        return (REPO_ROOT / path).read_bytes()

    with pytest.raises(Phase3SealViolation, match="SCORER FREEZE VIOLATION"):
        _score(scored_repo, judge_path, committed, spy)
    assert "assignment" not in spy.events


def test_an_existing_result_file_prevents_the_identity_reveal(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    existing = scored_repo / RESULTS_ROOT / RESULT_FILENAME
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("{}\n", encoding="utf-8")
    spy = _Spy()
    with pytest.raises(Phase3AlreadyFrozen):
        _score(scored_repo, judge_path, blob_reader, spy)
    assert "assignment" not in spy.events


def test_an_existing_report_file_also_prevents_the_identity_reveal(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    existing = scored_repo / RESULTS_ROOT / REPORT_FILENAME
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("# stale\n", encoding="utf-8")
    with pytest.raises(Phase3AlreadyFrozen):
        _score(scored_repo, judge_path, blob_reader)


# --------------------------------------------------------------------------- 36-41 mapping


def _blind_case(case_id: str, a_matched: int, b_matched: int) -> BlindCaseScore:
    return BlindCaseScore(
        case_id=case_id,
        system_a=_counts(a_matched),
        system_b=_counts(b_matched),
    )


def _counts(matched_critical: int) -> SystemCaseCounts:
    return SystemCaseCounts(
        semantic=SemanticCounts(
            matched_critical_concepts=matched_critical,
            total_critical_concepts=1,
            matched_concepts=matched_critical,
            total_concepts=1,
            gap_kind_correct_matches=matched_critical,
            matched_expected_predictions=matched_critical,
            supported_extra_predictions=0,
            unsupported_predictions=1 - matched_critical,
            redundant_predictions=0,
            total_predictions=1,
            bundled_concept_prediction_count=0,
        ),
        safety=safety_counts_from_labels(()),
        exact=ExactCounts(
            critical_exact_detected=matched_critical,
            critical_exact_missed=1 - matched_critical,
            noncritical_exact_detected=0,
            noncritical_exact_missed=0,
            false_exact_gaps=0,
            exact_identity_collisions=0,
        ),
    )


def _two_case_assignment(first_foundry_label: str, second_foundry_label: str):
    def build(case_id: str, foundry_label: str) -> CaseExecutionAssignment:
        foundry_is_a = foundry_label == "SYSTEM-A"
        return CaseExecutionAssignment(
            case_id=case_id,
            first_contestant=ContestantId.FOUNDRY,
            second_contestant=ContestantId.BASELINE,
            foundry_blind_label=(
                BlindSystemLabel.SYSTEM_A if foundry_is_a else BlindSystemLabel.SYSTEM_B
            ),
            baseline_blind_label=(
                BlindSystemLabel.SYSTEM_B if foundry_is_a else BlindSystemLabel.SYSTEM_A
            ),
        )

    return ExecutionAssignmentManifest(
        manifest_version="execution-assignment-v1",
        assignments=(build("H-1", first_foundry_label), build("H-2", second_foundry_label)),
    )


def _tiny_phase1(assignment: ExecutionAssignmentManifest) -> Any:
    """A two-case stand-in for a Phase-1 manifest.

    `Phase1OutputManifest` structurally requires all 12 cases and 24 slots, so the
    small per-case mapping tests use this narrow duck type instead. Only `.executions`
    and `.attempts` are ever read by `aggregate_by_contestant`.
    """
    executions = tuple(
        _TinyExecution(item.case_id, contestant, label)
        for item in assignment.assignments
        for contestant, label in (
            (ContestantId.FOUNDRY, item.foundry_blind_label),
            (ContestantId.BASELINE, item.baseline_blind_label),
        )
    )
    return SimpleNamespace(executions=executions, attempts=())


class _TinyExecution:
    def __init__(self, case_id: str, contestant: ContestantId, label: BlindSystemLabel) -> None:
        self.case_id = case_id
        self.contestant_id = contestant
        self.blind_label = label
        self.terminal_status = Phase1TerminalStatus.VALID
        self.infrastructure_retry_count = 0
        self.input_tokens = 1
        self.output_tokens = 2
        self.cost_usd = 0.5
        self.wall_clock_ms = 1000


def test_foundry_as_system_a_aggregates_the_system_a_column() -> None:
    metrics = aggregate_by_contestant(
        (_blind_case("H-1", 1, 0), _blind_case("H-2", 1, 0)),
        _two_case_assignment("SYSTEM-A", "SYSTEM-A"),
        _tiny_phase1(_two_case_assignment("SYSTEM-A", "SYSTEM-A")),
    )
    assert metrics.foundry.counts.semantic.matched_critical_concepts == 2
    assert metrics.baseline.counts.semantic.matched_critical_concepts == 0


def test_foundry_as_system_b_aggregates_the_system_b_column() -> None:
    metrics = aggregate_by_contestant(
        (_blind_case("H-1", 0, 1), _blind_case("H-2", 0, 1)),
        _two_case_assignment("SYSTEM-B", "SYSTEM-B"),
        _tiny_phase1(_two_case_assignment("SYSTEM-B", "SYSTEM-B")),
    )
    assert metrics.foundry.counts.semantic.matched_critical_concepts == 2
    assert metrics.baseline.counts.semantic.matched_critical_concepts == 0


def test_mapping_is_applied_per_case_and_mixed_assignments_aggregate_correctly() -> None:
    assignment = _two_case_assignment("SYSTEM-A", "SYSTEM-B")
    metrics = aggregate_by_contestant(
        (_blind_case("H-1", 1, 0), _blind_case("H-2", 0, 1)),
        assignment,
        _tiny_phase1(assignment),
    )
    assert metrics.foundry.counts.semantic.matched_critical_concepts == 2
    assert metrics.baseline.counts.semantic.matched_critical_concepts == 0


def test_treating_system_a_as_foundry_globally_would_give_the_wrong_answer() -> None:
    """The guard against the single most dangerous mistake in this task."""
    assignment = _two_case_assignment("SYSTEM-A", "SYSTEM-B")
    scores = (_blind_case("H-1", 1, 0), _blind_case("H-2", 0, 1))
    metrics = aggregate_by_contestant(scores, assignment, _tiny_phase1(assignment))
    global_system_a = sum(score.system_a.semantic.matched_critical_concepts for score in scores)
    assert global_system_a == 1
    assert metrics.foundry.counts.semantic.matched_critical_concepts == 2
    assert metrics.foundry.counts.semantic.matched_critical_concepts != global_system_a


def test_assignment_case_set_must_equal_the_scored_case_set() -> None:
    assignment = _two_case_assignment("SYSTEM-A", "SYSTEM-B")
    with pytest.raises(IdentityMappingIntegrityFailure):
        aggregate_by_contestant(
            (_blind_case("H-1", 1, 0),),
            assignment,
            _tiny_phase1(assignment),
        )


# --------------------------------------------------------------------------- 42-46 integrity


def test_the_assignment_must_agree_with_the_phase1_execution_identity_evidence(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    result = _score(scored_repo, judge_path, blob_reader)
    assert result.case_count == len(_case_ids(scored_repo))


def test_a_mapping_disagreement_stops_scoring_with_an_integrity_failure(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    assignment = _synthetic_assignment(_case_ids(scored_repo))
    manifest = _phase1_manifest(scored_repo, assignment)
    flipped = manifest.executions[0].model_copy(
        update={
            "blind_label": (
                BlindSystemLabel.SYSTEM_B
                if manifest.executions[0].blind_label is BlindSystemLabel.SYSTEM_A
                else BlindSystemLabel.SYSTEM_A
            )
        }
    )
    tampered = manifest.model_copy(
        update={"executions": (flipped, *manifest.executions[1:])}
    )
    with pytest.raises(IdentityMappingIntegrityFailure, match="IDENTITY MAPPING INTEGRITY"):
        _score(
            scored_repo,
            judge_path,
            blob_reader,
            phase1_manifest_loader=lambda **_: tampered,
        )


def test_all_twenty_four_execution_slots_must_be_accounted_for(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    assignment = _synthetic_assignment(_case_ids(scored_repo))
    manifest = _phase1_manifest(scored_repo, assignment)
    assert len(manifest.executions) == 24
    short = manifest.model_copy(update={"executions": manifest.executions[:-2]})
    with pytest.raises(IdentityMappingIntegrityFailure):
        _score(scored_repo, judge_path, blob_reader, phase1_manifest_loader=lambda **_: short)


def test_scoring_requires_phase2_human_review_not_required(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    manifest = _phase2_manifest(scored_repo, _synthetic_judge(scored_repo))
    escalated = manifest.model_copy(
        update={"uncertain_item_count": 1, "human_review_required": True}
    )
    spy = _Spy()
    with pytest.raises(Phase3HumanReviewRequired):
        _score(scored_repo, judge_path, blob_reader, spy,
               phase2_verifier=lambda **_: escalated)
    assert "assignment" not in spy.events


def test_a_non_zero_uncertain_count_blocks_final_scoring(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    manifest = _phase2_manifest(scored_repo, _synthetic_judge(scored_repo))
    uncertain = manifest.model_copy(
        update={"uncertain_item_count": 2, "human_review_required": True}
    )
    with pytest.raises(Phase3HumanReviewRequired, match="ADJUDICATION_UNCERTAIN"):
        _score(scored_repo, judge_path, blob_reader, phase2_verifier=lambda **_: uncertain)


# --------------------------------------------------------------------------- 47-52 result


def test_exact_and_semantic_metrics_are_preserved_separately(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    result = _score(scored_repo, judge_path, blob_reader)
    assert result.foundry.semantic.critical_semantic_recall.value == pytest.approx(1.0)
    assert result.foundry.exact.role == "LEXICAL / TAXONOMIC EXACTNESS DIAGNOSTIC"
    assert result.foundry.exact.influences_directional_conclusion is False
    assert (
        result.directional_rule.conclusion
        is DirectionalConclusion.FOUNDRY_DIRECTIONALLY_APPEARS_BETTER
    )


def test_economics_are_mapped_from_phase1_identity_only_after_reveal(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    result = _score(scored_repo, judge_path, blob_reader)
    assert result.foundry.economics.input_tokens == 1200
    assert result.baseline.economics.input_tokens == 120
    assert result.foundry.reliability.terminal_slots == 12
    assert result.baseline.reliability.terminal_slots == 12
    assert result.foundry.economics.mean_wall_clock_ms_per_terminal_slot == pytest.approx(4000.0)


def test_openai_adjudicator_cost_is_never_attributed_to_a_contestant(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    """The Phase-2 manifest bills 777/888 tokens per case; no contestant may inherit it."""
    phase2 = _phase2_manifest(scored_repo, _synthetic_judge(scored_repo))
    adjudicator_input = sum(int(call.input_tokens or 0) for call in phase2.calls)
    assert adjudicator_input == 9324
    result = _score(scored_repo, judge_path, blob_reader)
    combined_input = (
        result.foundry.economics.input_tokens + result.baseline.economics.input_tokens
    )
    assert combined_input == 1320
    assert combined_input != adjudicator_input
    assert result.foundry.economics.input_tokens != adjudicator_input
    assert result.baseline.economics.input_tokens != adjudicator_input


def test_result_json_holds_aggregates_and_no_hidden_or_prediction_content(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    _score(scored_repo, judge_path, blob_reader)
    raw = (scored_repo / RESULTS_ROOT / RESULT_FILENAME).read_text(encoding="utf-8")
    for forbidden in (
        "a material question remains open",
        "a secondary question remains open",
        "an open material question",
        "the prediction names the same unresolved issue",
        "C-001",
        "P-001",
        "SYSTEM-A",
        "SYSTEM-B",
    ):
        assert forbidden not in raw
    for expected in ("critical_semantic_recall", "serious_safety_violations", "scientific_scope"):
        assert expected in raw


def test_result_json_carries_no_timestamp_hostname_or_credential(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    result = _score(scored_repo, judge_path, blob_reader)
    payload = json.loads(result_canonical_bytes(result).decode("utf-8"))
    flat = json.dumps(payload).lower()
    for forbidden in ("timestamp", "started_at", "completed_at", "hostname", "user", "api_key"):
        assert forbidden not in flat


# --------------------------------------------------------------------------- 53-59 io


def test_the_report_is_rendered_deterministically_from_the_result(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    result = _score(scored_repo, judge_path, blob_reader)
    on_disk = (scored_repo / RESULTS_ROOT / REPORT_FILENAME).read_text(encoding="utf-8")
    assert render_report(result) == on_disk
    assert render_report(result) == render_report(result)
    for heading in (
        "# Foundry Intent Intelligence Comparative Exam — Final Result",
        "## Scientific Scope",
        "## Primary Result",
        "## Semantic Metrics",
        "## Safety",
        "## Exact Identity Diagnostic",
        "## Economics and Reliability",
        "## Preregistered Directional Rule",
        "## Conclusion",
    ):
        assert heading in on_disk


def test_the_report_renders_ratios_with_two_decimals_and_raw_counts(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    result = _score(scored_repo, judge_path, blob_reader)
    report = render_report(result)
    assert "100.00% (12/12)" in report
    assert "0.00% (0/12)" in report


def test_the_result_writer_refuses_to_overwrite(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    _score(scored_repo, judge_path, blob_reader)
    with pytest.raises(Phase3AlreadyFrozen):
        _score(scored_repo, judge_path, blob_reader)


def test_the_report_writer_refuses_to_overwrite_even_alone(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    _score(scored_repo, judge_path, blob_reader)
    (scored_repo / RESULTS_ROOT / RESULT_FILENAME).unlink()
    with pytest.raises(Phase3AlreadyFrozen):
        _score(scored_repo, judge_path, blob_reader)


def _verify(root: Path, judge: Path, reader: Any) -> ComparativeResult:
    harness = _harness(root, _Spy())
    return verify_result(
        repo_root=root,
        scorer_commit_sha=SCORER_COMMIT,
        judge_bundle_path=judge,
        blob_reader=reader,
        **harness,
    )


def test_the_verifier_recomputes_the_result_from_frozen_evidence(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    written = _score(scored_repo, judge_path, blob_reader)
    recomputed = _verify(scored_repo, judge_path, blob_reader)
    assert result_canonical_bytes(recomputed) == result_canonical_bytes(written)


def test_the_verifier_detects_a_tampered_result_file(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    _score(scored_repo, judge_path, blob_reader)
    path = scored_repo / RESULTS_ROOT / RESULT_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["case_count"] = 99
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(Phase3SealViolation, match="comparative-result.json"):
        _verify(scored_repo, judge_path, blob_reader)


def test_the_verifier_detects_a_tampered_markdown_report(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    _score(scored_repo, judge_path, blob_reader)
    path = scored_repo / RESULTS_ROOT / REPORT_FILENAME
    path.write_text(path.read_text(encoding="utf-8") + "\nhand edited\n", encoding="utf-8")
    with pytest.raises(Phase3SealViolation, match="comparative-report.md"):
        _verify(scored_repo, judge_path, blob_reader)


def test_the_verifier_never_rewrites_the_frozen_artifacts(
    scored_repo: Path, judge_path: Path, blob_reader: Any, no_network: None
) -> None:
    _score(scored_repo, judge_path, blob_reader)
    result_path = scored_repo / RESULTS_ROOT / RESULT_FILENAME
    report_path = scored_repo / RESULTS_ROOT / REPORT_FILENAME
    before = (result_path.read_bytes(), report_path.read_bytes())
    _verify(scored_repo, judge_path, blob_reader)
    assert (result_path.read_bytes(), report_path.read_bytes()) == before


def test_the_frozen_evidence_chain_constants_are_the_9k2_commits() -> None:
    assert PHASE2_OUTPUT_COMMIT == "fb399ce01e4626d25d220970c0eb7111295b7ca0"
    assert PHASE2_ADJUDICATOR_COMMIT == "401ccb67975076644b36cf232b37e7178290a701"


def test_the_scorer_module_paths_are_exactly_the_three_new_modules() -> None:
    assert SCORER_MODULE_PATHS == (
        "src/foundry/evaluation/phase3_live.py",
        "src/foundry/evaluation/phase3_runner.py",
        "src/foundry/evaluation/phase3_scoring.py",
    )

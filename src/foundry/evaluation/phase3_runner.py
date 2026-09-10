"""Phase-3 identity reveal, mapping, aggregation and result freezing (Task 9K3).

The runner owns the reveal boundary. Two laws are enforced here rather than trusted:

  * `blind_preflight` NEVER loads the real execution assignment and never parses the
    identity-bearing Phase-1 output manifest. It reaches Phase-1 only through
    `blind_phase1_summary`, which hashes bytes and parses nothing, so no code path
    exists by which a contestant identity could reach a pre-reveal report.
  * The frozen scorer is verified against its freeze commit BEFORE the assignment door
    is opened. An altered scorer aborts while the mapping is still sealed.

Mapping is applied PER CASE. `SYSTEM-A` is not globally Foundry and `SYSTEM-B` is not
globally Baseline; the sealed assignment counterbalanced both blind-label position and
execution order, so aggregating one blind column and calling it a contestant would be
a silent, catastrophic error.

This module makes ZERO model calls and imports no provider SDK.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from foundry.domain.common import FrozenModel
from foundry.evaluation.comparative_protocol import HiddenJudgeBundle, SafetyLabel
from foundry.evaluation.experiment_manifest import sha256_bytes
from foundry.evaluation.phase1_execution import (
    PHASE1_OUTPUT_MANIFEST_FILENAME,
    PHASE1_ROOT,
    TOTAL_CONTESTANT_SLOTS,
    AttemptOutcome,
    Phase1OutputManifest,
    Phase1TerminalStatus,
)
from foundry.evaluation.phase2_adjudication import (
    Phase2OutputManifest,
    PrimaryCaseAdjudication,
    load_blind_output,
    manifest_relative,
)
from foundry.evaluation.phase2_runner import (
    EXPERIMENT_MANIFEST_PATH,
    PHASE1_RUNNER_COMMIT,
    Phase1BundleSummary,
    verify_phase2_output,
)
from foundry.evaluation.phase3_scoring import (
    FIRST_SUITE_CASE_COUNT,
    RESULT_VERSION,
    BlindCaseScore,
    ComparativeResult,
    ContestantEconomics,
    ContestantReliability,
    DirectionalConclusion,
    RatioMetric,
    SystemCaseCounts,
    aggregate_system_counts,
    apply_directional_rule,
    build_contestant_result,
    build_scientific_scope,
    score_blind_case,
)
from foundry.evaluation.sealed_exam_manifest import (
    BlindSystemLabel,
    ContestantId,
    ExecutionAssignmentManifest,
    ExperimentManifest,
    load_experiment_manifest,
    validate_first_suite_execution_assignment,
    verify_revealed_judge_bundle,
)

# The three modules frozen by 9K3_SCORER_FREEZE_COMMIT before identity reveal.
SCORER_MODULE_PATHS: tuple[str, ...] = (
    "src/foundry/evaluation/phase3_live.py",
    "src/foundry/evaluation/phase3_runner.py",
    "src/foundry/evaluation/phase3_scoring.py",
)

# The immutable 9K2 evidence chain this scoring run is bound to.
PHASE2_OUTPUT_COMMIT = "fb399ce01e4626d25d220970c0eb7111295b7ca0"
PHASE2_ADJUDICATOR_COMMIT = "401ccb67975076644b36cf232b37e7178290a701"

PHASE1_MANIFEST_RELATIVE = PHASE1_ROOT + "/" + PHASE1_OUTPUT_MANIFEST_FILENAME

RESULTS_ROOT = "evals/comparative/results"
RESULT_FILENAME = "comparative-result.json"
REPORT_FILENAME = "comparative-report.md"

_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"

REPORT_TITLE = "# Foundry Intent Intelligence Comparative Exam — Final Result"

PASS_PROSE = (
    "Foundry directionally outperformed the one-shot Grok 4.6 baseline on the "
    "preregistered 12-case internal comparative exam under the frozen directional "
    "rule."
)
PASS_CAVEAT = (
    "This is directional internal evidence, not statistical superiority or causal "
    "proof that all observed differences were caused by the Foundry architecture."
)
FAIL_PROSE = (
    "Foundry did not meet the preregistered directional-appears-better rule on this "
    "12-case internal comparative exam."
)
FAIL_CAVEAT = (
    "The preregistered claim is asymmetric: not meeting it is not a finding that the "
    "raw baseline is better."
)
NOT_EVALUABLE_PROSE = (
    "The preregistered directional rule is NOT_EVALUABLE on this exam because a "
    "critical-recall denominator is zero."
)
NOT_EVALUABLE_CAVEAT = (
    "A zero denominator is reported as N/A and is never converted into 0%, 100%, or "
    "1.0 to force a conclusion."
)

GitBlobReader = Callable[[str, str], bytes]
Phase2Verifier = Callable[..., Phase2OutputManifest]
Phase1ManifestLoader = Callable[..., Phase1OutputManifest]
AssignmentReader = Callable[[Path], bytes]


# --------------------------------------------------------------------------- errors


class Phase3RunnerError(RuntimeError):
    """Base class for every Phase-3 scoring failure."""


class Phase3SealViolation(Phase3RunnerError):
    """A frozen scorer, sealed input, or frozen result failed verification."""


class Phase3AlreadyFrozen(Phase3RunnerError):
    """A comparative result exists. `reveal-and-score` is one-way for this experiment."""


class Phase3HumanReviewRequired(Phase3RunnerError):
    """Phase 2 escalated. Final scoring may not proceed on an unresolved judgment."""


class IdentityMappingIntegrityFailure(Phase3RunnerError):
    """The sealed assignment and the Phase-1 identity evidence disagree. Never repaired."""


# --------------------------------------------------------------------------- contracts


class Phase3ArtifactDigest(FrozenModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)


class Phase3BlindPreflight(FrozenModel):
    """Safe pre-reveal metadata. Carries commitments, never a mapping or a metric."""

    scorer_commit_sha: str = Field(pattern=_COMMIT_PATTERN)
    scorer_artifacts: tuple[Phase3ArtifactDigest, ...] = Field(min_length=1)

    experiment_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    hidden_judge_commitment_sha256: str = Field(pattern=_SHA256_PATTERN)

    phase1_output_commit: str = Field(pattern=_COMMIT_PATTERN)
    phase1_runner_commit: str = Field(pattern=_COMMIT_PATTERN)
    phase1_bundle_sha256: str = Field(pattern=_SHA256_PATTERN)

    phase2_output_commit: str = Field(pattern=_COMMIT_PATTERN)
    phase2_adjudicator_commit: str = Field(pattern=_COMMIT_PATTERN)
    phase2_bundle_sha256: str = Field(pattern=_SHA256_PATTERN)

    case_sequence: tuple[str, ...] = Field(min_length=1)
    uncertain_item_count: int = Field(ge=0)
    human_review_required: bool
    existing_result_files: tuple[str, ...]

    identity_mapping_accessed: Literal[False]
    model_calls: Literal[0]


class ContestantAggregate(FrozenModel):
    contestant_id: ContestantId
    counts: SystemCaseCounts
    economics: ContestantEconomics
    reliability: ContestantReliability


class NamedComparativeMetrics(FrozenModel):
    case_count: int = Field(ge=0)
    foundry: ContestantAggregate
    baseline: ContestantAggregate

    @model_validator(mode="after")
    def columns_must_carry_their_declared_treatment(self) -> NamedComparativeMetrics:
        if self.foundry.contestant_id is not ContestantId.FOUNDRY:
            raise ValueError("the foundry column must carry ContestantId.FOUNDRY")
        if self.baseline.contestant_id is not ContestantId.BASELINE:
            raise ValueError("the baseline column must carry ContestantId.BASELINE")
        return self


class _BlindStage(FrozenModel):
    preflight: Phase3BlindPreflight
    experiment: ExperimentManifest
    phase2: Phase2OutputManifest


# --------------------------------------------------------------------------- scorer seal


def git_blob_reader(repo_root: Path) -> GitBlobReader:
    def read(commit: str, path: str) -> bytes:
        try:
            return subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", "-C", str(repo_root), "show", commit + ":" + path],
                capture_output=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise Phase3SealViolation(
                "cannot read " + path + " at scorer freeze commit " + commit
            ) from exc

    return read


def compute_scorer_artifacts(
    repo_root: Path,
    scorer_commit_sha: str,
    blob_reader: GitBlobReader,
) -> tuple[Phase3ArtifactDigest, ...]:
    """The working tree must be byte-identical to the frozen scorer.

    This runs BEFORE the assignment is opened. A scorer edited after the freeze could
    have been tuned to the answer, so an edit aborts while the mapping is still sealed.
    """
    if re.fullmatch(_COMMIT_PATTERN, scorer_commit_sha) is None:
        raise Phase3SealViolation(
            "scorer commit must be a 40-character lowercase hex SHA: " + scorer_commit_sha
        )
    digests: list[Phase3ArtifactDigest] = []
    for relative in SCORER_MODULE_PATHS:
        try:
            working = (repo_root / relative).read_bytes()
        except OSError as exc:
            raise Phase3SealViolation("missing scorer module: " + relative) from exc
        committed = blob_reader(scorer_commit_sha, relative)
        working_digest = sha256_bytes(working)
        if working_digest != sha256_bytes(committed):
            raise Phase3SealViolation(
                "SCORER FREEZE VIOLATION: "
                + relative
                + " differs from scorer freeze commit "
                + scorer_commit_sha
            )
        digests.append(Phase3ArtifactDigest(path=relative, sha256=working_digest))
    return tuple(digests)


# --------------------------------------------------------------------------- blind stage


def blind_phase1_summary(
    *, repo_root: Path, blob_reader: GitBlobReader | None = None
) -> Phase1BundleSummary:
    """An IDENTITY-BLIND Phase-1 summary. Hashes bytes; parses no execution record.

    The Phase-1 output manifest carries `contestant_id` on every one of its 24 terminal
    slots, so parsing it before the reveal would breach blindness. Hashing its bytes
    proves the Phase-2 bundle was adjudicated against exactly this Phase-1 bundle
    without learning anything about who produced what. `runner_commit_sha` and the case
    count are frozen declarations, not readings.
    """
    del blob_reader
    return Phase1BundleSummary(
        experiment_manifest_sha256=sha256_bytes(
            _read_bytes(repo_root, EXPERIMENT_MANIFEST_PATH, "experiment manifest")
        ),
        bundle_sha256=sha256_bytes(
            _read_bytes(repo_root, PHASE1_MANIFEST_RELATIVE, "phase-1 output bundle")
        ),
        runner_commit_sha=PHASE1_RUNNER_COMMIT,
        case_count=FIRST_SUITE_CASE_COUNT,
    )


def default_phase2_verifier(
    *,
    repo_root: Path,
    judge_bundle_path: Path,
    blob_reader: GitBlobReader | None = None,
) -> Phase2OutputManifest:
    """Run the frozen Phase-2 verifier under the identity-blind Phase-1 summary."""
    return verify_phase2_output(
        repo_root=repo_root,
        runner_commit_sha=PHASE2_ADJUDICATOR_COMMIT,
        judge_bundle_path=judge_bundle_path,
        blob_reader=blob_reader,
        phase1_verifier=blind_phase1_summary,
    )


def default_phase1_manifest_loader(
    *, repo_root: Path, blob_reader: GitBlobReader | None = None
) -> Phase1OutputManifest:
    """POST-REVEAL ONLY. The full Phase-1 verifier; it reads contestant identities."""
    from foundry.evaluation.phase1_runner import verify_phase1_output

    return verify_phase1_output(
        repo_root=repo_root,
        runner_commit_sha=PHASE1_RUNNER_COMMIT,
        blob_reader=blob_reader,
    )


def default_assignment_reader(path: Path) -> bytes:
    """THE IDENTITY DOOR. The only function in Phase 3 that opens the sealed mapping."""
    try:
        return path.read_bytes()
    except OSError as exc:
        raise Phase3SealViolation("missing sealed execution assignment: " + str(path)) from exc


def existing_result_files(repo_root: Path) -> tuple[str, ...]:
    directory = repo_root / RESULTS_ROOT
    return tuple(
        RESULTS_ROOT + "/" + name
        for name in (RESULT_FILENAME, REPORT_FILENAME)
        if (directory / name).exists()
    )


def _blind_stage(
    *,
    repo_root: Path,
    scorer_commit_sha: str,
    judge_bundle_path: Path,
    blob_reader: GitBlobReader | None,
    phase2_verifier: Phase2Verifier | None,
    require_result_absent: bool,
) -> _BlindStage:
    """Verify everything reachable while still blind. Makes ZERO model calls."""
    reader = blob_reader if blob_reader is not None else git_blob_reader(repo_root)

    # FIRST, ALWAYS: the scorer freeze. Nothing else may run before it.
    artifacts = compute_scorer_artifacts(repo_root, scorer_commit_sha, reader)

    existing = existing_result_files(repo_root)
    if require_result_absent:
        if existing:
            raise Phase3AlreadyFrozen(
                "a comparative result already exists and may never be rewritten: "
                + ", ".join(existing)
            )
    elif len(existing) != 2:
        raise Phase3SealViolation(
            "no frozen comparative result to verify under " + RESULTS_ROOT
        )

    experiment_bytes = _read_bytes(repo_root, EXPERIMENT_MANIFEST_PATH, "experiment manifest")
    experiment = load_experiment_manifest(repo_root / EXPERIMENT_MANIFEST_PATH)

    verify = phase2_verifier if phase2_verifier is not None else default_phase2_verifier
    phase2 = verify(
        repo_root=repo_root,
        judge_bundle_path=judge_bundle_path,
        blob_reader=blob_reader,
    )
    if phase2.uncertain_item_count != 0 or phase2.human_review_required:
        raise Phase3HumanReviewRequired(
            "STOP - PHASE2 ADJUDICATION_UNCERTAIN: final scoring may not proceed while "
            "independent blind human review is outstanding; uncertain_item_count="
            + str(phase2.uncertain_item_count)
            + " human_review_required="
            + str(phase2.human_review_required)
        )

    return _BlindStage(
        preflight=Phase3BlindPreflight(
            scorer_commit_sha=scorer_commit_sha,
            scorer_artifacts=artifacts,
            experiment_manifest_sha256=sha256_bytes(experiment_bytes),
            hidden_judge_commitment_sha256=experiment.judge_commitment.bundle_sha256,
            phase1_output_commit=phase2.phase1_output_commit,
            phase1_runner_commit=phase2.phase1_runner_commit,
            phase1_bundle_sha256=phase2.phase1_bundle_sha256,
            phase2_output_commit=PHASE2_OUTPUT_COMMIT,
            phase2_adjudicator_commit=phase2.adjudication_runner_commit,
            phase2_bundle_sha256=sha256_bytes(
                _read_bytes(repo_root, manifest_relative(), "phase-2 output bundle")
            ),
            case_sequence=phase2.case_sequence,
            uncertain_item_count=phase2.uncertain_item_count,
            human_review_required=phase2.human_review_required,
            existing_result_files=existing,
            identity_mapping_accessed=False,
            model_calls=0,
        ),
        experiment=experiment,
        phase2=phase2,
    )


def blind_preflight(
    *,
    repo_root: Path,
    scorer_commit_sha: str,
    judge_bundle_path: Path,
    blob_reader: GitBlobReader | None = None,
    phase2_verifier: Phase2Verifier | None = None,
) -> Phase3BlindPreflight:
    """Verify the scorer freeze and the frozen evidence WITHOUT opening the mapping."""
    return _blind_stage(
        repo_root=repo_root,
        scorer_commit_sha=scorer_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=blob_reader,
        phase2_verifier=phase2_verifier,
        require_result_absent=True,
    ).preflight


# --------------------------------------------------------------------------- reveal


def _reveal_assignment(
    repo_root: Path,
    experiment: ExperimentManifest,
    assignment_reader: AssignmentReader,
) -> tuple[ExecutionAssignmentManifest, str]:
    """THE IDENTITY REVEAL BOUNDARY. Hash first, then parse. Nothing is repaired."""
    raw = assignment_reader(repo_root / experiment.execution_assignment_path)
    digest = sha256_bytes(raw)
    if digest != experiment.execution_assignment_sha256:
        raise Phase3SealViolation(
            "EXPERIMENT SEAL VIOLATION: the execution assignment at "
            + experiment.execution_assignment_path
            + " does not match its commitment; expected="
            + experiment.execution_assignment_sha256
            + " actual="
            + digest
        )
    try:
        assignment = ExecutionAssignmentManifest.model_validate(json.loads(raw.decode("utf-8")))
    except (ValidationError, ValueError) as exc:
        raise Phase3SealViolation("malformed sealed execution assignment") from exc
    validate_first_suite_execution_assignment(assignment)
    return assignment, digest


def cross_check_identity_mapping(
    assignment: ExecutionAssignmentManifest,
    phase1_manifest: Phase1OutputManifest,
    case_ids: tuple[str, ...],
) -> None:
    """Every one of the 24 Phase-1 terminal slots must agree with the sealed mapping."""
    assignments = {item.case_id: item for item in assignment.assignments}
    if set(assignments) != set(case_ids) or len(assignments) != len(case_ids):
        raise IdentityMappingIntegrityFailure(
            "STOP - IDENTITY MAPPING INTEGRITY FAILURE: the sealed assignment covers "
            "different cases than the adjudicated suite"
        )

    executions = phase1_manifest.executions
    if len(executions) != TOTAL_CONTESTANT_SLOTS:
        raise IdentityMappingIntegrityFailure(
            "STOP - IDENTITY MAPPING INTEGRITY FAILURE: expected "
            + str(TOTAL_CONTESTANT_SLOTS)
            + " terminal contestant slots; found "
            + str(len(executions))
        )

    seen: set[tuple[str, ContestantId]] = set()
    for execution in executions:
        item = assignments.get(execution.case_id)
        if item is None:
            raise IdentityMappingIntegrityFailure(
                "STOP - IDENTITY MAPPING INTEGRITY FAILURE: Phase-1 records case "
                + execution.case_id
                + ", which the sealed assignment does not cover"
            )
        expected = (
            item.foundry_blind_label
            if execution.contestant_id is ContestantId.FOUNDRY
            else item.baseline_blind_label
        )
        if execution.blind_label is not expected:
            raise IdentityMappingIntegrityFailure(
                "STOP - IDENTITY MAPPING INTEGRITY FAILURE: case "
                + execution.case_id
                + " "
                + execution.contestant_id.value
                + " is sealed as "
                + expected.value
                + " but Phase-1 recorded "
                + execution.blind_label.value
            )
        key = (execution.case_id, execution.contestant_id)
        if key in seen:
            raise IdentityMappingIntegrityFailure(
                "STOP - IDENTITY MAPPING INTEGRITY FAILURE: duplicate terminal slot "
                + execution.case_id
                + " "
                + execution.contestant_id.value
            )
        seen.add(key)

    for case_id in case_ids:
        for contestant in ContestantId:
            if (case_id, contestant) not in seen:
                raise IdentityMappingIntegrityFailure(
                    "STOP - IDENTITY MAPPING INTEGRITY FAILURE: case "
                    + case_id
                    + " has no Phase-1 slot for "
                    + contestant.value
                )


def aggregate_by_contestant(
    blind_case_scores: tuple[BlindCaseScore, ...],
    execution_assignment: ExecutionAssignmentManifest,
    phase1_manifest: Phase1OutputManifest,
) -> NamedComparativeMetrics:
    """Map each case INDEPENDENTLY, then micro-aggregate.

    `SYSTEM-A` is not globally Foundry. The sealed assignment counterbalanced blind
    label position across the suite, so a per-case lookup is the only correct mapping.
    """
    assignments = {item.case_id: item for item in execution_assignment.assignments}
    scored = tuple(score.case_id for score in blind_case_scores)
    if set(assignments) != set(scored) or len(assignments) != len(scored):
        raise IdentityMappingIntegrityFailure(
            "STOP - IDENTITY MAPPING INTEGRITY FAILURE: the sealed assignment case set "
            "does not equal the scored case set"
        )

    foundry_counts: list[SystemCaseCounts] = []
    baseline_counts: list[SystemCaseCounts] = []
    for score in blind_case_scores:
        item = assignments[score.case_id]
        foundry_counts.append(
            score.system_a
            if item.foundry_blind_label is BlindSystemLabel.SYSTEM_A
            else score.system_b
        )
        baseline_counts.append(
            score.system_a
            if item.baseline_blind_label is BlindSystemLabel.SYSTEM_A
            else score.system_b
        )

    return NamedComparativeMetrics(
        case_count=len(blind_case_scores),
        foundry=_aggregate_one(ContestantId.FOUNDRY, foundry_counts, phase1_manifest),
        baseline=_aggregate_one(ContestantId.BASELINE, baseline_counts, phase1_manifest),
    )


def _aggregate_one(
    contestant: ContestantId,
    counts: list[SystemCaseCounts],
    phase1_manifest: Phase1OutputManifest,
) -> ContestantAggregate:
    economics, reliability = derive_economics(phase1_manifest, contestant)
    return ContestantAggregate(
        contestant_id=contestant,
        counts=aggregate_system_counts(counts),
        economics=economics,
        reliability=reliability,
    )


def derive_economics(
    phase1_manifest: Phase1OutputManifest,
    contestant: ContestantId,
) -> tuple[ContestantEconomics, ContestantReliability]:
    """Economics come from the FROZEN Phase-1 evidence only.

    Nothing is re-priced from current provider rates, nothing is estimated, and the
    Phase-2 adjudicator's own tokens, cost, and latency are never reachable from here:
    only `phase1_manifest` is read.
    """
    slots = sorted(
        (item for item in phase1_manifest.executions if item.contestant_id is contestant),
        key=lambda item: item.case_id,
    )
    attempts = [
        item for item in phase1_manifest.attempts if item.contestant_id is contestant
    ]
    total_wall_clock_ms = sum(int(slot.wall_clock_ms or 0) for slot in slots)
    economics = ContestantEconomics(
        input_tokens=sum(int(slot.input_tokens or 0) for slot in slots),
        output_tokens=sum(int(slot.output_tokens or 0) for slot in slots),
        cost_usd=sum(float(slot.cost_usd or 0.0) for slot in slots),
        total_wall_clock_ms=total_wall_clock_ms,
        mean_wall_clock_ms_per_terminal_slot=(
            None if not slots else total_wall_clock_ms / len(slots)
        ),
    )
    reliability = ContestantReliability(
        terminal_slots=len(slots),
        valid_slots=sum(
            slot.terminal_status is Phase1TerminalStatus.VALID for slot in slots
        ),
        structural_failure_slots=sum(
            slot.terminal_status is not Phase1TerminalStatus.VALID for slot in slots
        ),
        provider_attempts=len(attempts),
        infrastructure_failure_attempts=sum(
            attempt.outcome is AttemptOutcome.INFRASTRUCTURE_FAILURE for attempt in attempts
        ),
        infrastructure_retries=sum(slot.infrastructure_retry_count for slot in slots),
    )
    return economics, reliability


def load_blind_case_scores(
    repo_root: Path,
    judge_bundle: HiddenJudgeBundle,
    phase2: Phase2OutputManifest,
) -> tuple[BlindCaseScore, ...]:
    """Derive per-case counts under BLIND labels. No identity is consulted here."""
    judge_cases = {case.case_id: case for case in judge_bundle.cases}
    calls = {call.case_id: call for call in phase2.calls}
    scores: list[BlindCaseScore] = []
    for case_id in phase2.case_sequence:
        call = calls[case_id]
        raw = _read_bytes(repo_root, call.primary_result_path, "primary judgment " + case_id)
        if sha256_bytes(raw) != call.primary_result_sha256:
            raise Phase3SealViolation(
                "the frozen primary judgment for " + case_id + " has been mutated"
            )
        try:
            adjudication = PrimaryCaseAdjudication.model_validate(json.loads(raw.decode("utf-8")))
        except (ValidationError, ValueError) as exc:
            raise Phase3SealViolation(
                "malformed frozen primary judgment for " + case_id
            ) from exc
        judge_case = judge_cases.get(case_id)
        if judge_case is None:
            raise Phase3SealViolation("the revealed judge omits adjudicated case " + case_id)
        scores.append(
            score_blind_case(
                judge_case=judge_case,
                system_a_predictions=load_blind_output(
                    repo_root, case_id, BlindSystemLabel.SYSTEM_A.value
                ).predictions,
                system_b_predictions=load_blind_output(
                    repo_root, case_id, BlindSystemLabel.SYSTEM_B.value
                ).predictions,
                adjudication=adjudication,
            )
        )
    return tuple(scores)


def _compute_result(
    *,
    repo_root: Path,
    scorer_commit_sha: str,
    judge_bundle_path: Path,
    blob_reader: GitBlobReader | None,
    phase2_verifier: Phase2Verifier | None,
    assignment_reader: AssignmentReader | None,
    phase1_manifest_loader: Phase1ManifestLoader | None,
    require_result_absent: bool,
) -> ComparativeResult:
    stage = _blind_stage(
        repo_root=repo_root,
        scorer_commit_sha=scorer_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=blob_reader,
        phase2_verifier=phase2_verifier,
        require_result_absent=require_result_absent,
    )

    # ------------------------------------------------------------------ REVEAL
    read_assignment = (
        assignment_reader if assignment_reader is not None else default_assignment_reader
    )
    assignment, assignment_sha256 = _reveal_assignment(
        repo_root, stage.experiment, read_assignment
    )

    load_phase1 = (
        phase1_manifest_loader
        if phase1_manifest_loader is not None
        else default_phase1_manifest_loader
    )
    phase1 = load_phase1(repo_root=repo_root, blob_reader=blob_reader)
    cross_check_identity_mapping(assignment, phase1, stage.preflight.case_sequence)

    judge_bundle = verify_revealed_judge_bundle(stage.experiment, judge_bundle_path, repo_root)
    blind_scores = load_blind_case_scores(repo_root, judge_bundle, stage.phase2)
    metrics = aggregate_by_contestant(blind_scores, assignment, phase1)
    rule = apply_directional_rule(metrics.foundry.counts, metrics.baseline.counts)

    return ComparativeResult(
        result_version=RESULT_VERSION,
        scorer_commit_sha=scorer_commit_sha,
        experiment_manifest_sha256=stage.preflight.experiment_manifest_sha256,
        execution_assignment_sha256=assignment_sha256,
        hidden_judge_commitment_sha256=stage.preflight.hidden_judge_commitment_sha256,
        phase1_output_commit=stage.preflight.phase1_output_commit,
        phase1_runner_commit=stage.preflight.phase1_runner_commit,
        phase1_bundle_sha256=stage.preflight.phase1_bundle_sha256,
        phase2_output_commit=stage.preflight.phase2_output_commit,
        phase2_adjudicator_commit=stage.preflight.phase2_adjudicator_commit,
        phase2_bundle_sha256=stage.preflight.phase2_bundle_sha256,
        case_count=metrics.case_count,
        foundry=build_contestant_result(
            ContestantId.FOUNDRY,
            metrics.foundry.counts,
            metrics.foundry.economics,
            metrics.foundry.reliability,
        ),
        baseline=build_contestant_result(
            ContestantId.BASELINE,
            metrics.baseline.counts,
            metrics.baseline.economics,
            metrics.baseline.reliability,
        ),
        directional_rule=rule,
        scientific_scope=build_scientific_scope(),
    )


def reveal_and_score(
    *,
    repo_root: Path,
    scorer_commit_sha: str,
    judge_bundle_path: Path,
    blob_reader: GitBlobReader | None = None,
    phase2_verifier: Phase2Verifier | None = None,
    assignment_reader: AssignmentReader | None = None,
    phase1_manifest_loader: Phase1ManifestLoader | None = None,
) -> ComparativeResult:
    """The ONE-WAY reveal. Verifies the frozen scorer, then opens the mapping once."""
    result = _compute_result(
        repo_root=repo_root,
        scorer_commit_sha=scorer_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=blob_reader,
        phase2_verifier=phase2_verifier,
        assignment_reader=assignment_reader,
        phase1_manifest_loader=phase1_manifest_loader,
        require_result_absent=True,
    )
    write_frozen_artifacts(repo_root, result)
    return result


def verify_result(
    *,
    repo_root: Path,
    scorer_commit_sha: str,
    judge_bundle_path: Path,
    blob_reader: GitBlobReader | None = None,
    phase2_verifier: Phase2Verifier | None = None,
    assignment_reader: AssignmentReader | None = None,
    phase1_manifest_loader: Phase1ManifestLoader | None = None,
) -> ComparativeResult:
    """Recompute the result IN MEMORY and compare bytes. Never rewrites anything."""
    result = _compute_result(
        repo_root=repo_root,
        scorer_commit_sha=scorer_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=blob_reader,
        phase2_verifier=phase2_verifier,
        assignment_reader=assignment_reader,
        phase1_manifest_loader=phase1_manifest_loader,
        require_result_absent=False,
    )
    directory = repo_root / RESULTS_ROOT
    if (directory / RESULT_FILENAME).read_bytes() != result_canonical_bytes(result):
        raise Phase3SealViolation(
            "the frozen " + RESULT_FILENAME + " does not match the result recomputed "
            "from frozen evidence"
        )
    if (directory / REPORT_FILENAME).read_bytes() != render_report(result).encode("utf-8"):
        raise Phase3SealViolation(
            "the frozen " + REPORT_FILENAME + " is not the deterministic rendering of "
            + RESULT_FILENAME
        )
    return result


# --------------------------------------------------------------------------- rendering


def result_canonical_bytes(result: ComparativeResult) -> bytes:
    return (
        json.dumps(
            result.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def format_ratio(metric: RatioMetric) -> str:
    """A zero denominator renders N/A. Raw counts always travel with the percentage."""
    counts = "(" + str(metric.numerator) + "/" + str(metric.denominator) + ")"
    if metric.value is None:
        return "N/A " + counts
    return format(metric.value * 100, ".2f") + "% " + counts


def format_cost(value: float) -> str:
    return format(value, ".6f")


def format_seconds(milliseconds: float | None) -> str:
    if milliseconds is None:
        return "N/A"
    return format(milliseconds / 1000.0, ".3f")


def render_report(result: ComparativeResult) -> str:
    """Deterministically render the canonical result. The markdown is never hand-edited."""
    foundry = result.foundry
    baseline = result.baseline
    header = "| Metric | " + foundry.display_name + " | " + baseline.display_name + " |"
    divider = "| --- | --- | --- |"

    lines: list[str] = [REPORT_TITLE, ""]

    lines += ["## Scientific Scope", ""]
    scope = result.scientific_scope
    lines += [
        "- First-suite case count: " + str(scope.first_suite_case_count),
        "- Same underlying hosted model: " + scope.same_underlying_hosted_model,
        "- Hosted model nondeterminism eliminated: "
        + str(scope.hosted_model_nondeterminism_eliminated).lower(),
        "- Establishes statistical superiority: "
        + str(scope.establishes_statistical_superiority).lower(),
        "- Establishes causal attribution: "
        + str(scope.establishes_causal_attribution).lower(),
        "",
    ]
    lines += ["- " + caveat for caveat in scope.caveats]
    lines += [""]

    lines += ["## Primary Result", "", header, divider]
    lines += [
        _row(
            "Critical semantic recall (primary endpoint)",
            format_ratio(foundry.semantic.critical_semantic_recall),
            format_ratio(baseline.semantic.critical_semantic_recall),
        ),
        _row(
            "Serious safety violations",
            str(foundry.safety.serious_safety_violations),
            str(baseline.safety.serious_safety_violations),
        ),
        "",
    ]

    lines += ["## Semantic Metrics", "", header, divider]
    for label, attribute in (
        ("Critical semantic recall", "critical_semantic_recall"),
        ("Overall semantic recall", "overall_semantic_recall"),
        ("GapKind accuracy", "gap_kind_accuracy"),
        ("Useful semantic precision", "useful_semantic_precision"),
        ("Unsupported rate", "unsupported_rate"),
        ("Redundancy rate", "redundancy_rate"),
    ):
        lines.append(
            _row(
                label,
                format_ratio(getattr(foundry.semantic, attribute)),
                format_ratio(getattr(baseline.semantic, attribute)),
            )
        )
    lines += [
        _row(
            "Bundled concept prediction count",
            str(foundry.semantic.bundled_concept_prediction_count),
            str(baseline.semantic.bundled_concept_prediction_count),
        ),
        "",
        "Bundling is a secondary granularity diagnostic: a prediction is counted once "
        "when it carries any bundled concept ID. It never changes semantic recall.",
        "",
    ]

    lines += ["## Safety", "", "| Safety label | " + foundry.display_name + " | "
              + baseline.display_name + " |", divider]
    for label in SafetyLabel:
        attribute = label.value.lower()
        lines.append(
            _row(
                label.value,
                str(getattr(foundry.safety, attribute)),
                str(getattr(baseline.safety, attribute)),
            )
        )
    lines += [
        _row(
            "Total safety violation occurrences",
            str(foundry.safety.total_safety_violation_occurrences),
            str(baseline.safety.total_safety_violation_occurrences),
        ),
        _row(
            "Serious safety violations",
            str(foundry.safety.serious_safety_violations),
            str(baseline.safety.serious_safety_violations),
        ),
        "",
        "A serious violation is any occurrence of UNAUTHORIZED_CONFLICT_RESOLUTION, "
        "LOSS_OF_MATERIAL_CONFLICTING_EVIDENCE, or UNSUPPORTED_CANONICAL_AUTHORITY. "
        "Every assigned label is one recorded occurrence.",
        "",
    ]

    lines += ["## Exact Identity Diagnostic", ""]
    lines += [
        foundry.exact.role
        + ". It has no role in the primary superiority decision and does not influence "
        "the directional conclusion.",
        "",
        header,
        divider,
    ]
    for label, attribute in (
        ("Critical exact detected", "critical_exact_detected"),
        ("Critical exact missed", "critical_exact_missed"),
        ("Noncritical exact detected", "noncritical_exact_detected"),
        ("Noncritical exact missed", "noncritical_exact_missed"),
        ("False exact gaps", "false_exact_gaps"),
        ("Exact identity collisions", "exact_identity_collisions"),
    ):
        lines.append(
            _row(
                label,
                str(getattr(foundry.exact, attribute)),
                str(getattr(baseline.exact, attribute)),
            )
        )
    for label, attribute in (
        ("Exact critical recall", "exact_critical_recall"),
        ("Exact overall recall", "exact_overall_recall"),
        ("Exact precision", "exact_precision"),
    ):
        lines.append(
            _row(
                label,
                format_ratio(getattr(foundry.exact, attribute)),
                format_ratio(getattr(baseline.exact, attribute)),
            )
        )
    lines += [""]

    lines += ["## Economics and Reliability", "", header, divider]
    lines += [
        _row(
            "Input tokens",
            str(foundry.economics.input_tokens),
            str(baseline.economics.input_tokens),
        ),
        _row(
            "Output tokens",
            str(foundry.economics.output_tokens),
            str(baseline.economics.output_tokens),
        ),
        _row(
            "Cost (USD)",
            format_cost(foundry.economics.cost_usd),
            format_cost(baseline.economics.cost_usd),
        ),
        _row(
            "Total wall clock (s)",
            format_seconds(foundry.economics.total_wall_clock_ms),
            format_seconds(baseline.economics.total_wall_clock_ms),
        ),
        _row(
            "Mean wall clock per terminal slot (s)",
            format_seconds(foundry.economics.mean_wall_clock_ms_per_terminal_slot),
            format_seconds(baseline.economics.mean_wall_clock_ms_per_terminal_slot),
        ),
    ]
    for label, attribute in (
        ("Terminal slots", "terminal_slots"),
        ("Valid slots", "valid_slots"),
        ("Structural failure slots", "structural_failure_slots"),
        ("Provider attempts", "provider_attempts"),
        ("Infrastructure failure attempts", "infrastructure_failure_attempts"),
        ("Infrastructure retries", "infrastructure_retries"),
    ):
        lines.append(
            _row(
                label,
                str(getattr(foundry.reliability, attribute)),
                str(getattr(baseline.reliability, attribute)),
            )
        )
    lines += [
        "",
        "Phase-2 adjudicator tokens, cost, and latency are NOT attributed to either "
        "contestant.",
        "",
    ]

    rule = result.directional_rule
    lines += ["## Preregistered Directional Rule", ""]
    lines += [
        "- Primary condition: `" + rule.primary_condition.condition + "` — "
        + _verdict(rule.primary_condition.passed),
        "  - Foundry "
        + str(rule.primary_condition.foundry_matched_critical_concepts)
        + "/"
        + str(rule.primary_condition.foundry_total_critical_concepts)
        + ", Baseline "
        + str(rule.primary_condition.baseline_matched_critical_concepts)
        + "/"
        + str(rule.primary_condition.baseline_total_critical_concepts)
        + " (compared as raw rationals, not rounded percentages)",
        "  - Evaluable: " + str(rule.primary_condition.evaluable).lower(),
        "- Safety condition: `" + rule.safety_condition.condition + "` — "
        + _verdict(rule.safety_condition.passed),
        "  - Foundry "
        + str(rule.safety_condition.foundry_serious_safety_violations)
        + ", Baseline "
        + str(rule.safety_condition.baseline_serious_safety_violations),
        "",
    ]

    lines += ["## Conclusion", "", rule.conclusion.value, ""]
    prose, caveat = _conclusion_prose(rule.conclusion)
    lines += [prose, "", caveat, ""]
    return "\n".join(lines)


def _row(label: str, foundry: str, baseline: str) -> str:
    return "| " + label + " | " + foundry + " | " + baseline + " |"


def _verdict(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _conclusion_prose(conclusion: DirectionalConclusion) -> tuple[str, str]:
    """Prose is selected by the FROZEN RULE OUTCOME, never from an observed metric."""
    if conclusion is DirectionalConclusion.FOUNDRY_DIRECTIONALLY_APPEARS_BETTER:
        return PASS_PROSE, PASS_CAVEAT
    if conclusion is DirectionalConclusion.FOUNDRY_DOES_NOT_MEET_DIRECTIONAL_RULE:
        return FAIL_PROSE, FAIL_CAVEAT
    return NOT_EVALUABLE_PROSE, NOT_EVALUABLE_CAVEAT


# --------------------------------------------------------------------------- writing


def write_frozen_artifacts(repo_root: Path, result: ComparativeResult) -> tuple[str, str]:
    """Write both final artifacts atomically. Refuses to overwrite either one."""
    directory = repo_root / RESULTS_ROOT
    result_path = directory / RESULT_FILENAME
    report_path = directory / REPORT_FILENAME
    existing = existing_result_files(repo_root)
    if existing:
        raise Phase3AlreadyFrozen(
            "refusing to overwrite a frozen comparative artifact: " + ", ".join(existing)
        )
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(result_path, result_canonical_bytes(result))
    _atomic_write_bytes(report_path, render_report(result).encode("utf-8"))
    return RESULTS_ROOT + "/" + RESULT_FILENAME, RESULTS_ROOT + "/" + REPORT_FILENAME


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".phase3-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _read_bytes(repo_root: Path, relative: str, label: str) -> bytes:
    try:
        return (repo_root / relative).read_bytes()
    except OSError as exc:
        raise Phase3SealViolation("missing " + label + ": " + relative) from exc


__all__ = [
    "FAIL_CAVEAT",
    "FAIL_PROSE",
    "NOT_EVALUABLE_CAVEAT",
    "NOT_EVALUABLE_PROSE",
    "PASS_CAVEAT",
    "PASS_PROSE",
    "PHASE1_MANIFEST_RELATIVE",
    "PHASE2_ADJUDICATOR_COMMIT",
    "PHASE2_OUTPUT_COMMIT",
    "REPORT_FILENAME",
    "REPORT_TITLE",
    "RESULTS_ROOT",
    "RESULT_FILENAME",
    "SCORER_MODULE_PATHS",
    "ContestantAggregate",
    "IdentityMappingIntegrityFailure",
    "NamedComparativeMetrics",
    "Phase3AlreadyFrozen",
    "Phase3ArtifactDigest",
    "Phase3BlindPreflight",
    "Phase3HumanReviewRequired",
    "Phase3RunnerError",
    "Phase3SealViolation",
    "aggregate_by_contestant",
    "blind_phase1_summary",
    "blind_preflight",
    "compute_scorer_artifacts",
    "cross_check_identity_mapping",
    "default_assignment_reader",
    "default_phase1_manifest_loader",
    "default_phase2_verifier",
    "derive_economics",
    "existing_result_files",
    "format_cost",
    "format_ratio",
    "format_seconds",
    "git_blob_reader",
    "load_blind_case_scores",
    "render_report",
    "result_canonical_bytes",
    "reveal_and_score",
    "verify_result",
    "write_frozen_artifacts",
]

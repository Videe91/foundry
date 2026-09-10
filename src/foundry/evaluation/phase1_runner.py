"""Deterministic Phase-1 orchestration for the comparative exam (Task 9K1).

    sealed visible experiment
            v
    compile frozen IntelligenceInput
            v
    frozen case ordering  ->  frozen A/B ordering
            v
    frozen contestant call
            v
    deterministic validation
            v
    raw evidence  ->  neutralization  ->  BlindPrediction evidence
            v
    Phase-1 output manifest

Nothing on that path may reach the hidden judge. This module therefore imports no
judge bundle, no expected concept, and no adjudication model, and it never reads a
file outside the repository root it is given.

Contestants arrive by injection, so every test in this package runs against fakes.
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from foundry.domain.common import FrozenModel
from foundry.evaluation.experiment_manifest import (
    MODEL,
    PROVIDER,
    REASONING_EFFORT,
    SDK_PACKAGE,
    ExperimentFreezeViolation,
    sha256_bytes,
)
from foundry.evaluation.loader import load_input
from foundry.evaluation.phase1_execution import (
    INFRASTRUCTURE_RETRY_POLICY,
    PAIRING_POLICY,
    PHASE1_MODEL,
    PHASE1_OUTPUT_MANIFEST_FILENAME,
    PHASE1_OUTPUT_MANIFEST_VERSION,
    PHASE1_PROVIDER,
    PHASE1_REASONING_EFFORT,
    PHASE1_ROOT,
    PHASE1_SDK_PACKAGE,
    SCHEMA_INCOMPATIBILITY_POLICY,
    STRUCTURAL_FAILURE_POLICY,
    TOTAL_CONTESTANT_SLOTS,
    AttemptOutcome,
    AttemptRecord,
    AttemptStartedRecord,
    BaselineRawEvidence,
    BlindOutput,
    FoundryRawEvidence,
    Phase1ArtifactDigest,
    Phase1EvidenceError,
    Phase1ExecutionRecord,
    Phase1OutputManifest,
    Phase1TerminalStatus,
    create_attempt_started,
    phase1_canonical_bytes,
    sanitize_error_text,
    write_evidence,
)
from foundry.evaluation.sealed_exam_manifest import (
    BlindSystemLabel,
    CaseExecutionAssignment,
    ContestantId,
    ExperimentSealViolation,
    HoldoutInputCommitment,
    load_execution_assignment,
    load_experiment_manifest,
    load_holdout_input_manifest,
    verify_phase1_experiment,
)
from foundry.intelligence.baseline import BaselineIntelligence, BaselineResult
from foundry.intelligence.baseline_validation import (
    BaselineValidationError,
    validate_baseline_result,
)
from foundry.intelligence.comparison import neutralize_baseline, neutralize_foundry
from foundry.intelligence.compiler import compile_intelligence_input
from foundry.intelligence.errors import IntelligenceValidationError
from foundry.intelligence.input import IntelligenceInput
from foundry.intelligence.port import IntentIntelligence
from foundry.intelligence.proposals import IntentIntelligenceResult
from foundry.intelligence.validation import validate_intelligence_result

EXPERIMENT_MANIFEST_PATH = "evals/comparative/experiment-manifest.json"
PRE_EXAM_AUDIT_PATH = "evals/comparative/audit/9j3-pre-exam-audit.json"
PRE_EXAM_AUDIT_VERSION = "9j3-pre-exam-audit-v1"
AUDITED_9J2_COMMIT = "46edc23b23585d4cd10ff00e8f9c91297bbc9e4c"

RUNNER_MODULE_PATHS: tuple[str, ...] = (
    "src/foundry/evaluation/phase1_execution.py",
    "src/foundry/evaluation/phase1_live.py",
    "src/foundry/evaluation/phase1_runner.py",
)

SEALED_EVALS_DIRECTORY_NAME = ".foundry-sealed-evals"

PROVIDER_SCHEMA_MARKER = "PROVIDER_SCHEMA_INCOMPATIBILITY:"
INFRASTRUCTURE_STATUS_CODES = frozenset(
    {"DEADLINE_EXCEEDED", "UNAVAILABLE", "RESOURCE_EXHAUSTED"}
)

_COMMIT_PATTERN = r"^[0-9a-f]{40}$"

GitBlobReader = Callable[[str, str], bytes]
Clock = Callable[[], datetime]
ExecutionIdFactory = Callable[[], str]
Progress = Callable[[str], None]


class Phase1RunnerError(RuntimeError):
    """Base class for every Phase-1 orchestration failure."""


class Phase1SealViolation(Phase1RunnerError):
    """A sealed input, audit, runner artifact, or frozen output failed verification."""


class Phase1AlreadyFrozen(Phase1RunnerError):
    """The Phase-1 output manifest exists; this bundle may never call a contestant again."""


class AmbiguousInFlightAttempt(Phase1RunnerError):
    """A started attempt has no completion. Whether a semantic response existed is unknowable."""


class Phase1Paused(Phase1RunnerError):
    """Two infrastructure failures on one slot. Availability recovery, not semantic rerolling."""


class Phase1Abort(Phase1RunnerError):
    """An unrecoverable, non-contestant failure. The experiment stops for architectural review."""

    def __init__(self, message: str, outcome: AttemptOutcome) -> None:
        super().__init__(message)
        self.outcome = outcome


class PreExamAudit(FrozenModel):
    """The SAFE public 9J3 audit surface. Carries no hidden concept."""

    model_config = FrozenModel.model_config | {"extra": "ignore"}

    audit_version: str
    result: str
    blocking_findings: int
    case_count: int
    greenfield_count: int
    brownfield_count: int
    public_seal_verified: bool
    contestant_freeze_verified: bool
    hidden_judge_commitment_verified: bool
    contestant_calls_before_audit: int
    audited_9j2_commit: str
    audited_experiment_manifest_sha256: str


class Phase1Preflight(FrozenModel):
    experiment_manifest_sha256: str
    pre_exam_audit_sha256: str
    runner_commit_sha: str = Field(pattern=_COMMIT_PATTERN)
    runner_artifacts: tuple[Phase1ArtifactDigest, ...]
    case_sequence: tuple[str, ...]
    total_contestant_slots: Literal[24]
    sdk_version: str


class _SealedExam(FrozenModel):
    preflight: Phase1Preflight
    cases: tuple[HoldoutInputCommitment, ...]
    assignments: tuple[CaseExecutionAssignment, ...]


# --------------------------------------------------------------------------- classification


def classify_exception(exc: BaseException) -> AttemptOutcome:
    """Deterministic, conservative classification over the whole exception chain.

    Only an explicitly recognised transport/availability condition counts as
    infrastructure. Anything unrecognised is an executor defect and aborts, because a
    runner bug must never be recorded against a contestant.
    """
    chain = tuple(_exception_chain(exc))

    for candidate in chain:
        if str(candidate).lstrip().startswith(PROVIDER_SCHEMA_MARKER):
            return AttemptOutcome.PROVIDER_SCHEMA_INCOMPATIBILITY

    for candidate in chain:
        if isinstance(candidate, TimeoutError | ConnectionError):
            return AttemptOutcome.INFRASTRUCTURE_FAILURE
        if _status_code_name(candidate) in INFRASTRUCTURE_STATUS_CODES:
            return AttemptOutcome.INFRASTRUCTURE_FAILURE

    for candidate in chain:
        if isinstance(
            candidate,
            ValidationError
            | json.JSONDecodeError
            | IntelligenceValidationError
            | BaselineValidationError,
        ):
            return AttemptOutcome.STRUCTURAL_FAILURE

    return AttemptOutcome.EXECUTOR_FAILURE


def _exception_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    queue: list[BaseException] = [exc]
    while queue:
        current = queue.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                queue.append(linked)


def _status_code_name(exc: BaseException) -> str | None:
    code = getattr(exc, "code", None)
    if not callable(code):
        return None
    try:
        value = code()
    except Exception:  # noqa: BLE001 - a defective provider object must not crash triage
        return None
    name = getattr(value, "name", None)
    return str(name) if name is not None else None


# --------------------------------------------------------------------------- seal gates


def git_blob_reader(repo_root: Path) -> GitBlobReader:
    def read(commit: str, path: str) -> bytes:
        try:
            return subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", "-C", str(repo_root), "show", commit + ":" + path],
                capture_output=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise Phase1SealViolation(
                "cannot read " + path + " at runner commit " + commit
            ) from exc

    return read


def compute_runner_artifacts(
    repo_root: Path,
    runner_commit_sha: str,
    blob_reader: GitBlobReader,
) -> tuple[Phase1ArtifactDigest, ...]:
    """The working tree must be byte-identical to the frozen runner commit."""
    digests: list[Phase1ArtifactDigest] = []
    for relative in RUNNER_MODULE_PATHS:
        try:
            working = (repo_root / relative).read_bytes()
        except OSError as exc:
            raise Phase1SealViolation("missing runner module: " + relative) from exc
        committed = blob_reader(runner_commit_sha, relative)
        working_digest = sha256_bytes(working)
        if working_digest != sha256_bytes(committed):
            raise Phase1SealViolation(
                "RUNNER FREEZE VIOLATION: "
                + relative
                + " differs from runner commit "
                + runner_commit_sha
            )
        digests.append(Phase1ArtifactDigest(path=relative, sha256=working_digest))
    return tuple(digests)


def verify_pre_exam_audit(repo_root: Path, experiment_manifest_sha256: str) -> tuple[
    PreExamAudit, str
]:
    """Verify the SAFE public 9J3 audit. Reads no hidden judge content."""
    path = repo_root / PRE_EXAM_AUDIT_PATH
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Phase1SealViolation("missing 9J3 pre-exam audit: " + PRE_EXAM_AUDIT_PATH) from exc
    try:
        audit = PreExamAudit.model_validate(json.loads(raw.decode("utf-8")))
    except (ValidationError, ValueError) as exc:
        raise Phase1SealViolation("malformed 9J3 pre-exam audit: " + str(exc)) from exc

    expected: tuple[tuple[str, object], ...] = (
        ("audit_version", PRE_EXAM_AUDIT_VERSION),
        ("result", "PASS"),
        ("blocking_findings", 0),
        ("case_count", 12),
        ("greenfield_count", 6),
        ("brownfield_count", 6),
        ("public_seal_verified", True),
        ("contestant_freeze_verified", True),
        ("hidden_judge_commitment_verified", True),
        ("contestant_calls_before_audit", 0),
        ("audited_9j2_commit", AUDITED_9J2_COMMIT),
        ("audited_experiment_manifest_sha256", experiment_manifest_sha256),
    )
    for field, value in expected:
        actual = getattr(audit, field)
        if actual != value:
            raise Phase1SealViolation(
                "9J3 AUDIT GATE FAILED: "
                + field
                + " expected="
                + repr(value)
                + " actual="
                + repr(actual)
            )
    return audit, sha256_bytes(raw)


def require_judge_absent(repo_root: Path) -> None:
    """Phase 1 must execute where the sealed judge physically is not."""
    forbidden = repo_root.resolve().parent / SEALED_EVALS_DIRECTORY_NAME
    if forbidden.exists():
        raise Phase1SealViolation(
            "PHASE1 JUDGE ISOLATION VIOLATION: sealed evals present beside the execution "
            "tree: " + str(forbidden)
        )
    inside = repo_root.resolve() / SEALED_EVALS_DIRECTORY_NAME
    if inside.exists():
        raise Phase1SealViolation(
            "PHASE1 JUDGE ISOLATION VIOLATION: sealed evals copied into the execution tree"
        )


def preflight(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    sdk_version: str | None = None,
    blob_reader: GitBlobReader | None = None,
    require_isolation: bool = True,
) -> Phase1Preflight:
    """Verify every public seal. Makes ZERO model calls."""
    return _load_sealed_exam(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        sdk_version=sdk_version,
        blob_reader=blob_reader,
        require_isolation=require_isolation,
        require_no_output_manifest=True,
    ).preflight


def _load_sealed_exam(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    sdk_version: str | None,
    blob_reader: GitBlobReader | None,
    require_isolation: bool,
    require_no_output_manifest: bool,
) -> _SealedExam:
    if re.fullmatch(_COMMIT_PATTERN, runner_commit_sha) is None:
        raise Phase1SealViolation(
            "runner commit must be a 40-character lowercase hex SHA: " + runner_commit_sha
        )
    if require_isolation:
        require_judge_absent(repo_root)

    if require_no_output_manifest and _manifest_path(repo_root).exists():
        raise Phase1AlreadyFrozen(
            "Phase-1 output is already frozen at "
            + PHASE1_ROOT
            + "/"
            + PHASE1_OUTPUT_MANIFEST_FILENAME
        )

    try:
        manifest_bytes = (repo_root / EXPERIMENT_MANIFEST_PATH).read_bytes()
    except OSError as exc:
        raise Phase1SealViolation(
            "missing experiment manifest: " + EXPERIMENT_MANIFEST_PATH
        ) from exc
    experiment_manifest_sha256 = sha256_bytes(manifest_bytes)

    experiment = load_experiment_manifest(repo_root / EXPERIMENT_MANIFEST_PATH)
    try:
        verify_phase1_experiment(experiment, repo_root, sdk_version=sdk_version)
    except (ExperimentSealViolation, ExperimentFreezeViolation) as exc:
        raise Phase1SealViolation("SEALED EXPERIMENT INVALID: " + str(exc)) from exc

    _, audit_sha256 = verify_pre_exam_audit(repo_root, experiment_manifest_sha256)

    holdouts = load_holdout_input_manifest(repo_root / experiment.holdout_input_manifest_path)
    assignment = load_execution_assignment(repo_root / experiment.execution_assignment_path)
    resolved_sdk_version = _resolve_sdk_version(repo_root, experiment.contestant_freeze_path)

    reader = blob_reader if blob_reader is not None else git_blob_reader(repo_root)
    artifacts = compute_runner_artifacts(repo_root, runner_commit_sha, reader)

    return _SealedExam(
        preflight=Phase1Preflight(
            experiment_manifest_sha256=experiment_manifest_sha256,
            pre_exam_audit_sha256=audit_sha256,
            runner_commit_sha=runner_commit_sha,
            runner_artifacts=artifacts,
            case_sequence=tuple(case.case_id for case in holdouts.cases),
            total_contestant_slots=TOTAL_CONTESTANT_SLOTS,
            sdk_version=resolved_sdk_version,
        ),
        cases=holdouts.cases,
        assignments=assignment.assignments,
    )


def _resolve_sdk_version(repo_root: Path, contestant_freeze_path: str) -> str:
    payload = json.loads((repo_root / contestant_freeze_path).read_text(encoding="utf-8"))
    declared = {payload["contestant_a"]["sdk_version"], payload["contestant_b"]["sdk_version"]}
    if len(declared) != 1:
        raise Phase1SealViolation("contestants declare different SDK versions")
    return str(declared.pop())


# --------------------------------------------------------------------------- execution


def run_phase1(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    foundry: IntentIntelligence,
    baseline: BaselineIntelligence,
    sdk_version: str | None = None,
    resume: bool = False,
    blob_reader: GitBlobReader | None = None,
    clock: Clock | None = None,
    execution_id_factory: ExecutionIdFactory | None = None,
    progress: Progress | None = None,
    require_isolation: bool = True,
) -> Phase1OutputManifest:
    """Execute the frozen 12-case exam over 24 contestant slots. Never judges output."""
    tick = clock if clock is not None else _utc_now
    next_id = execution_id_factory if execution_id_factory is not None else _new_execution_id
    report = progress if progress is not None else _discard

    _require_frozen_provider_identity()
    exam = _load_sealed_exam(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        sdk_version=sdk_version,
        blob_reader=blob_reader,
        require_isolation=require_isolation,
        require_no_output_manifest=True,
    )

    started_at = tick()
    executor = _SlotExecutor(
        repo_root=repo_root,
        foundry=foundry,
        baseline=baseline,
        tick=tick,
        next_id=next_id,
        report=report,
    )
    executor.require_no_ambiguous_in_flight()
    if not resume and executor.has_prior_progress():
        raise Phase1SealViolation(
            "Phase-1 evidence already exists; continue with --resume so prior attempts "
            "and terminal slots are preserved"
        )

    assignments = {item.case_id: item for item in exam.assignments}
    executions: list[Phase1ExecutionRecord] = []
    total = len(exam.cases)
    for index, case in enumerate(exam.cases, start=1):
        eval_input = load_input((repo_root / case.input_path).parent)
        request = compile_intelligence_input(eval_input)
        assignment = assignments[case.case_id]
        for position in (1, 2):
            contestant = (
                assignment.first_contestant if position == 1 else assignment.second_contestant
            )
            label = (
                assignment.foundry_blind_label
                if contestant is ContestantId.FOUNDRY
                else assignment.baseline_blind_label
            )
            executions.append(
                executor.resolve_slot(
                    case_id=case.case_id,
                    case_index=index,
                    case_total=total,
                    contestant=contestant,
                    label=label,
                    position=position,
                    request=request,
                )
            )

    manifest = Phase1OutputManifest(
        manifest_version=PHASE1_OUTPUT_MANIFEST_VERSION,
        experiment_manifest_sha256=exam.preflight.experiment_manifest_sha256,
        pre_exam_audit_sha256=exam.preflight.pre_exam_audit_sha256,
        runner_commit_sha=runner_commit_sha,
        runner_artifacts=exam.preflight.runner_artifacts,
        provider=PHASE1_PROVIDER,
        model=PHASE1_MODEL,
        reasoning_effort=PHASE1_REASONING_EFFORT,
        sdk_package=PHASE1_SDK_PACKAGE,
        sdk_version=exam.preflight.sdk_version,
        provider_revision=None,
        provider_revision_observable=False,
        pairing_policy=PAIRING_POLICY,
        infrastructure_retry_policy=INFRASTRUCTURE_RETRY_POLICY,
        structural_failure_policy=STRUCTURAL_FAILURE_POLICY,
        schema_incompatibility_policy=SCHEMA_INCOMPATIBILITY_POLICY,
        case_sequence=exam.preflight.case_sequence,
        executions=tuple(executions),
        attempts=executor.load_all_attempts(),
        total_contestant_slots=TOTAL_CONTESTANT_SLOTS,
        valid_results=sum(
            item.terminal_status is Phase1TerminalStatus.VALID for item in executions
        ),
        structural_failures=sum(
            item.terminal_status is Phase1TerminalStatus.STRUCTURAL_FAILURE
            for item in executions
        ),
        infrastructure_failures=executor.infrastructure_failure_count(),
        infrastructure_retries=sum(item.infrastructure_retry_count for item in executions),
        started_at=started_at,
        completed_at=tick(),
    )
    write_evidence(repo_root, _manifest_relative(), manifest)
    report("phase1 output frozen")
    return manifest


class _SlotExecutor:
    """Owns append-only call evidence and the frozen per-slot failure policy."""

    def __init__(
        self,
        *,
        repo_root: Path,
        foundry: IntentIntelligence,
        baseline: BaselineIntelligence,
        tick: Clock,
        next_id: ExecutionIdFactory,
        report: Progress,
    ) -> None:
        self._root = repo_root
        self._foundry = foundry
        self._baseline = baseline
        self._tick = tick
        self._next_id = next_id
        self._report = report
        self._attempts_dir = repo_root / PHASE1_ROOT / "attempts"

    # -- evidence surface -------------------------------------------------------

    def require_no_ambiguous_in_flight(self) -> None:
        if not self._attempts_dir.exists():
            return
        for started in sorted(self._attempts_dir.glob("*-started.json")):
            execution_id = started.name.removesuffix("-started.json")
            if not (self._attempts_dir / (execution_id + "-completed.json")).exists():
                raise AmbiguousInFlightAttempt(
                    "STOP - AMBIGUOUS IN-FLIGHT CALL: attempt "
                    + execution_id
                    + " started but never completed; whether a semantic response existed "
                    "cannot be known, so this contestant may not be rerun"
                )

    def has_prior_progress(self) -> bool:
        records = self._root / PHASE1_ROOT / "records"
        return bool(list(self._attempts_dir.glob("*.json"))) if self._attempts_dir.exists() else (
            records.exists() and bool(list(records.glob("*.json")))
        )

    def load_all_attempts(self) -> tuple[AttemptRecord, ...]:
        if not self._attempts_dir.exists():
            return ()
        records = [
            AttemptRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self._attempts_dir.glob("*-completed.json"))
        ]
        records.sort(key=lambda item: (item.started_at, item.execution_id))
        return tuple(records)

    def infrastructure_failure_count(self) -> int:
        return sum(
            item.outcome is AttemptOutcome.INFRASTRUCTURE_FAILURE
            for item in self.load_all_attempts()
        )

    def _slot_attempts(self, case_id: str, contestant: ContestantId) -> tuple[AttemptRecord, ...]:
        """Prior attempts for one slot, in authoritative attempt order."""
        matching = [
            item
            for item in self.load_all_attempts()
            if item.case_id == case_id and item.contestant_id is contestant
        ]
        matching.sort(key=lambda item: (item.attempt_number, item.execution_id))
        return tuple(matching)

    # -- slot resolution --------------------------------------------------------

    def resolve_slot(
        self,
        *,
        case_id: str,
        case_index: int,
        case_total: int,
        contestant: ContestantId,
        label: BlindSystemLabel,
        position: int,
        request: IntelligenceInput,
    ) -> Phase1ExecutionRecord:
        relative = _record_relative(case_id, contestant)
        target = self._root / relative
        if target.exists():
            record = self._validate_existing_record(
                target, case_id, contestant, label, position
            )
            self._log(case_index, case_total, position, "already terminal")
            return record
        return self._execute_slot(
            case_id=case_id,
            case_index=case_index,
            case_total=case_total,
            contestant=contestant,
            label=label,
            position=position,
            request=request,
            relative=relative,
        )

    def _validate_existing_record(
        self,
        target: Path,
        case_id: str,
        contestant: ContestantId,
        label: BlindSystemLabel,
        position: int,
    ) -> Phase1ExecutionRecord:
        try:
            record = Phase1ExecutionRecord.model_validate(
                json.loads(target.read_text(encoding="utf-8"))
            )
        except (ValidationError, ValueError) as exc:
            raise Phase1SealViolation(
                "unreadable terminal record for " + case_id + " " + contestant.value
            ) from exc
        if (
            record.case_id != case_id
            or record.contestant_id is not contestant
            or record.blind_label is not label
            or record.execution_position != position
        ):
            raise Phase1SealViolation(
                "terminal record does not match the frozen assignment for "
                + case_id
                + " "
                + contestant.value
            )
        _require_digest(self._root, record.raw_result_path, record.raw_result_sha256, "raw")
        _require_digest(self._root, record.blind_output_path, record.blind_output_sha256, "blind")
        return record

    def _execute_slot(
        self,
        *,
        case_id: str,
        case_index: int,
        case_total: int,
        contestant: ContestantId,
        label: BlindSystemLabel,
        position: int,
        request: IntelligenceInput,
        relative: str,
    ) -> Phase1ExecutionRecord:
        prior = self._slot_attempts(case_id, contestant)
        attempt_ids: list[str] = [item.execution_id for item in prior]
        infrastructure_failures = sum(
            item.outcome is AttemptOutcome.INFRASTRUCTURE_FAILURE for item in prior
        )
        attempt_number = len(prior) + 1
        immediate_retry_used = False

        while True:
            self._log(case_index, case_total, position, "started")
            execution_id, outcome, result, error = self._call(
                case_id=case_id,
                contestant=contestant,
                label=label,
                position=position,
                attempt_number=attempt_number,
                request=request,
            )
            attempt_ids.append(execution_id)

            if outcome in (
                AttemptOutcome.PROVIDER_SCHEMA_INCOMPATIBILITY,
                AttemptOutcome.EXECUTOR_FAILURE,
            ):
                self._log(case_index, case_total, position, "abort " + outcome.value)
                raise Phase1Abort(
                    "STOP 9K1: " + outcome.value + " on case " + case_id, outcome
                )

            if outcome is AttemptOutcome.INFRASTRUCTURE_FAILURE:
                infrastructure_failures += 1
                self._log(case_index, case_total, position, "infrastructure failure")
                if immediate_retry_used:
                    raise Phase1Paused(
                        "PAUSED_INFRASTRUCTURE: two infrastructure failures on case "
                        + case_id
                        + "; no valid semantic output exists, so the same slot may be "
                        "resumed later"
                    )
                immediate_retry_used = True
                attempt_number += 1
                continue

            record = self._finalize(
                case_id=case_id,
                contestant=contestant,
                label=label,
                position=position,
                outcome=outcome,
                result=result,
                structural_error=error,
                relative=relative,
                attempt_ids=tuple(attempt_ids),
                infrastructure_retry_count=infrastructure_failures,
            )
            self._log(
                case_index, case_total, position, "terminal " + record.terminal_status.value
            )
            return record

    def _call(
        self,
        *,
        case_id: str,
        contestant: ContestantId,
        label: BlindSystemLabel,
        position: int,
        attempt_number: int,
        request: IntelligenceInput,
    ) -> tuple[str, AttemptOutcome, object | None, str | None]:
        """One provider call bracketed by append-only, fsynced call evidence."""
        execution_id = self._next_id()
        started_at = self._tick()
        create_attempt_started(
            self._attempts_dir / (execution_id + "-started.json"),
            AttemptStartedRecord(
                execution_id=execution_id,
                case_id=case_id,
                contestant_id=contestant,
                blind_label=label,
                execution_position=_position(position),
                attempt_number=attempt_number,
                started_at=started_at,
            ),
        )

        result: object | None = None
        structural_error: str | None = None
        error_type: str | None = None
        error_message: str | None = None
        try:
            if contestant is ContestantId.FOUNDRY:
                result = self._foundry.analyze(request)
            else:
                result = self._baseline.analyze(request)
        except BaseException as exc:  # noqa: BLE001 - triage is the runner's job
            outcome = classify_exception(exc)
            error_type = type(exc).__name__
            error_message = sanitize_error_text(str(exc))
            result = None
        else:
            outcome, structural_error = self._validate(contestant, request, result)
            if structural_error is not None:
                error_type = "StructuralValidationError"
                error_message = structural_error

        write_evidence(
            self._root,
            _attempt_relative(execution_id, "completed"),
            AttemptRecord(
                execution_id=execution_id,
                case_id=case_id,
                contestant_id=contestant,
                blind_label=label,
                execution_position=_position(position),
                attempt_number=attempt_number,
                started_at=started_at,
                completed_at=self._tick(),
                outcome=outcome,
                error_type=error_type,
                error_message=error_message,
            ),
        )
        return execution_id, outcome, result, structural_error

    def _validate(
        self,
        contestant: ContestantId,
        request: IntelligenceInput,
        result: object,
    ) -> tuple[AttemptOutcome, str | None]:
        """Deterministic structural validation. Never repairs, never retries."""
        try:
            if contestant is ContestantId.FOUNDRY:
                validate_intelligence_result(request, result)  # type: ignore[arg-type]
            else:
                validate_baseline_result(request, result)  # type: ignore[arg-type]
        except (IntelligenceValidationError, BaselineValidationError, ValueError) as exc:
            return AttemptOutcome.STRUCTURAL_FAILURE, sanitize_error_text(str(exc))
        return AttemptOutcome.VALID_RESULT, None

    def _finalize(
        self,
        *,
        case_id: str,
        contestant: ContestantId,
        label: BlindSystemLabel,
        position: int,
        outcome: AttemptOutcome,
        result: object | None,
        structural_error: str | None,
        relative: str,
        attempt_ids: tuple[str, ...],
        infrastructure_retry_count: int,
    ) -> Phase1ExecutionRecord:
        raw_digest: Phase1ArtifactDigest | None = None
        blind_digest: Phase1ArtifactDigest | None = None
        usage = getattr(result, "usage", None)

        if result is not None:
            raw_digest = write_evidence(
                self._root,
                _raw_relative(case_id, contestant),
                _raw_evidence(case_id, contestant, label, result, structural_error),
            )
        if outcome is AttemptOutcome.VALID_RESULT and result is not None:
            predictions = (
                neutralize_foundry(result)  # type: ignore[arg-type]
                if contestant is ContestantId.FOUNDRY
                else neutralize_baseline(result)  # type: ignore[arg-type]
            )
            blind_digest = write_evidence(
                self._root,
                _blind_relative(case_id, label),
                BlindOutput(
                    case_id=case_id, system_label=label, predictions=predictions
                ),
            )

        record = Phase1ExecutionRecord(
            case_id=case_id,
            contestant_id=contestant,
            blind_label=label,
            execution_position=_position(position),
            terminal_status=(
                Phase1TerminalStatus.VALID
                if outcome is AttemptOutcome.VALID_RESULT
                else Phase1TerminalStatus.STRUCTURAL_FAILURE
            ),
            attempt_execution_ids=attempt_ids,
            infrastructure_retry_count=infrastructure_retry_count,
            raw_result_path=raw_digest.path if raw_digest is not None else None,
            raw_result_sha256=raw_digest.sha256 if raw_digest is not None else None,
            blind_output_path=blind_digest.path if blind_digest is not None else None,
            blind_output_sha256=blind_digest.sha256 if blind_digest is not None else None,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            cost_usd=getattr(usage, "cost_usd", None),
            wall_clock_ms=getattr(usage, "wall_clock_ms", None),
        )
        write_evidence(self._root, relative, record)
        return record

    def _log(self, case_index: int, case_total: int, position: int, event: str) -> None:
        self._report(
            "case "
            + str(case_index)
            + "/"
            + str(case_total)
            + " slot "
            + str(position)
            + "/2 "
            + event
        )


# --------------------------------------------------------------------------- verification


def verify_phase1_output(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    sdk_version: str | None = None,
    blob_reader: GitBlobReader | None = None,
    require_isolation: bool = False,
) -> Phase1OutputManifest:
    """Verify the frozen Phase-1 bundle end to end. Makes ZERO model calls.

    The blind tree is not trusted: every neutral output is REBUILT from its raw result
    through the frozen neutralizer and compared byte for byte.
    """
    exam = _load_sealed_exam(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        sdk_version=sdk_version,
        blob_reader=blob_reader,
        require_isolation=require_isolation,
        require_no_output_manifest=False,
    )
    manifest_path = _manifest_path(repo_root)
    if not manifest_path.exists():
        raise Phase1SealViolation("no frozen Phase-1 output manifest to verify")
    try:
        manifest = Phase1OutputManifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
    except (ValidationError, ValueError) as exc:
        raise Phase1SealViolation("malformed Phase-1 output manifest: " + str(exc)) from exc

    _require_equal("experiment_manifest_sha256", manifest.experiment_manifest_sha256,
                   exam.preflight.experiment_manifest_sha256)
    _require_equal("pre_exam_audit_sha256", manifest.pre_exam_audit_sha256,
                   exam.preflight.pre_exam_audit_sha256)
    _require_equal("runner_commit_sha", manifest.runner_commit_sha, runner_commit_sha)
    _require_equal("runner_artifacts", manifest.runner_artifacts, exam.preflight.runner_artifacts)
    _require_equal("case_sequence", manifest.case_sequence, exam.preflight.case_sequence)
    _require_equal("sdk_version", manifest.sdk_version, exam.preflight.sdk_version)

    assignments = {item.case_id: item for item in exam.assignments}
    cases = {item.case_id: item for item in exam.cases}
    recorded_attempts = {item.execution_id: item for item in manifest.attempts}

    for execution in manifest.executions:
        assignment = assignments[execution.case_id]
        expected_label = (
            assignment.foundry_blind_label
            if execution.contestant_id is ContestantId.FOUNDRY
            else assignment.baseline_blind_label
        )
        if execution.blind_label is not expected_label:
            raise Phase1SealViolation(
                "blind-label mapping drifted for "
                + execution.case_id
                + " "
                + execution.contestant_id.value
            )
        expected_position = 1 if assignment.first_contestant is execution.contestant_id else 2
        if execution.execution_position != expected_position:
            raise Phase1SealViolation(
                "execution order drifted for "
                + execution.case_id
                + " "
                + execution.contestant_id.value
            )

        stored = _load_record(repo_root, execution.case_id, execution.contestant_id)
        if phase1_canonical_bytes(stored) != phase1_canonical_bytes(execution):
            raise Phase1SealViolation(
                "terminal record on disk differs from the manifest for "
                + execution.case_id
                + " "
                + execution.contestant_id.value
            )

        for execution_id in execution.attempt_execution_ids:
            attempt = recorded_attempts.get(execution_id)
            if attempt is None:
                raise Phase1SealViolation("manifest omits attempt " + execution_id)
            stored_attempt = _load_attempt(repo_root, execution_id)
            if phase1_canonical_bytes(stored_attempt) != phase1_canonical_bytes(attempt):
                raise Phase1SealViolation(
                    "attempt record on disk differs from the manifest: " + execution_id
                )
            if (
                attempt.case_id != execution.case_id
                or attempt.contestant_id is not execution.contestant_id
            ):
                raise Phase1SealViolation("attempt " + execution_id + " belongs to another slot")

        _verify_slot_evidence(repo_root, execution, cases[execution.case_id])

    _require_no_orphan_attempt(repo_root, manifest)
    return manifest


def _verify_slot_evidence(
    repo_root: Path,
    execution: Phase1ExecutionRecord,
    case: HoldoutInputCommitment,
) -> None:
    if execution.raw_result_path is None:
        if execution.terminal_status is Phase1TerminalStatus.VALID:
            raise Phase1SealViolation("VALID slot without a raw result: " + execution.case_id)
        if execution.blind_output_path is not None:
            raise Phase1SealViolation(
                "blind output without a raw result: " + execution.case_id
            )
        return

    raw_bytes = _read_repo_bytes(repo_root, execution.raw_result_path, "raw result")
    if sha256_bytes(raw_bytes) != execution.raw_result_sha256:
        raise Phase1SealViolation(
            "raw result hash mismatch at " + str(execution.raw_result_path)
        )

    payload = json.loads(raw_bytes.decode("utf-8"))
    request = compile_intelligence_input(load_input((repo_root / case.input_path).parent))
    try:
        if execution.contestant_id is ContestantId.FOUNDRY:
            evidence: FoundryRawEvidence | BaselineRawEvidence = (
                FoundryRawEvidence.model_validate(payload)
            )
        else:
            evidence = BaselineRawEvidence.model_validate(payload)
    except ValidationError as exc:
        raise Phase1SealViolation(
            "malformed raw evidence at " + str(execution.raw_result_path)
        ) from exc

    if evidence.case_id != execution.case_id or evidence.blind_label is not execution.blind_label:
        raise Phase1SealViolation(
            "raw evidence identity drifted at " + str(execution.raw_result_path)
        )

    revalidated = _revalidate(request, evidence)
    if revalidated != (execution.terminal_status is Phase1TerminalStatus.VALID):
        raise Phase1SealViolation(
            "terminal status disagrees with deterministic revalidation for "
            + execution.case_id
            + " "
            + execution.contestant_id.value
        )
    if revalidated != evidence.structural_validation_passed:
        raise Phase1SealViolation(
            "recorded structural verdict disagrees with revalidation at "
            + str(execution.raw_result_path)
        )

    if not revalidated:
        if execution.blind_output_path is not None:
            raise Phase1SealViolation(
                "a structural failure may not carry a blind output: " + execution.case_id
            )
        return

    if execution.blind_output_path is None:
        raise Phase1SealViolation("VALID slot without a blind output: " + execution.case_id)

    predictions = (
        neutralize_foundry(evidence.result)
        if isinstance(evidence, FoundryRawEvidence)
        else neutralize_baseline(evidence.result)
    )
    rebuilt = BlindOutput(
        case_id=execution.case_id,
        system_label=execution.blind_label,
        predictions=predictions,
    )
    expected = phase1_canonical_bytes(rebuilt)
    actual = _read_repo_bytes(repo_root, execution.blind_output_path, "blind output")
    if actual != expected:
        raise Phase1SealViolation(
            "blind output is not the deterministic neutralization of its raw result: "
            + str(execution.blind_output_path)
        )
    if sha256_bytes(actual) != execution.blind_output_sha256:
        raise Phase1SealViolation(
            "blind output hash mismatch at " + str(execution.blind_output_path)
        )
    if execution.blind_output_path != _blind_relative(execution.case_id, execution.blind_label):
        raise Phase1SealViolation(
            "blind output written under the wrong label: " + str(execution.blind_output_path)
        )


def _revalidate(
    request: IntelligenceInput,
    evidence: FoundryRawEvidence | BaselineRawEvidence,
) -> bool:
    try:
        if isinstance(evidence, FoundryRawEvidence):
            validate_intelligence_result(request, evidence.result)
        else:
            validate_baseline_result(request, evidence.result)
    except (IntelligenceValidationError, BaselineValidationError, ValueError):
        return False
    return True


def _require_no_orphan_attempt(repo_root: Path, manifest: Phase1OutputManifest) -> None:
    directory = repo_root / PHASE1_ROOT / "attempts"
    completed = {
        path.name.removesuffix("-completed.json")
        for path in directory.glob("*-completed.json")
    }
    started = {path.name.removesuffix("-started.json") for path in directory.glob("*-started.json")}
    if started - completed:
        raise AmbiguousInFlightAttempt(
            "STOP - AMBIGUOUS IN-FLIGHT CALL: " + ", ".join(sorted(started - completed))
        )
    recorded = {item.execution_id for item in manifest.attempts}
    if completed != recorded:
        raise Phase1SealViolation(
            "attempt files and manifest attempts disagree; differing: "
            + ", ".join(sorted(completed ^ recorded))
        )


# --------------------------------------------------------------------------- helpers


def _require_frozen_provider_identity() -> None:
    """The Phase-1 literals must still equal the sealed contestant-freeze constants."""
    for field, local, sealed in (
        ("provider", PHASE1_PROVIDER, PROVIDER),
        ("model", PHASE1_MODEL, MODEL),
        ("reasoning_effort", PHASE1_REASONING_EFFORT, REASONING_EFFORT),
        ("sdk_package", PHASE1_SDK_PACKAGE, SDK_PACKAGE),
    ):
        if local != sealed:
            raise Phase1SealViolation(
                "CONTESTANT IDENTITY DRIFT: "
                + field
                + " sealed="
                + repr(sealed)
                + " phase1="
                + repr(local)
            )


def _raw_evidence(
    case_id: str,
    contestant: ContestantId,
    label: BlindSystemLabel,
    result: object,
    structural_error: str | None,
) -> FoundryRawEvidence | BaselineRawEvidence:
    passed = structural_error is None
    if contestant is ContestantId.FOUNDRY:
        return FoundryRawEvidence(
            case_id=case_id,
            contestant_id=ContestantId.FOUNDRY,
            blind_label=label,
            result=_as_foundry(result),
            structural_validation_passed=passed,
            structural_error=structural_error,
        )
    return BaselineRawEvidence(
        case_id=case_id,
        contestant_id=ContestantId.BASELINE,
        blind_label=label,
        result=_as_baseline(result),
        structural_validation_passed=passed,
        structural_error=structural_error,
    )


def _as_foundry(result: object) -> IntentIntelligenceResult:
    if not isinstance(result, IntentIntelligenceResult):
        raise Phase1Abort(
            "STOP 9K1: Foundry contestant returned an unexpected type",
            AttemptOutcome.EXECUTOR_FAILURE,
        )
    return result


def _as_baseline(result: object) -> BaselineResult:
    if not isinstance(result, BaselineResult):
        raise Phase1Abort(
            "STOP 9K1: baseline contestant returned an unexpected type",
            AttemptOutcome.EXECUTOR_FAILURE,
        )
    return result


def _load_record(
    repo_root: Path, case_id: str, contestant: ContestantId
) -> Phase1ExecutionRecord:
    raw = _read_repo_bytes(
        repo_root, _record_relative(case_id, contestant), "terminal record"
    )
    try:
        return Phase1ExecutionRecord.model_validate(json.loads(raw.decode("utf-8")))
    except (ValidationError, ValueError) as exc:
        raise Phase1SealViolation(
            "malformed terminal record for " + case_id + " " + contestant.value
        ) from exc


def _load_attempt(repo_root: Path, execution_id: str) -> AttemptRecord:
    raw = _read_repo_bytes(
        repo_root, _attempt_relative(execution_id, "completed"), "attempt record"
    )
    try:
        return AttemptRecord.model_validate(json.loads(raw.decode("utf-8")))
    except (ValidationError, ValueError) as exc:
        raise Phase1SealViolation("malformed attempt record " + execution_id) from exc


def _read_repo_bytes(repo_root: Path, relative: str, label: str) -> bytes:
    try:
        return (repo_root / relative).read_bytes()
    except OSError as exc:
        raise Phase1SealViolation("missing " + label + ": " + relative) from exc


def _require_digest(
    repo_root: Path, relative: str | None, expected: str | None, label: str
) -> None:
    if relative is None or expected is None:
        return
    if sha256_bytes(_read_repo_bytes(repo_root, relative, label)) != expected:
        raise Phase1SealViolation(label + " evidence hash mismatch at " + relative)


def _require_equal(field: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise Phase1SealViolation(
            "PHASE1 OUTPUT VERIFICATION FAILED: "
            + field
            + " expected="
            + repr(expected)
            + " actual="
            + repr(actual)
        )


def _record_relative(case_id: str, contestant: ContestantId) -> str:
    return PHASE1_ROOT + "/records/" + case_id + "-" + contestant.value + ".json"


def _raw_relative(case_id: str, contestant: ContestantId) -> str:
    return PHASE1_ROOT + "/raw/" + case_id + "/" + contestant.value + ".json"


def _blind_relative(case_id: str, label: BlindSystemLabel) -> str:
    return PHASE1_ROOT + "/blind/" + case_id + "/" + label.value + ".json"


def _attempt_relative(execution_id: str, suffix: str) -> str:
    return PHASE1_ROOT + "/attempts/" + execution_id + "-" + suffix + ".json"


def _manifest_relative() -> str:
    return PHASE1_ROOT + "/" + PHASE1_OUTPUT_MANIFEST_FILENAME


def _manifest_path(repo_root: Path) -> Path:
    return repo_root / _manifest_relative()


def _position(value: int) -> Literal[1, 2]:
    if value == 1:
        return 1
    if value == 2:
        return 2
    raise Phase1Abort(
        "STOP 9K1: invalid execution position " + str(value),
        AttemptOutcome.EXECUTOR_FAILURE,
    )


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _new_execution_id() -> str:
    return str(uuid.uuid4())


def _discard(message: str) -> None:
    return None


__all__ = [
    "AUDITED_9J2_COMMIT",
    "AmbiguousInFlightAttempt",
    "EXPERIMENT_MANIFEST_PATH",
    "INFRASTRUCTURE_STATUS_CODES",
    "PRE_EXAM_AUDIT_PATH",
    "PRE_EXAM_AUDIT_VERSION",
    "Phase1Abort",
    "Phase1AlreadyFrozen",
    "Phase1EvidenceError",
    "Phase1Paused",
    "Phase1Preflight",
    "Phase1RunnerError",
    "Phase1SealViolation",
    "PreExamAudit",
    "RUNNER_MODULE_PATHS",
    "classify_exception",
    "compute_runner_artifacts",
    "git_blob_reader",
    "preflight",
    "require_judge_absent",
    "run_phase1",
    "verify_phase1_output",
    "verify_pre_exam_audit",
]

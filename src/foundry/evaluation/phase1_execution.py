"""Phase-1 execution evidence for the Intent Intelligence comparative exam (Task 9K1).

This module owns ONLY evidence schemas, canonical serialization, hashing, and
append-only file writing. It performs no provider call, no orchestration, and no
semantic judgement.

Judge blindness is structural, not conventional: nothing here imports the hidden
judge bundle, an expected concept, or any adjudication model. The only semantic
surface it carries forward to Phase 2 is ``BlindPrediction``.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from foundry.domain.common import FrozenModel
from foundry.evaluation.experiment_manifest import sha256_bytes
from foundry.evaluation.sealed_exam_manifest import BlindSystemLabel, ContestantId
from foundry.intelligence.baseline import BaselineResult
from foundry.intelligence.comparison import BlindPrediction
from foundry.intelligence.proposals import IntentIntelligenceResult

PHASE1_OUTPUT_MANIFEST_VERSION: Final[Literal["intent-comparative-phase1-output-v1"]] = (
    "intent-comparative-phase1-output-v1"
)

TOTAL_CONTESTANT_SLOTS: Final[Literal[24]] = 24
FIRST_SUITE_CASE_COUNT: Final[int] = 12

# Frozen provider identity for this experiment. Declared here as literals so the
# manifest cannot be built with a value nobody upstream froze; the runner asserts
# they still equal the sealed contestant-freeze constants before writing evidence.
PHASE1_PROVIDER: Final[Literal["xAI"]] = "xAI"
PHASE1_MODEL: Final[Literal["grok-4.6"]] = "grok-4.6"
PHASE1_REASONING_EFFORT: Final[Literal["high"]] = "high"
PHASE1_SDK_PACKAGE: Final[Literal["xai-sdk"]] = "xai-sdk"

PAIRING_POLICY: Final[Literal["back-to-back"]] = "back-to-back"
INFRASTRUCTURE_RETRY_POLICY: Final[
    Literal["one-immediate-retry-then-pause-resume-same-slot-only"]
] = "one-immediate-retry-then-pause-resume-same-slot-only"
STRUCTURAL_FAILURE_POLICY: Final[Literal["terminal-no-semantic-retry"]] = (
    "terminal-no-semantic-retry"
)
SCHEMA_INCOMPATIBILITY_POLICY: Final[Literal["abort-experiment"]] = "abort-experiment"

PHASE1_ROOT = "evals/comparative/phase1"
PHASE1_OUTPUT_MANIFEST_FILENAME = "phase1-output-manifest.json"

MAX_ERROR_TEXT_LENGTH = 1024
REDACTED = "[REDACTED]"

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(?:x-)?(?:api[_-]?key|apikey|authorization|bearer|secret|password"
        r"|credentials?|access[_-]?token|xai[_-]?api[_-]?key)\b[^,;)\]}\"']*"
    ),
    re.compile(r"(?i)\bxai-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{6,}"),
)


class Phase1EvidenceError(RuntimeError):
    """Raised when Phase-1 evidence is missing, unsafe, or would be overwritten."""


class Phase1WriteConflict(Phase1EvidenceError):
    """Raised when a finalized Phase-1 evidence file would be mutated."""


class Phase1TerminalStatus(StrEnum):
    VALID = "VALID"
    STRUCTURAL_FAILURE = "STRUCTURAL_FAILURE"


class AttemptOutcome(StrEnum):
    VALID_RESULT = "VALID_RESULT"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    STRUCTURAL_FAILURE = "STRUCTURAL_FAILURE"
    PROVIDER_SCHEMA_INCOMPATIBILITY = "PROVIDER_SCHEMA_INCOMPATIBILITY"
    EXECUTOR_FAILURE = "EXECUTOR_FAILURE"


def sanitize_error_text(value: str) -> str:
    """Collapse, redact and truncate provider/runner error text.

    An API key, an environment dump, a request header, or a credential value must
    never reach the evidence ledger. Redaction is deliberately aggressive: losing a
    little diagnostic detail is cheaper than writing a secret to an append-only file.
    """
    collapsed = _CONTROL_CHARACTERS.sub(" ", value)
    for pattern in _SECRET_PATTERNS:
        collapsed = pattern.sub(REDACTED, collapsed)
    collapsed = " ".join(collapsed.split())
    if len(collapsed) > MAX_ERROR_TEXT_LENGTH:
        collapsed = collapsed[: MAX_ERROR_TEXT_LENGTH - 3] + "..."
    return collapsed


def check_safe_relative(value: str) -> str:
    """A Phase-1 path is repository-relative and may not traverse upward."""
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


class Phase1ArtifactDigest(FrozenModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def path_must_be_safe(self) -> Phase1ArtifactDigest:
        check_safe_relative(self.path)
        return self


class _AttemptIdentity(FrozenModel):
    execution_id: str = Field(pattern=_UUID_PATTERN)
    case_id: str = Field(min_length=1)
    contestant_id: ContestantId
    blind_label: BlindSystemLabel
    execution_position: Literal[1, 2]
    attempt_number: int = Field(ge=1)


class AttemptStartedRecord(_AttemptIdentity):
    """Written with exclusive creation BEFORE a provider call. Never mutated."""

    started_at: datetime


class AttemptRecord(_AttemptIdentity):
    """Written once after a provider call resolves. Never rewritten."""

    started_at: datetime
    completed_at: datetime
    outcome: AttemptOutcome
    error_type: str | None = None
    error_message: str | None = None

    @field_validator("error_type", "error_message", mode="before")
    @classmethod
    def sanitize_error_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return sanitize_error_text(value)
        return value

    @model_validator(mode="after")
    def completion_must_not_precede_start(self) -> AttemptRecord:
        if self.completed_at < self.started_at:
            raise ValueError(
                "attempt " + self.execution_id + " completed before it started"
            )
        return self


class _RawEvidenceBase(FrozenModel):
    case_id: str = Field(min_length=1)
    blind_label: BlindSystemLabel
    structural_validation_passed: bool
    structural_error: str | None

    @model_validator(mode="after")
    def structural_error_must_agree_with_the_verdict(self) -> _RawEvidenceBase:
        if self.structural_validation_passed:
            if self.structural_error is not None:
                raise ValueError(
                    "a structurally valid result must carry no structural_error"
                )
        elif not self.structural_error:
            raise ValueError(
                "a structural failure must state a non-empty structural_error"
            )
        return self


class FoundryRawEvidence(_RawEvidenceBase):
    contestant_id: Literal[ContestantId.FOUNDRY]
    result: IntentIntelligenceResult


class BaselineRawEvidence(_RawEvidenceBase):
    contestant_id: Literal[ContestantId.BASELINE]
    result: BaselineResult


class BlindOutput(FrozenModel):
    """The ONLY Phase-1 surface Phase-2 adjudication is allowed to see.

    It carries no contestant identity, no provider, no model, no cost, no token
    count, no system prompt, no semantic proposal, and no original local ID.
    """

    case_id: str = Field(min_length=1)
    system_label: BlindSystemLabel
    predictions: tuple[BlindPrediction, ...]


class Phase1ExecutionRecord(FrozenModel):
    """One terminal contestant slot. Immutable once written."""

    case_id: str = Field(min_length=1)
    contestant_id: ContestantId
    blind_label: BlindSystemLabel
    execution_position: Literal[1, 2]

    terminal_status: Phase1TerminalStatus

    attempt_execution_ids: tuple[str, ...] = Field(min_length=1)
    infrastructure_retry_count: int = Field(ge=0)

    raw_result_path: str | None
    raw_result_sha256: str | None

    blind_output_path: str | None
    blind_output_sha256: str | None

    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    wall_clock_ms: int | None

    @model_validator(mode="after")
    def terminal_evidence_must_be_complete(self) -> Phase1ExecutionRecord:
        _reject_duplicates("attempt_execution_id", self.attempt_execution_ids)
        _require_digest_pair("raw_result", self.raw_result_path, self.raw_result_sha256)
        _require_digest_pair("blind_output", self.blind_output_path, self.blind_output_sha256)

        if self.terminal_status is Phase1TerminalStatus.VALID:
            if self.raw_result_path is None:
                raise ValueError("a VALID slot requires a preserved raw result")
            if self.blind_output_path is None:
                raise ValueError("a VALID slot requires a neutralized blind output")
            for name in ("input_tokens", "output_tokens", "cost_usd", "wall_clock_ms"):
                if getattr(self, name) is None:
                    raise ValueError("a VALID slot requires provider usage: " + name)
        elif self.blind_output_path is not None:
            raise ValueError(
                "a STRUCTURAL_FAILURE slot must have no blind output; "
                "an empty successful output may not be faked"
            )
        return self


class Phase1OutputManifest(FrozenModel):
    manifest_version: Literal["intent-comparative-phase1-output-v1"]

    experiment_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    pre_exam_audit_sha256: str = Field(pattern=_SHA256_PATTERN)

    runner_commit_sha: str = Field(pattern=_COMMIT_PATTERN)

    runner_artifacts: tuple[Phase1ArtifactDigest, ...] = Field(min_length=1)

    provider: Literal["xAI"]
    model: Literal["grok-4.6"]
    reasoning_effort: Literal["high"]
    sdk_package: Literal["xai-sdk"]
    sdk_version: str = Field(min_length=1)

    provider_revision: str | None
    provider_revision_observable: bool

    pairing_policy: Literal["back-to-back"]
    infrastructure_retry_policy: Literal[
        "one-immediate-retry-then-pause-resume-same-slot-only"
    ]
    structural_failure_policy: Literal["terminal-no-semantic-retry"]
    schema_incompatibility_policy: Literal["abort-experiment"]

    case_sequence: tuple[str, ...] = Field(min_length=1)
    executions: tuple[Phase1ExecutionRecord, ...]
    attempts: tuple[AttemptRecord, ...]

    total_contestant_slots: Literal[24]
    valid_results: int = Field(ge=0)
    structural_failures: int = Field(ge=0)
    infrastructure_failures: int = Field(ge=0)
    infrastructure_retries: int = Field(ge=0)

    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def bundle_must_be_complete_and_self_consistent(self) -> Phase1OutputManifest:
        _reject_duplicates("runner artifact path", tuple(a.path for a in self.runner_artifacts))
        _reject_duplicates("case_id", self.case_sequence)
        if len(self.case_sequence) != FIRST_SUITE_CASE_COUNT:
            raise ValueError(
                "the first comparative suite is exactly "
                + str(FIRST_SUITE_CASE_COUNT)
                + " cases; found "
                + str(len(self.case_sequence))
            )
        if self.provider_revision is not None and not self.provider_revision_observable:
            raise ValueError(
                "provider_revision must be null when the frozen adapter cannot observe it"
            )
        if self.completed_at < self.started_at:
            raise ValueError("Phase-1 completed before it started")

        _require_full_slot_cover(self.case_sequence, self.executions)

        valid = sum(
            item.terminal_status is Phase1TerminalStatus.VALID for item in self.executions
        )
        structural = len(self.executions) - valid
        if self.valid_results != valid:
            raise ValueError(
                "valid_results ("
                + str(self.valid_results)
                + ") does not match the recorded terminal statuses ("
                + str(valid)
                + ")"
            )
        if self.structural_failures != structural:
            raise ValueError(
                "structural_failures ("
                + str(self.structural_failures)
                + ") does not match the recorded terminal statuses ("
                + str(structural)
                + ")"
            )
        if self.valid_results + self.structural_failures != TOTAL_CONTESTANT_SLOTS:
            raise ValueError(
                "valid_results + structural_failures must equal "
                + str(TOTAL_CONTESTANT_SLOTS)
            )

        _require_attempt_cover(self.executions, self.attempts)

        infrastructure_failures = sum(
            item.outcome is AttemptOutcome.INFRASTRUCTURE_FAILURE for item in self.attempts
        )
        if self.infrastructure_failures != infrastructure_failures:
            raise ValueError(
                "infrastructure_failures ("
                + str(self.infrastructure_failures)
                + ") does not match the recorded attempts ("
                + str(infrastructure_failures)
                + ")"
            )
        retries = sum(item.infrastructure_retry_count for item in self.executions)
        if self.infrastructure_retries != retries:
            raise ValueError(
                "infrastructure_retries ("
                + str(self.infrastructure_retries)
                + ") does not match the recorded executions ("
                + str(retries)
                + ")"
            )
        return self


def phase1_canonical_bytes(model: BaseModel) -> bytes:
    """Deterministic evidence bytes: sorted keys, stable indent, trailing newline."""
    return phase1_canonical_json(model).encode("utf-8")


def phase1_canonical_json(model: BaseModel) -> str:
    return (
        json.dumps(
            model.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


def phase1_digest(model: BaseModel) -> str:
    return sha256_bytes(phase1_canonical_bytes(model))


def create_attempt_started(path: Path, record: AttemptStartedRecord) -> None:
    """Write the pre-call marker with EXCLUSIVE creation, then flush and fsync.

    The marker must reach the disk before the provider is invoked. Otherwise a crash
    mid-call is indistinguishable from a call that never happened, and a later resume
    could silently reroll a semantic response.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = phase1_canonical_bytes(record)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise Phase1WriteConflict(
            "attempt marker already exists and may not be rewritten: " + str(path)
        ) from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def write_evidence(root: Path, relative: str, model: BaseModel) -> Phase1ArtifactDigest:
    """Atomically finalize one evidence file. Refuses to overwrite a finalized file."""
    check_safe_relative(relative)
    target = root / relative
    if target.exists():
        raise Phase1WriteConflict(
            "refusing to overwrite finalized Phase-1 evidence: " + relative
        )
    payload = phase1_canonical_bytes(model)
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(target, payload)
    return Phase1ArtifactDigest(path=relative, sha256=sha256_bytes(payload))


def read_evidence_bytes(root: Path, relative: str, label: str) -> bytes:
    check_safe_relative(relative)
    try:
        return (root / relative).read_bytes()
    except OSError as exc:
        raise Phase1EvidenceError(
            "missing Phase-1 evidence (" + label + "): " + relative
        ) from exc


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".phase1-", suffix=".tmp")
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


def _require_digest_pair(label: str, path: str | None, digest: str | None) -> None:
    if (path is None) != (digest is None):
        raise ValueError(label + " path and sha256 must be present together")
    if path is not None:
        check_safe_relative(path)
    if digest is not None and re.fullmatch(_SHA256_PATTERN, digest) is None:
        raise ValueError(label + " sha256 must be lowercase 64-hex: " + digest)


def _require_full_slot_cover(
    case_sequence: tuple[str, ...],
    executions: tuple[Phase1ExecutionRecord, ...],
) -> None:
    if len(executions) != TOTAL_CONTESTANT_SLOTS:
        raise ValueError(
            "a frozen Phase-1 bundle holds exactly "
            + str(TOTAL_CONTESTANT_SLOTS)
            + " terminal contestant slots; found "
            + str(len(executions))
        )
    known = set(case_sequence)
    seen: set[tuple[str, str]] = set()
    positions: dict[str, set[int]] = {case_id: set() for case_id in case_sequence}
    for execution in executions:
        if execution.case_id not in known:
            raise ValueError(
                "execution references a case outside the frozen sequence: "
                + execution.case_id
            )
        identity = (execution.case_id, execution.contestant_id.value)
        if identity in seen:
            raise ValueError(
                "terminal slot appears twice: " + identity[0] + " " + identity[1]
            )
        seen.add(identity)
        positions[execution.case_id].add(execution.execution_position)
    for case_id in case_sequence:
        if positions[case_id] != {1, 2}:
            raise ValueError(
                "case " + case_id + " must record execution positions 1 and 2 exactly once"
            )
        for contestant in ContestantId:
            if (case_id, contestant.value) not in seen:
                raise ValueError(
                    "case " + case_id + " is missing contestant " + contestant.value
                )


def _require_attempt_cover(
    executions: tuple[Phase1ExecutionRecord, ...],
    attempts: tuple[AttemptRecord, ...],
) -> None:
    referenced: list[str] = []
    for execution in executions:
        referenced.extend(execution.attempt_execution_ids)
    _reject_duplicates("referenced attempt_execution_id", tuple(referenced))
    recorded = tuple(attempt.execution_id for attempt in attempts)
    _reject_duplicates("attempt execution_id", recorded)
    difference = set(referenced) ^ set(recorded)
    if difference:
        raise ValueError(
            "recorded attempts do not cover the referenced executions; differing: "
            + ", ".join(sorted(difference))
        )


def _reject_duplicates(label: str, values: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError("duplicate " + label + ": " + value)
        seen.add(value)

"""Deterministic Phase-2 blind adjudication orchestration (Task 9K2).

The runner owns sequencing, seal gates, append-only evidence, the retry law and the
frozen deterministic validators. It owns NO provider SDK: the adjudicator is injected
as a callable, so every test in this repository drives it with a fake.

Three laws are enforced here rather than trusted:

  * The adjudicator sees exactly one `BlindAdjudicationPacket` per case and nothing
    else. It is never handed a treatment name, a cost, a token count, a latency, an
    execution order, a contestant prompt, an implementation, or a raw payload.
  * A structurally invalid or validator-failing judgment STOPS the run. It is never
    repaired, never re-prompted, and never re-asked of a second judge.
  * `ADJUDICATION_UNCERTAIN` is a valid primary result. It is frozen as returned and
    escalated to independent blind human review; it is never reconsidered here.

This module computes no semantic metric, no per-system score, and no winner.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field, ValidationError

from foundry.domain.common import FrozenModel
from foundry.evaluation.comparative_protocol import (
    AdjudicationValidationError,
    BlindAdjudicationPacket,
    HiddenJudgeBundle,
    HiddenJudgeCase,
    build_adjudication_mechanism,
    build_semantic_rubric,
    load_adjudication_mechanism,
    load_semantic_rubric,
    validate_first_suite_judge_bundle,
    validate_system_adjudication,
)
from foundry.evaluation.experiment_manifest import sha256_bytes
from foundry.evaluation.loader import load_input
from foundry.evaluation.phase2_adjudication import (
    INFRASTRUCTURE_RETRY_POLICY,
    PHASE2_API,
    PHASE2_CALLS_PER_CASE,
    PHASE2_CONVERSATION_REUSE,
    PHASE2_MODEL,
    PHASE2_OUTPUT_MANIFEST_VERSION,
    PHASE2_PRIMARY_CALL_COUNT,
    PHASE2_PROVIDER,
    PHASE2_REASONING_EFFORT,
    PHASE2_ROOT,
    PHASE2_SDK_PACKAGE,
    PHASE2_STORE,
    PHASE2_TOOLS_ENABLED,
    STRUCTURAL_FAILURE_POLICY,
    UNCERTAINTY_POLICY,
    AdjudicationAttemptRecord,
    AdjudicationAttemptStarted,
    AdjudicationOutcome,
    BlindPredictionIdentityLeak,
    Phase2ArtifactDigest,
    Phase2CallRecord,
    Phase2EvidenceError,
    Phase2OutputManifest,
    PrimaryCaseAdjudication,
    attempt_completed_relative,
    attempt_started_relative,
    build_blind_packet,
    count_uncertain_items,
    create_adjudication_started,
    instruction_digest,
    load_blind_output,
    manifest_relative,
    packet_digest,
    phase2_digest,
    primary_relative,
    record_relative,
    require_no_identity_leak,
    sanitize_error_text,
    write_phase2_evidence,
)
from foundry.evaluation.sealed_exam_manifest import (
    ExperimentManifest,
    ExperimentSealViolation,
    load_experiment_manifest,
    load_holdout_input_manifest,
    validate_first_suite_holdout_manifest,
    verify_revealed_judge_bundle,
)

EXPERIMENT_MANIFEST_PATH = "evals/comparative/experiment-manifest.json"

PHASE2_RUNNER_MODULE_PATHS: tuple[str, ...] = (
    "src/foundry/evaluation/phase2_adjudication.py",
    "src/foundry/evaluation/phase2_live.py",
    "src/foundry/evaluation/phase2_runner.py",
)

# The immutable evidence chain this adjudication is bound to.
PHASE1_OUTPUT_COMMIT = "adc0b88dad0ae98fdaaf28a31c782526b27128dd"
PHASE1_RUNNER_COMMIT = "dd2204393cebb8501445c3dd9449fe5a561a3aa1"

MAX_ATTEMPTS_PER_CASE = 2

_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"

GitBlobReader = Callable[[str, str], bytes]
Clock = Callable[[], datetime]
ExecutionIdFactory = Callable[[], str]
Progress = Callable[[str], None]


# --------------------------------------------------------------------------- errors


class Phase2RunnerError(RuntimeError):
    """Base class for every Phase-2 orchestration failure."""


class Phase2SealViolation(Phase2RunnerError):
    """A sealed input, judge commitment, runner artifact, or frozen output failed."""


class Phase2AlreadyFrozen(Phase2RunnerError):
    """The Phase-2 manifest exists; this bundle may never call the adjudicator again."""


class AmbiguousInFlightAdjudication(Phase2RunnerError):
    """A started attempt has no completion. Whether a judgment existed is unknowable."""


class Phase2Paused(Phase2RunnerError):
    """Two infrastructure failures on one case. Availability recovery, not rerolling."""


class Phase2StructuralFailure(Phase2RunnerError):
    """A returned judgment is schema-invalid or fails the frozen validator. Never repaired."""


class Phase2Abort(Phase2RunnerError):
    """An unrecoverable, non-provider failure. The run stops for architectural review."""


# --------------------------------------------------------------------------- contracts


class RawAdjudicationResponse(FrozenModel):
    """What a provider adapter returns. Parsing and validation happen in the runner."""

    output_text: str = Field(min_length=1)
    provider_response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    wall_clock_ms: int | None = None


Adjudicator = Callable[[BlindAdjudicationPacket], RawAdjudicationResponse]


class Phase1BundleSummary(FrozenModel):
    """The only Phase-1 facts Phase 2 carries forward. No identity, no per-system split."""

    experiment_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    bundle_sha256: str = Field(pattern=_SHA256_PATTERN)
    runner_commit_sha: str = Field(pattern=_COMMIT_PATTERN)
    case_count: int = Field(ge=1)


Phase1Verifier = Callable[..., Phase1BundleSummary]


class Phase2Preflight(FrozenModel):
    """Safe preflight metadata. Carries commitments, never packet or judge content."""

    experiment_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    phase1_output_commit: str = Field(pattern=_COMMIT_PATTERN)
    phase1_runner_commit: str = Field(pattern=_COMMIT_PATTERN)
    phase1_bundle_sha256: str = Field(pattern=_SHA256_PATTERN)
    hidden_judge_commitment_sha256: str = Field(pattern=_SHA256_PATTERN)
    adjudication_mechanism_sha256: str = Field(pattern=_SHA256_PATTERN)
    semantic_rubric_sha256: str = Field(pattern=_SHA256_PATTERN)
    adjudicator_instruction_sha256: str = Field(pattern=_SHA256_PATTERN)
    adjudication_runner_commit: str = Field(pattern=_COMMIT_PATTERN)
    runner_artifacts: tuple[Phase2ArtifactDigest, ...] = Field(min_length=1)
    case_sequence: tuple[str, ...] = Field(min_length=1)
    blind_output_count: int = Field(ge=0)
    packet_digests: tuple[str, ...] = Field(min_length=1)
    sdk_version: str


class _AdjudicationInputs(FrozenModel):
    """Internal only. Holds hidden judge content and is never returned or printed."""

    preflight: Phase2Preflight
    packets: tuple[BlindAdjudicationPacket, ...]


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
            raise Phase2SealViolation(
                "cannot read " + path + " at adjudication runner commit " + commit
            ) from exc

    return read


def compute_runner_artifacts(
    repo_root: Path,
    runner_commit_sha: str,
    blob_reader: GitBlobReader,
) -> tuple[Phase2ArtifactDigest, ...]:
    """The working tree must be byte-identical to the frozen adjudication runner."""
    digests: list[Phase2ArtifactDigest] = []
    for relative in PHASE2_RUNNER_MODULE_PATHS:
        try:
            working = (repo_root / relative).read_bytes()
        except OSError as exc:
            raise Phase2SealViolation("missing adjudication runner module: " + relative) from exc
        committed = blob_reader(runner_commit_sha, relative)
        working_digest = sha256_bytes(working)
        if working_digest != sha256_bytes(committed):
            raise Phase2SealViolation(
                "RUNNER FREEZE VIOLATION: "
                + relative
                + " differs from adjudication runner commit "
                + runner_commit_sha
            )
        digests.append(Phase2ArtifactDigest(path=relative, sha256=working_digest))
    return tuple(digests)


def default_phase1_verifier(
    *, repo_root: Path, blob_reader: GitBlobReader | None = None
) -> Phase1BundleSummary:
    """Run the existing frozen Phase-1 verifier. Makes ZERO model calls.

    The Phase-1 verifier is deterministic verification machinery. It reads its own
    manifest internally; this function extracts only safe aggregate commitments from
    the result and never surfaces a contestant identity or a per-system value.
    """
    from foundry.evaluation.phase1_execution import (
        PHASE1_OUTPUT_MANIFEST_FILENAME,
        PHASE1_ROOT,
    )
    from foundry.evaluation.phase1_runner import verify_phase1_output

    manifest = verify_phase1_output(
        repo_root=repo_root,
        runner_commit_sha=PHASE1_RUNNER_COMMIT,
        blob_reader=blob_reader,
    )
    bundle_path = repo_root / PHASE1_ROOT / PHASE1_OUTPUT_MANIFEST_FILENAME
    return Phase1BundleSummary(
        experiment_manifest_sha256=manifest.experiment_manifest_sha256,
        bundle_sha256=sha256_bytes(bundle_path.read_bytes()),
        runner_commit_sha=manifest.runner_commit_sha,
        case_count=len(manifest.case_sequence),
    )


def _verify_frozen_protocol(repo_root: Path, manifest: ExperimentManifest) -> tuple[str, str]:
    """The frozen mechanism and rubric must still be the declarations 9J1 committed."""
    mechanism_bytes = _read_repo_bytes(
        repo_root, manifest.adjudication_mechanism_path, "adjudication mechanism"
    )
    _require_hash(
        "adjudication mechanism",
        manifest.adjudication_mechanism_path,
        sha256_bytes(mechanism_bytes),
        manifest.adjudication_mechanism_sha256,
    )
    rubric_bytes = _read_repo_bytes(
        repo_root, manifest.semantic_rubric_path, "semantic rubric"
    )
    _require_hash(
        "semantic rubric",
        manifest.semantic_rubric_path,
        sha256_bytes(rubric_bytes),
        manifest.semantic_rubric_sha256,
    )

    mechanism = load_adjudication_mechanism(repo_root / manifest.adjudication_mechanism_path)
    if mechanism != build_adjudication_mechanism():
        raise Phase2SealViolation(
            "the committed adjudication mechanism no longer equals the frozen declaration"
        )
    if mechanism.grok_4_6_may_be_sole_adjudicator:
        raise Phase2SealViolation(
            "the frozen mechanism forbids a sole Grok adjudicator; the committed "
            "declaration permits one"
        )
    if not mechanism.identity_blind:
        raise Phase2SealViolation("the frozen mechanism must declare identity_blind")
    if mechanism.human_review_trigger != "ADJUDICATION_UNCERTAIN":
        raise Phase2SealViolation("the frozen human review trigger drifted")

    rubric = load_semantic_rubric(repo_root / manifest.semantic_rubric_path)
    if rubric != build_semantic_rubric():
        raise Phase2SealViolation(
            "the committed semantic rubric no longer equals the frozen declaration"
        )
    if not rubric.one_to_one_matching:
        raise Phase2SealViolation("the frozen rubric must require one-to-one matching")
    return sha256_bytes(mechanism_bytes), sha256_bytes(rubric_bytes)


def _load_adjudication_inputs(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    judge_bundle_path: Path,
    sdk_version: str | None,
    blob_reader: GitBlobReader | None,
    phase1_verifier: Phase1Verifier | None,
    require_no_output_manifest: bool,
) -> _AdjudicationInputs:
    """Verify every seal and build the 12 blind packets. Makes ZERO model calls."""
    reader = blob_reader if blob_reader is not None else git_blob_reader(repo_root)
    runner_artifacts = compute_runner_artifacts(repo_root, runner_commit_sha, reader)

    if require_no_output_manifest and (repo_root / manifest_relative()).exists():
        raise Phase2AlreadyFrozen(
            "this Phase-2 bundle is already frozen and may never call the adjudicator again"
        )

    manifest_bytes = _read_repo_bytes(repo_root, EXPERIMENT_MANIFEST_PATH, "experiment manifest")
    experiment_manifest_sha256 = sha256_bytes(manifest_bytes)
    experiment = load_experiment_manifest(repo_root / EXPERIMENT_MANIFEST_PATH)

    verifier = phase1_verifier if phase1_verifier is not None else default_phase1_verifier
    try:
        phase1 = verifier(repo_root=repo_root, blob_reader=blob_reader)
    except Phase2RunnerError:
        raise
    except Exception as exc:
        raise Phase2SealViolation(
            "the frozen Phase-1 output bundle does not verify: " + sanitize_error_text(str(exc))
        ) from exc
    if phase1.experiment_manifest_sha256 != experiment_manifest_sha256:
        raise Phase2SealViolation(
            "the Phase-1 bundle was produced against a different experiment manifest; "
            "expected="
            + experiment_manifest_sha256
            + " actual="
            + phase1.experiment_manifest_sha256
        )
    if phase1.runner_commit_sha != PHASE1_RUNNER_COMMIT:
        raise Phase2SealViolation(
            "the Phase-1 bundle was produced by runner commit "
            + phase1.runner_commit_sha
            + ", not the frozen "
            + PHASE1_RUNNER_COMMIT
        )
    if phase1.case_count != PHASE2_PRIMARY_CALL_COUNT:
        raise Phase2SealViolation(
            "the Phase-1 bundle covers " + str(phase1.case_count) + " cases, not 12"
        )

    mechanism_sha256, rubric_sha256 = _verify_frozen_protocol(repo_root, experiment)

    try:
        bundle: HiddenJudgeBundle = verify_revealed_judge_bundle(
            experiment, judge_bundle_path, repo_root
        )
        validate_first_suite_judge_bundle(bundle)
    except (ExperimentSealViolation, AdjudicationValidationError, ValidationError) as exc:
        raise Phase2SealViolation(
            "the revealed hidden judge does not match its precommitment: "
            + sanitize_error_text(str(exc))
        ) from exc

    holdouts = validate_first_suite_holdout_manifest(
        load_holdout_input_manifest(repo_root / experiment.holdout_input_manifest_path)
    )
    inputs = {case.case_id: case.input_path for case in holdouts.cases}
    judge_cases = {case.case_id: case for case in bundle.cases}

    # Adjudication order is the stable case order, never the Phase-1 execution order:
    # execution order is contestant-pairing information and must not reach Phase 2.
    case_sequence = tuple(sorted(inputs))

    packets: list[BlindAdjudicationPacket] = []
    blind_output_count = 0
    for case_id in case_sequence:
        eval_input = load_input((repo_root / inputs[case_id]).parent)
        system_a = load_blind_output(repo_root, case_id, "SYSTEM-A")
        system_b = load_blind_output(repo_root, case_id, "SYSTEM-B")
        blind_output_count += 2
        packet = build_blind_packet(
            eval_input=eval_input,
            judge_case=judge_cases[case_id],
            system_a_predictions=system_a.predictions,
            system_b_predictions=system_b.predictions,
        )
        require_no_identity_leak(packet)
        packets.append(packet)

    preflight_report = Phase2Preflight(
        experiment_manifest_sha256=experiment_manifest_sha256,
        phase1_output_commit=PHASE1_OUTPUT_COMMIT,
        phase1_runner_commit=PHASE1_RUNNER_COMMIT,
        phase1_bundle_sha256=phase1.bundle_sha256,
        hidden_judge_commitment_sha256=experiment.judge_commitment.bundle_sha256,
        adjudication_mechanism_sha256=mechanism_sha256,
        semantic_rubric_sha256=rubric_sha256,
        adjudicator_instruction_sha256=instruction_digest(),
        adjudication_runner_commit=runner_commit_sha,
        runner_artifacts=runner_artifacts,
        case_sequence=case_sequence,
        blind_output_count=blind_output_count,
        packet_digests=tuple(packet_digest(packet) for packet in packets),
        sdk_version=sdk_version or "",
    )
    return _AdjudicationInputs(preflight=preflight_report, packets=tuple(packets))


def preflight(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    judge_bundle_path: Path,
    sdk_version: str | None = None,
    blob_reader: GitBlobReader | None = None,
    phase1_verifier: Phase1Verifier | None = None,
) -> Phase2Preflight:
    """Verify every seal before adjudication. Makes ZERO model calls."""
    return _load_adjudication_inputs(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        judge_bundle_path=judge_bundle_path,
        sdk_version=sdk_version,
        blob_reader=blob_reader,
        phase1_verifier=phase1_verifier,
        require_no_output_manifest=True,
    ).preflight


# --------------------------------------------------------------------------- execution


def classify_exception(exc: BaseException) -> AdjudicationOutcome:
    """Conservative triage. Only a recognised transport condition is infrastructure."""
    for candidate in _exception_chain(exc):
        if isinstance(candidate, TimeoutError | ConnectionError):
            return AdjudicationOutcome.INFRASTRUCTURE_FAILURE
        name = type(candidate).__name__
        if name in {
            "APIConnectionError",
            "APITimeoutError",
            "InternalServerError",
            "RateLimitError",
        }:
            return AdjudicationOutcome.INFRASTRUCTURE_FAILURE
        status = getattr(candidate, "status_code", None)
        if isinstance(status, int) and (status == 429 or 500 <= status < 600):
            return AdjudicationOutcome.INFRASTRUCTURE_FAILURE
    return AdjudicationOutcome.EXECUTOR_FAILURE


def _exception_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    queue: list[BaseException] = [exc]
    while queue:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                queue.append(linked)


def _require_no_ambiguous_attempt(repo_root: Path) -> None:
    attempts = repo_root / PHASE2_ROOT / "attempts"
    if not attempts.exists():
        return
    started = {path.name.removesuffix("-started.json") for path in attempts.glob("*-started.json")}
    completed = {
        path.name.removesuffix("-completed.json") for path in attempts.glob("*-completed.json")
    }
    orphans = sorted(started - completed)
    if orphans:
        raise AmbiguousInFlightAdjudication(
            "STOP - AMBIGUOUS IN-FLIGHT ADJUDICATION: a started attempt has no completion "
            "marker, so whether a semantic judgment was produced is unknowable: "
            + ", ".join(orphans)
        )


def _parse_and_validate(
    packet: BlindAdjudicationPacket, output_text: str
) -> PrimaryCaseAdjudication:
    """Parse, then run the frozen deterministic validator on BOTH systems. No repair."""
    try:
        parsed = PrimaryCaseAdjudication.model_validate(json.loads(output_text))
    except (ValidationError, ValueError) as exc:
        raise Phase2StructuralFailure(
            "STOP - PRIMARY ADJUDICATION STRUCTURAL FAILURE: case "
            + packet.case_id
            + " returned an unparseable or schema-invalid judgment: "
            + sanitize_error_text(str(exc))
        ) from exc
    if parsed.case_id != packet.case_id:
        raise Phase2StructuralFailure(
            "STOP - PRIMARY ADJUDICATION STRUCTURAL FAILURE: judgment for "
            + parsed.case_id
            + " was returned for packet "
            + packet.case_id
        )
    judge_case = _judge_case_of(packet)
    for label, predictions, adjudication in (
        ("system_a", packet.system_a_predictions, parsed.system_a),
        ("system_b", packet.system_b_predictions, parsed.system_b),
    ):
        try:
            validate_system_adjudication(judge_case, predictions, adjudication)
        except AdjudicationValidationError as exc:
            raise Phase2StructuralFailure(
                "STOP - PRIMARY ADJUDICATION STRUCTURAL FAILURE: case "
                + packet.case_id
                + " "
                + label
                + " failed the frozen adjudication validator: "
                + sanitize_error_text(str(exc))
            ) from exc
    return parsed


def _judge_case_of(packet: BlindAdjudicationPacket) -> HiddenJudgeCase:
    """Reconstruct the judge case a packet was built from. No file is reopened."""
    return HiddenJudgeCase(case_id=packet.case_id, expected_concepts=packet.expected_concepts)


def run_phase2(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    judge_bundle_path: Path,
    adjudicator: Adjudicator,
    openai_sdk_version: str,
    resume: bool = False,
    blob_reader: GitBlobReader | None = None,
    phase1_verifier: Phase1Verifier | None = None,
    clock: Clock | None = None,
    execution_id_factory: ExecutionIdFactory | None = None,
    progress: Progress | None = None,
) -> Phase2OutputManifest:
    """Execute the 12 blind primary adjudications, one fresh call each."""
    now = clock if clock is not None else _utc_now
    next_id = execution_id_factory if execution_id_factory is not None else _uuid4
    announce = progress if progress is not None else _silent

    inputs = _load_adjudication_inputs(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        judge_bundle_path=judge_bundle_path,
        sdk_version=openai_sdk_version,
        blob_reader=blob_reader,
        phase1_verifier=phase1_verifier,
        require_no_output_manifest=True,
    )
    _require_no_ambiguous_attempt(repo_root)

    started_at = now()
    packets = {packet.case_id: packet for packet in inputs.packets}
    sequence = inputs.preflight.case_sequence
    total = len(sequence)

    calls: list[Phase2CallRecord] = []

    for position, case_id in enumerate(sequence, start=1):
        existing = _resume_record(repo_root, case_id) if resume else None
        if existing is not None:
            announce("case " + str(position) + "/" + str(total) + " primary adjudication resumed")
            calls.append(existing)
            continue

        announce("case " + str(position) + "/" + str(total) + " primary adjudication started")
        calls.append(
            _adjudicate_case(
                repo_root=repo_root,
                packet=packets[case_id],
                adjudicator=adjudicator,
                now=now,
                next_id=next_id,
            )
        )
        announce("case " + str(position) + "/" + str(total) + " primary adjudication frozen")

    # The ledger, not the loop, is the source of truth: a resumed run must carry every
    # attempt an earlier invocation already wrote, including its abandoned ones.
    attempts = _read_attempt_ledger(repo_root)
    infrastructure_failures = sum(
        1
        for attempt in attempts
        if attempt.outcome is AdjudicationOutcome.INFRASTRUCTURE_FAILURE
    )
    uncertain_item_count = sum(call.uncertain_item_count for call in calls)
    report = inputs.preflight
    manifest = Phase2OutputManifest(
        manifest_version=PHASE2_OUTPUT_MANIFEST_VERSION,
        experiment_manifest_sha256=report.experiment_manifest_sha256,
        phase1_output_commit=report.phase1_output_commit,
        phase1_runner_commit=report.phase1_runner_commit,
        phase1_bundle_sha256=report.phase1_bundle_sha256,
        hidden_judge_commitment_sha256=report.hidden_judge_commitment_sha256,
        adjudication_mechanism_sha256=report.adjudication_mechanism_sha256,
        semantic_rubric_sha256=report.semantic_rubric_sha256,
        adjudicator_instruction_sha256=report.adjudicator_instruction_sha256,
        adjudication_runner_commit=report.adjudication_runner_commit,
        runner_artifacts=report.runner_artifacts,
        provider=PHASE2_PROVIDER,
        model=PHASE2_MODEL,
        reasoning_effort=PHASE2_REASONING_EFFORT,
        api=PHASE2_API,
        store=PHASE2_STORE,
        tools_enabled=PHASE2_TOOLS_ENABLED,
        conversation_reuse=PHASE2_CONVERSATION_REUSE,
        reasoning_effort_frozen_before_first_call=True,
        calls_per_case=PHASE2_CALLS_PER_CASE,
        sdk_package=PHASE2_SDK_PACKAGE,
        openai_sdk_version=openai_sdk_version,
        infrastructure_retry_policy=INFRASTRUCTURE_RETRY_POLICY,
        structural_failure_policy=STRUCTURAL_FAILURE_POLICY,
        uncertainty_policy=UNCERTAINTY_POLICY,
        case_sequence=sequence,
        calls=tuple(calls),
        attempts=tuple(attempts),
        infrastructure_failures=infrastructure_failures,
        infrastructure_retries=sum(call.infrastructure_retry_count for call in calls),
        uncertain_item_count=uncertain_item_count,
        human_review_required=uncertain_item_count > 0,
        started_at=started_at,
        completed_at=now(),
    )
    write_phase2_evidence(repo_root, manifest_relative(), manifest)
    return manifest


def _adjudicate_case(
    *,
    repo_root: Path,
    packet: BlindAdjudicationPacket,
    adjudicator: Adjudicator,
    now: Clock,
    next_id: ExecutionIdFactory,
) -> Phase2CallRecord:
    """One case: at most one immediate infrastructure retry, exactly one judgment."""
    execution_ids: list[str] = []
    infrastructure_failures = 0

    for attempt_number in range(1, MAX_ATTEMPTS_PER_CASE + 1):
        execution_id = next_id()
        execution_ids.append(execution_id)
        attempt_started = now()
        create_adjudication_started(
            repo_root / attempt_started_relative(execution_id),
            AdjudicationAttemptStarted(
                execution_id=execution_id,
                case_id=packet.case_id,
                attempt_number=attempt_number,
                started_at=attempt_started,
            ),
        )
        try:
            response = adjudicator(packet)
        except BaseException as exc:  # noqa: BLE001 - every failure must be classified
            outcome = classify_exception(exc)
            record = AdjudicationAttemptRecord(
                execution_id=execution_id,
                case_id=packet.case_id,
                attempt_number=attempt_number,
                started_at=attempt_started,
                completed_at=now(),
                outcome=outcome,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            write_phase2_evidence(
                repo_root, attempt_completed_relative(execution_id), record
            )
            if outcome is not AdjudicationOutcome.INFRASTRUCTURE_FAILURE:
                raise Phase2Abort(
                    "STOP - ADJUDICATION EXECUTOR FAILURE on case "
                    + packet.case_id
                    + ": "
                    + sanitize_error_text(str(exc))
                ) from exc
            infrastructure_failures += 1
            if attempt_number == MAX_ATTEMPTS_PER_CASE:
                raise Phase2Paused(
                    "PAUSED_INFRASTRUCTURE: case "
                    + packet.case_id
                    + " suffered two infrastructure failures; resume may retry only this case"
                ) from exc
            continue

        try:
            result = _parse_and_validate(packet, response.output_text)
        except Phase2StructuralFailure:
            record = AdjudicationAttemptRecord(
                execution_id=execution_id,
                case_id=packet.case_id,
                attempt_number=attempt_number,
                started_at=attempt_started,
                completed_at=now(),
                outcome=AdjudicationOutcome.STRUCTURAL_FAILURE,
                provider_response_id=response.provider_response_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                wall_clock_ms=response.wall_clock_ms,
            )
            write_phase2_evidence(
                repo_root, attempt_completed_relative(execution_id), record
            )
            raise

        record = AdjudicationAttemptRecord(
            execution_id=execution_id,
            case_id=packet.case_id,
            attempt_number=attempt_number,
            started_at=attempt_started,
            completed_at=now(),
            outcome=AdjudicationOutcome.VALID_ADJUDICATION,
            provider_response_id=response.provider_response_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            wall_clock_ms=response.wall_clock_ms,
        )
        write_phase2_evidence(repo_root, attempt_completed_relative(execution_id), record)

        primary = write_phase2_evidence(repo_root, primary_relative(packet.case_id), result)
        call = Phase2CallRecord(
            case_id=packet.case_id,
            attempt_execution_ids=tuple(execution_ids),
            infrastructure_retry_count=infrastructure_failures,
            packet_sha256=packet_digest(packet),
            primary_result_path=primary.path,
            primary_result_sha256=primary.sha256,
            provider_response_id=response.provider_response_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            wall_clock_ms=response.wall_clock_ms,
            uncertain_item_count=count_uncertain_items(result),
        )
        write_phase2_evidence(repo_root, record_relative(packet.case_id), call)
        return call

    raise Phase2Abort(  # pragma: no cover - the loop always returns or raises
        "unreachable: adjudication attempt loop exhausted for " + packet.case_id
    )


def _resume_record(repo_root: Path, case_id: str) -> Phase2CallRecord | None:
    path = repo_root / record_relative(case_id)
    if not path.exists():
        return None
    try:
        return Phase2CallRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValidationError, ValueError) as exc:
        raise Phase2SealViolation(
            "malformed frozen Phase-2 record for " + case_id + ": " + sanitize_error_text(str(exc))
        ) from exc


def _read_attempt_ledger(repo_root: Path) -> list[AdjudicationAttemptRecord]:
    """Every completed attempt on disk, in a deterministic order. Append-only."""
    attempts = repo_root / PHASE2_ROOT / "attempts"
    records: list[AdjudicationAttemptRecord] = []
    for path in sorted(attempts.glob("*-completed.json")):
        try:
            records.append(
                AdjudicationAttemptRecord.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise Phase2SealViolation(
                "malformed completed attempt marker: " + path.name
            ) from exc
    return sorted(records, key=lambda record: (record.started_at, record.execution_id))


# --------------------------------------------------------------------------- verification


def verify_phase2_output(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    judge_bundle_path: Path,
    blob_reader: GitBlobReader | None = None,
    phase1_verifier: Phase1Verifier | None = None,
) -> Phase2OutputManifest:
    """Verify the frozen Phase-2 bundle end to end. Makes ZERO model calls.

    Packets are REBUILT from the visible holdouts, the recommitted judge and the blind
    tree, then compared to the recorded commitments. Every frozen judgment is re-run
    through the frozen deterministic validator.
    """
    inputs = _load_adjudication_inputs(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        judge_bundle_path=judge_bundle_path,
        sdk_version=None,
        blob_reader=blob_reader,
        phase1_verifier=phase1_verifier,
        require_no_output_manifest=False,
    )
    path = repo_root / manifest_relative()
    if not path.exists():
        raise Phase2SealViolation("no frozen Phase-2 output manifest to verify")
    try:
        manifest = Phase2OutputManifest.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (ValidationError, ValueError) as exc:
        raise Phase2SealViolation(
            "malformed Phase-2 output manifest: " + sanitize_error_text(str(exc))
        ) from exc

    report = inputs.preflight
    for field, expected, actual in (
        ("experiment_manifest_sha256", report.experiment_manifest_sha256,
         manifest.experiment_manifest_sha256),
        ("phase1_bundle_sha256", report.phase1_bundle_sha256, manifest.phase1_bundle_sha256),
        ("hidden_judge_commitment_sha256", report.hidden_judge_commitment_sha256,
         manifest.hidden_judge_commitment_sha256),
        ("adjudication_mechanism_sha256", report.adjudication_mechanism_sha256,
         manifest.adjudication_mechanism_sha256),
        ("semantic_rubric_sha256", report.semantic_rubric_sha256, manifest.semantic_rubric_sha256),
        ("adjudicator_instruction_sha256", report.adjudicator_instruction_sha256,
         manifest.adjudicator_instruction_sha256),
        ("adjudication_runner_commit", report.adjudication_runner_commit,
         manifest.adjudication_runner_commit),
        ("runner_artifacts", report.runner_artifacts, manifest.runner_artifacts),
        ("case_sequence", report.case_sequence, manifest.case_sequence),
    ):
        if expected != actual:
            raise Phase2SealViolation(
                "Phase-2 manifest drifted from the sealed inputs at " + field
            )

    packets = {packet.case_id: packet for packet in inputs.packets}
    digests = dict(zip(report.case_sequence, report.packet_digests, strict=True))
    calls = {call.case_id: call for call in manifest.calls}

    referenced: set[str] = set()
    for case_id in manifest.case_sequence:
        call = calls[case_id]
        if call.packet_sha256 != digests[case_id]:
            raise Phase2SealViolation(
                "the adjudication packet for " + case_id + " is no longer reproducible"
            )
        result = _verify_primary_result(repo_root, call, packets[case_id])
        if count_uncertain_items(result) != call.uncertain_item_count:
            raise Phase2SealViolation(
                "uncertain_item_count for " + case_id + " does not match its frozen judgment"
            )
        _verify_record_file(repo_root, call)
        referenced.update(call.attempt_execution_ids)

    _verify_attempts(repo_root, manifest, referenced)
    return manifest


def _verify_primary_result(
    repo_root: Path, call: Phase2CallRecord, packet: BlindAdjudicationPacket
) -> PrimaryCaseAdjudication:
    if call.primary_result_path != primary_relative(call.case_id):
        raise Phase2SealViolation(
            "the primary judgment for " + call.case_id + " is filed under the wrong path"
        )
    try:
        raw = (repo_root / call.primary_result_path).read_bytes()
    except OSError as exc:
        raise Phase2SealViolation(
            "missing frozen primary judgment for " + call.case_id
        ) from exc
    if sha256_bytes(raw) != call.primary_result_sha256:
        raise Phase2SealViolation(
            "the frozen primary judgment for " + call.case_id + " has been mutated"
        )
    try:
        result = PrimaryCaseAdjudication.model_validate(json.loads(raw.decode("utf-8")))
    except (ValidationError, ValueError) as exc:
        raise Phase2SealViolation(
            "malformed frozen primary judgment for " + call.case_id
        ) from exc
    judge_case = _judge_case_of(packet)
    for label, predictions, adjudication in (
        ("system_a", packet.system_a_predictions, result.system_a),
        ("system_b", packet.system_b_predictions, result.system_b),
    ):
        try:
            validate_system_adjudication(judge_case, predictions, adjudication)
        except AdjudicationValidationError as exc:
            raise Phase2SealViolation(
                "the frozen judgment for "
                + call.case_id
                + " "
                + label
                + " no longer passes the frozen validator: "
                + sanitize_error_text(str(exc))
            ) from exc
    return result


def _verify_record_file(repo_root: Path, call: Phase2CallRecord) -> None:
    path = repo_root / record_relative(call.case_id)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Phase2SealViolation("missing Phase-2 record for " + call.case_id) from exc
    if sha256_bytes(raw) != phase2_digest(call):
        raise Phase2SealViolation(
            "the Phase-2 record for " + call.case_id + " drifted from the manifest"
        )


def _verify_attempts(
    repo_root: Path, manifest: Phase2OutputManifest, referenced: set[str]
) -> None:
    attempts = repo_root / PHASE2_ROOT / "attempts"
    started = {path.name.removesuffix("-started.json") for path in attempts.glob("*-started.json")}
    completed = {
        path.name.removesuffix("-completed.json") for path in attempts.glob("*-completed.json")
    }
    if started != completed:
        raise Phase2SealViolation(
            "every started attempt requires a completion marker; unmatched: "
            + ", ".join(sorted(started ^ completed))
        )
    recorded = {attempt.execution_id for attempt in manifest.attempts}
    if not referenced <= recorded:
        raise Phase2SealViolation(
            "an attempt referenced by a call record is absent from the manifest"
        )
    if not recorded <= started:
        raise Phase2SealViolation(
            "a manifest attempt has no started marker on disk"
        )


# --------------------------------------------------------------------------- helpers


def _read_repo_bytes(repo_root: Path, relative: str, label: str) -> bytes:
    try:
        return (repo_root / relative).read_bytes()
    except OSError as exc:
        raise Phase2SealViolation("missing " + label + ": " + relative) from exc


def _require_hash(label: str, relative: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise Phase2SealViolation(
            label + " at " + relative + " no longer matches its sealed hash"
        )


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid4() -> str:
    return str(uuid.uuid4())


def _silent(_: str) -> None:
    return None


__all__ = [
    "EXPERIMENT_MANIFEST_PATH",
    "MAX_ATTEMPTS_PER_CASE",
    "PHASE1_OUTPUT_COMMIT",
    "PHASE1_RUNNER_COMMIT",
    "PHASE2_RUNNER_MODULE_PATHS",
    "Adjudicator",
    "AmbiguousInFlightAdjudication",
    "BlindPredictionIdentityLeak",
    "Phase1BundleSummary",
    "Phase1Verifier",
    "Phase2Abort",
    "Phase2AlreadyFrozen",
    "Phase2EvidenceError",
    "Phase2Paused",
    "Phase2Preflight",
    "Phase2RunnerError",
    "Phase2SealViolation",
    "Phase2StructuralFailure",
    "RawAdjudicationResponse",
    "classify_exception",
    "compute_runner_artifacts",
    "default_phase1_verifier",
    "git_blob_reader",
    "preflight",
    "run_phase2",
    "verify_phase2_output",
]

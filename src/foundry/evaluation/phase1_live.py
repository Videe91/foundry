"""Phase-1 live CLI for the Intent Intelligence comparative exam (Task 9K1-B).

    preflight   verify every public seal            ZERO model calls
    execute     run the 24 frozen contestant slots  the ONLY command that may call
    verify      re-verify the frozen output bundle  ZERO model calls

The API key is read from the environment and passed straight into the frozen
adapters. It is never printed, logged, hashed, serialized, or placed in error text.

This module reaches no judge: it imports no judge bundle, no expected concept, and
no adjudication model, and it computes no semantic metric and no winner.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, Literal

from foundry.adapters.intelligence.xai import XAIIntentIntelligence
from foundry.adapters.intelligence.xai_baseline import XAIBaselineIntelligence
from foundry.domain.common import FrozenModel
from foundry.evaluation.experiment_manifest import (
    MODEL,
    PROVIDER,
    REASONING_EFFORT,
    SDK_PACKAGE,
    TIMEOUT_SECONDS,
    load_contestant_freeze,
)
from foundry.evaluation.phase1_execution import (
    PHASE1_MODEL,
    PHASE1_OUTPUT_MANIFEST_FILENAME,
    PHASE1_PROVIDER,
    PHASE1_REASONING_EFFORT,
    PHASE1_ROOT,
    PHASE1_SDK_PACKAGE,
    AttemptOutcome,
    Phase1EvidenceError,
    Phase1OutputManifest,
)
from foundry.evaluation.phase1_runner import (
    AmbiguousInFlightAttempt,
    Phase1Abort,
    Phase1AlreadyFrozen,
    Phase1Paused,
    Phase1SealViolation,
    git_blob_reader,
    preflight,
    run_phase1,
    verify_phase1_output,
)

API_KEY_ENV = "XAI_API_KEY"
CONTESTANT_FREEZE_PATH = "evals/comparative/contestant-freeze.json"

ReasoningEffort = Literal["low", "medium", "high", "xhigh"]

FROZEN_PROVIDER: Final[Literal["xAI"]] = PHASE1_PROVIDER
FROZEN_MODEL: Final[Literal["grok-4.6"]] = PHASE1_MODEL
FROZEN_REASONING_EFFORT: Final[ReasoningEffort] = PHASE1_REASONING_EFFORT
FROZEN_TIMEOUT_SECONDS: Final[int] = 3600
FROZEN_SDK_PACKAGE: Final[Literal["xai-sdk"]] = PHASE1_SDK_PACKAGE

EXIT_OK = 0
EXIT_SEAL = 2
EXIT_PAUSED = 3
EXIT_ABORT = 4
EXIT_AMBIGUOUS = 5
EXIT_MISSING_KEY = 6
EXIT_FROZEN = 7

Out = Callable[[str], None]


class ContestantConfig(FrozenModel):
    """The declared, verified contestant configuration. Never a silent default."""

    model: Literal["grok-4.6"]
    reasoning_effort: ReasoningEffort
    timeout_seconds: int


def frozen_contestant_config(repo_root: Path) -> ContestantConfig:
    """Read the committed freeze and assert it equals the frozen expected values."""
    for field, local, sealed in (
        ("provider", FROZEN_PROVIDER, PROVIDER),
        ("model", FROZEN_MODEL, MODEL),
        ("reasoning_effort", FROZEN_REASONING_EFFORT, REASONING_EFFORT),
        ("timeout_seconds", FROZEN_TIMEOUT_SECONDS, TIMEOUT_SECONDS),
        ("sdk_package", FROZEN_SDK_PACKAGE, SDK_PACKAGE),
    ):
        if local != sealed:
            raise ValueError(
                "CONTESTANT IDENTITY DRIFT: "
                + field
                + " sealed="
                + repr(sealed)
                + " live="
                + repr(local)
            )
    manifest = load_contestant_freeze(repo_root / CONTESTANT_FREEZE_PATH)
    expected: tuple[tuple[str, object], ...] = (
        ("provider", FROZEN_PROVIDER),
        ("model", FROZEN_MODEL),
        ("reasoning_effort", FROZEN_REASONING_EFFORT),
        ("timeout_seconds", FROZEN_TIMEOUT_SECONDS),
        ("sdk_package", FROZEN_SDK_PACKAGE),
        ("tools_enabled", False),
        ("research_enabled", False),
        ("persistent_conversation", False),
        ("sdk_retries_enabled", False),
        ("semantic_retries_enabled", False),
    )
    for label, contestant in (
        ("contestant_a", manifest.contestant_a),
        ("contestant_b", manifest.contestant_b),
    ):
        for field, value in expected:
            actual = getattr(contestant, field)
            if actual != value:
                raise ValueError(
                    "CONTESTANT CONFIGURATION DRIFT: "
                    + label
                    + "."
                    + field
                    + " expected="
                    + repr(value)
                    + " actual="
                    + repr(actual)
                )
    return ContestantConfig(
        model=FROZEN_MODEL,
        reasoning_effort=FROZEN_REASONING_EFFORT,
        timeout_seconds=FROZEN_TIMEOUT_SECONDS,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foundry.evaluation.phase1_live")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "execute", "verify"):
        child = sub.add_parser(name)
        child.add_argument("--runner-commit", required=True)
        child.add_argument("--repo-root", default=None)
        if name == "execute":
            child.add_argument("--resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, *, out: Out = print) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root) if args.repo_root else Path.cwd()
    try:
        if args.command == "preflight":
            return run_preflight(
                repo_root=repo_root, runner_commit_sha=args.runner_commit, out=out
            )
        if args.command == "verify":
            return run_verify(
                repo_root=repo_root, runner_commit_sha=args.runner_commit, out=out
            )
        return run_execute(
            repo_root=repo_root,
            runner_commit_sha=args.runner_commit,
            resume=bool(args.resume),
            env=os.environ,
            out=out,
        )
    except Phase1AlreadyFrozen as exc:
        out("STOP - PHASE1 OUTPUT ALREADY FROZEN: " + _safe(str(exc)))
        return EXIT_FROZEN
    except AmbiguousInFlightAttempt as exc:
        out(_safe(str(exc)))
        return EXIT_AMBIGUOUS
    except Phase1Paused as exc:
        out("PAUSED_INFRASTRUCTURE: " + _safe(str(exc)))
        return EXIT_PAUSED
    except Phase1Abort as exc:
        out("STOP 9K1 - " + exc.outcome.value + ": " + _safe(str(exc)))
        return EXIT_ABORT
    except (Phase1SealViolation, Phase1EvidenceError, ValueError) as exc:
        out("STOP - " + _safe(str(exc)))
        return EXIT_SEAL


def run_preflight(*, repo_root: Path, runner_commit_sha: str, out: Out) -> int:
    report = preflight(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        blob_reader=git_blob_reader(repo_root),
    )
    frozen_contestant_config(repo_root)
    out("sealed cases: " + str(len(report.case_sequence)))
    out("contestant slots: " + str(report.total_contestant_slots))
    out("runner commit: " + report.runner_commit_sha)
    for artifact in report.runner_artifacts:
        out("runner artifact: " + artifact.path + " " + artifact.sha256)
    out("experiment manifest sha256: " + report.experiment_manifest_sha256)
    out("9J3 audit sha256: " + report.pre_exam_audit_sha256)
    out("PHASE1 PREFLIGHT PASS")
    return EXIT_OK


def run_verify(*, repo_root: Path, runner_commit_sha: str, out: Out) -> int:
    manifest = verify_phase1_output(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        blob_reader=git_blob_reader(repo_root),
    )
    _report_safe_aggregates(manifest, out)
    out("PHASE1 OUTPUT BUNDLE VERIFIED")
    return EXIT_OK


def run_execute(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    resume: bool,
    env: Mapping[str, str],
    out: Out,
) -> int:
    """The ONLY command permitted to instantiate a contestant."""
    frozen = repo_root / PHASE1_ROOT / PHASE1_OUTPUT_MANIFEST_FILENAME
    if frozen.exists():
        raise Phase1AlreadyFrozen(
            "this Phase-1 bundle is already frozen and may never call a contestant again"
        )

    report = preflight(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        blob_reader=git_blob_reader(repo_root),
    )
    config = frozen_contestant_config(repo_root)

    api_key = env.get(API_KEY_ENV, "")
    if not api_key:
        out("STOP - XAI_API_KEY NOT AVAILABLE IN ENVIRONMENT")
        return EXIT_MISSING_KEY

    foundry = XAIIntentIntelligence(
        api_key=api_key,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
        timeout_seconds=config.timeout_seconds,
    )
    baseline = XAIBaselineIntelligence(
        api_key=api_key,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
        timeout_seconds=config.timeout_seconds,
    )

    out("LIVE COMPARATIVE EXECUTION STARTING")
    out("sealed cases: " + str(len(report.case_sequence)))
    manifest = run_phase1(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        foundry=foundry,
        baseline=baseline,
        resume=resume,
        blob_reader=git_blob_reader(repo_root),
        progress=out,
    )
    out("PHASE1 EXECUTION COMPLETE")
    _report_safe_aggregates(manifest, out)
    return EXIT_OK


def _report_safe_aggregates(manifest: Phase1OutputManifest, out: Out) -> None:
    """Combined aggregates only. No per-system split, no semantic content, no winner."""
    out("cases completed: " + str(len(manifest.case_sequence)))
    out("terminal contestant slots: " + str(manifest.total_contestant_slots))
    out("valid results (combined): " + str(manifest.valid_results))
    out("structural failures (combined): " + str(manifest.structural_failures))
    out("infrastructure failure attempts (combined): " + str(manifest.infrastructure_failures))
    out("infrastructure retries (combined): " + str(manifest.infrastructure_retries))
    out("total provider attempts: " + str(len(manifest.attempts)))
    out("combined input tokens: " + str(_total(manifest, "input_tokens")))
    out("combined output tokens: " + str(_total(manifest, "output_tokens")))
    out("combined cost usd: " + format(_total_cost(manifest), ".6f"))
    out("combined wall clock ms: " + str(_total(manifest, "wall_clock_ms")))


def _total(manifest: Phase1OutputManifest, field: str) -> int:
    return sum(int(getattr(item, field) or 0) for item in manifest.executions)


def _total_cost(manifest: Phase1OutputManifest) -> float:
    return sum(float(item.cost_usd or 0.0) for item in manifest.executions)


def _safe(message: str) -> str:
    """Never let a credential reach the terminal through an exception string."""
    from foundry.evaluation.phase1_execution import sanitize_error_text

    return sanitize_error_text(message)


__all__ = [
    "API_KEY_ENV",
    "EXIT_ABORT",
    "EXIT_AMBIGUOUS",
    "EXIT_FROZEN",
    "EXIT_MISSING_KEY",
    "EXIT_OK",
    "EXIT_PAUSED",
    "EXIT_SEAL",
    "FROZEN_MODEL",
    "FROZEN_PROVIDER",
    "FROZEN_REASONING_EFFORT",
    "FROZEN_SDK_PACKAGE",
    "FROZEN_TIMEOUT_SECONDS",
    "AttemptOutcome",
    "ContestantConfig",
    "build_parser",
    "frozen_contestant_config",
    "main",
    "run_execute",
    "run_preflight",
    "run_verify",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

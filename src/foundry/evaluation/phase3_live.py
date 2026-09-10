"""Phase-3 comparative scoring CLI for the Intent Intelligence exam (Task 9K3).

    preflight-blind   verify the frozen scorer and evidence   NEVER opens the mapping
    reveal-and-score  the ONE-WAY intentional identity reveal  writes two artifacts
    verify            recompute and compare, byte for byte     never rewrites

There are ZERO model calls in Phase 3. This module imports no provider SDK, reads no
API key, and opens no network path. `preflight-blind` prints no contestant name, no
blind label, no case ID, and no metric; only `reveal-and-score` and `verify` may print
named aggregates, and only after the reveal has intentionally happened.

Per-case judgments, expected concepts, predictions and rationales are never printed by
any command.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from foundry.evaluation.phase2_adjudication import sanitize_error_text
from foundry.evaluation.phase3_runner import (
    REPORT_FILENAME,
    RESULT_FILENAME,
    RESULTS_ROOT,
    IdentityMappingIntegrityFailure,
    Phase3AlreadyFrozen,
    Phase3BlindPreflight,
    Phase3HumanReviewRequired,
    Phase3RunnerError,
    Phase3SealViolation,
    blind_preflight,
    format_cost,
    format_ratio,
    format_seconds,
    git_blob_reader,
    reveal_and_score,
    verify_result,
)
from foundry.evaluation.phase3_scoring import ComparativeResult

DEFAULT_JUDGE_BUNDLE_PATH = "../.foundry-sealed-evals/intent-intelligence-v1/hidden-judge.json"

COMMANDS = ("preflight-blind", "reveal-and-score", "verify")

EXIT_OK = 0
EXIT_SEAL = 2
EXIT_HUMAN_REVIEW = 3
EXIT_FROZEN = 7
EXIT_IDENTITY = 9

Out = Callable[[str], None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foundry.evaluation.phase3_live")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        child = sub.add_parser(name)
        child.add_argument("--scorer-commit", required=True)
        child.add_argument("--repo-root", default=None)
        child.add_argument("--judge-bundle", default=None)
    return parser


def main(argv: Sequence[str] | None = None, *, out: Out = print) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root) if args.repo_root else Path.cwd()
    judge_bundle_path = (
        Path(args.judge_bundle)
        if args.judge_bundle
        else (repo_root / DEFAULT_JUDGE_BUNDLE_PATH).resolve()
    )
    try:
        if args.command == "preflight-blind":
            return run_preflight_blind(
                repo_root=repo_root,
                scorer_commit_sha=args.scorer_commit,
                judge_bundle_path=judge_bundle_path,
                out=out,
            )
        if args.command == "verify":
            return run_verify(
                repo_root=repo_root,
                scorer_commit_sha=args.scorer_commit,
                judge_bundle_path=judge_bundle_path,
                out=out,
            )
        return run_reveal_and_score(
            repo_root=repo_root,
            scorer_commit_sha=args.scorer_commit,
            judge_bundle_path=judge_bundle_path,
            out=out,
        )
    except Phase3AlreadyFrozen as exc:
        out("STOP - PHASE3 COMPARATIVE RESULT ALREADY FROZEN: " + _safe(str(exc)))
        return EXIT_FROZEN
    except Phase3HumanReviewRequired as exc:
        out(_safe(str(exc)))
        return EXIT_HUMAN_REVIEW
    except IdentityMappingIntegrityFailure as exc:
        out(_safe(str(exc)))
        out("Return to the architect. The result was NOT written.")
        return EXIT_IDENTITY
    except (Phase3SealViolation, Phase3RunnerError, ValueError) as exc:
        out("STOP - " + _safe(str(exc)))
        return EXIT_SEAL


def run_preflight_blind(
    *, repo_root: Path, scorer_commit_sha: str, judge_bundle_path: Path, out: Out
) -> int:
    """Safe pre-reveal report. Prints no contestant, no blind label, no case, no metric."""
    report = blind_preflight(
        repo_root=repo_root,
        scorer_commit_sha=scorer_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=git_blob_reader(repo_root),
    )
    _report_commitments(report, out)
    out("prior comparative result: none")
    out("identity mapping accessed: false")
    out("model calls: 0")
    out("PHASE3 BLIND PREFLIGHT PASS")
    return EXIT_OK


def run_reveal_and_score(
    *, repo_root: Path, scorer_commit_sha: str, judge_bundle_path: Path, out: Out
) -> int:
    """THE INTENTIONAL REVEAL. Preflight runs first; the mapping opens exactly once."""
    report = blind_preflight(
        repo_root=repo_root,
        scorer_commit_sha=scorer_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=git_blob_reader(repo_root),
    )
    _report_commitments(report, out)
    out("PHASE3 BLIND PREFLIGHT PASS")
    out("SCORER FROZEN - IDENTITY REVEAL AUTHORIZED")

    result = reveal_and_score(
        repo_root=repo_root,
        scorer_commit_sha=scorer_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=git_blob_reader(repo_root),
    )
    out("wrote " + RESULTS_ROOT + "/" + RESULT_FILENAME)
    out("wrote " + RESULTS_ROOT + "/" + REPORT_FILENAME)
    _report_named_metrics(result, out)
    out("PHASE3 COMPARATIVE RESULT FROZEN")
    return EXIT_OK


def run_verify(
    *, repo_root: Path, scorer_commit_sha: str, judge_bundle_path: Path, out: Out
) -> int:
    result = verify_result(
        repo_root=repo_root,
        scorer_commit_sha=scorer_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=git_blob_reader(repo_root),
    )
    _report_named_metrics(result, out)
    out("model calls: 0")
    out("PHASE3 COMPARATIVE RESULT VERIFIED")
    return EXIT_OK


def _report_commitments(report: Phase3BlindPreflight, out: Out) -> None:
    """Commitments only. A hash reveals nothing about who produced what."""
    out("scorer commit: " + report.scorer_commit_sha)
    for artifact in report.scorer_artifacts:
        out("scorer artifact: " + artifact.path + " " + artifact.sha256)
    out("experiment manifest sha256: " + report.experiment_manifest_sha256)
    out("hidden judge commitment sha256: " + report.hidden_judge_commitment_sha256)
    out("phase1 output commit: " + report.phase1_output_commit)
    out("phase1 runner commit: " + report.phase1_runner_commit)
    out("phase1 bundle sha256: " + report.phase1_bundle_sha256)
    out("phase2 output commit: " + report.phase2_output_commit)
    out("phase2 adjudicator commit: " + report.phase2_adjudicator_commit)
    out("phase2 bundle sha256: " + report.phase2_bundle_sha256)
    out("sealed cases: " + str(len(report.case_sequence)))
    out("adjudication uncertain items: " + str(report.uncertain_item_count))
    out("human review required: " + str(report.human_review_required).lower())


def _report_named_metrics(result: ComparativeResult, out: Out) -> None:
    """Named aggregates ONLY. No per-case judgment, no concept, no prediction."""
    foundry = result.foundry
    baseline = result.baseline
    out("cases scored: " + str(result.case_count))

    for label, attribute in (
        ("critical semantic recall", "critical_semantic_recall"),
        ("overall semantic recall", "overall_semantic_recall"),
        ("useful semantic precision", "useful_semantic_precision"),
        ("GapKind accuracy", "gap_kind_accuracy"),
        ("unsupported rate", "unsupported_rate"),
        ("redundancy rate", "redundancy_rate"),
    ):
        out("Foundry " + label + ": " + format_ratio(getattr(foundry.semantic, attribute)))
        out("Baseline " + label + ": " + format_ratio(getattr(baseline.semantic, attribute)))

    out(
        "Foundry bundled prediction count: "
        + str(foundry.semantic.bundled_concept_prediction_count)
    )
    out(
        "Baseline bundled prediction count: "
        + str(baseline.semantic.bundled_concept_prediction_count)
    )

    out(
        "Foundry total safety violation occurrences: "
        + str(foundry.safety.total_safety_violation_occurrences)
    )
    out(
        "Baseline total safety violation occurrences: "
        + str(baseline.safety.total_safety_violation_occurrences)
    )
    out("Foundry serious safety violations: " + str(foundry.safety.serious_safety_violations))
    out("Baseline serious safety violations: " + str(baseline.safety.serious_safety_violations))

    for label, attribute in (
        ("exact critical recall", "exact_critical_recall"),
        ("exact overall recall", "exact_overall_recall"),
        ("exact precision", "exact_precision"),
    ):
        out("Foundry " + label + ": " + format_ratio(getattr(foundry.exact, attribute)))
        out("Baseline " + label + ": " + format_ratio(getattr(baseline.exact, attribute)))

    out("Foundry input tokens: " + str(foundry.economics.input_tokens))
    out("Baseline input tokens: " + str(baseline.economics.input_tokens))
    out("Foundry output tokens: " + str(foundry.economics.output_tokens))
    out("Baseline output tokens: " + str(baseline.economics.output_tokens))
    out("Foundry cost usd: " + format_cost(foundry.economics.cost_usd))
    out("Baseline cost usd: " + format_cost(baseline.economics.cost_usd))
    out(
        "Foundry total wall clock s: "
        + format_seconds(foundry.economics.total_wall_clock_ms)
    )
    out(
        "Baseline total wall clock s: "
        + format_seconds(baseline.economics.total_wall_clock_ms)
    )
    out(
        "Foundry mean wall clock s per terminal slot: "
        + format_seconds(foundry.economics.mean_wall_clock_ms_per_terminal_slot)
    )
    out(
        "Baseline mean wall clock s per terminal slot: "
        + format_seconds(baseline.economics.mean_wall_clock_ms_per_terminal_slot)
    )

    out("DIRECTIONAL RULE:")
    out(result.directional_rule.conclusion.value)


def _safe(message: str) -> str:
    """Nothing sensitive may reach the terminal through an exception string."""
    return sanitize_error_text(message)


__all__ = [
    "COMMANDS",
    "DEFAULT_JUDGE_BUNDLE_PATH",
    "EXIT_FROZEN",
    "EXIT_HUMAN_REVIEW",
    "EXIT_IDENTITY",
    "EXIT_OK",
    "EXIT_SEAL",
    "build_parser",
    "main",
    "run_preflight_blind",
    "run_reveal_and_score",
    "run_verify",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

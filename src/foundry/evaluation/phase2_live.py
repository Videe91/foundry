"""Phase-2 live adjudication CLI for the Intent Intelligence exam (Task 9K2-B).

    preflight   verify every seal                       ZERO OpenAI calls
    adjudicate  run the 12 blind primary adjudications  the ONLY command that may call
    verify      re-verify the frozen Phase-2 bundle     ZERO OpenAI calls

The API key is read from the environment and passed straight into the client. It is
never printed, logged, hashed, serialized, or placed in error text.

The OpenAI SDK is a RUNTIME dependency of this evaluation, not a Foundry production
dependency. It is imported lazily, inside the adjudication execution path only, so
importing this module (or the whole `foundry` package) never requires it.

This CLI prints only safe progress and safe aggregates. It never prints a prediction,
an expected concept, a rationale, a match count, a per-system score, or a winner.
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from foundry.evaluation.comparative_protocol import BlindAdjudicationPacket
from foundry.evaluation.phase2_adjudication import (
    ADJUDICATOR_INSTRUCTION,
    PHASE2_API,
    PHASE2_MODEL,
    PHASE2_PROVIDER,
    PHASE2_REASONING_EFFORT,
    PHASE2_SDK_PACKAGE,
    PHASE2_STORE,
    PHASE2_TOOLS_ENABLED,
    BlindPredictionIdentityLeak,
    Phase2EvidenceError,
    Phase2OutputManifest,
    PrimaryCaseAdjudication,
    phase2_canonical_json,
    sanitize_error_text,
    strict_json_schema,
)
from foundry.evaluation.phase2_runner import (
    AmbiguousInFlightAdjudication,
    Phase2Abort,
    Phase2AlreadyFrozen,
    Phase2Paused,
    Phase2SealViolation,
    Phase2StructuralFailure,
    RawAdjudicationResponse,
    git_blob_reader,
    preflight,
    run_phase2,
    verify_phase2_output,
)

API_KEY_ENV = "OPENAI_API_KEY"

DEFAULT_JUDGE_BUNDLE_PATH = "../.foundry-sealed-evals/intent-intelligence-v1/hidden-judge.json"

STRUCTURED_OUTPUT_NAME = "primary_case_adjudication"

EXIT_OK = 0
EXIT_SEAL = 2
EXIT_PAUSED = 3
EXIT_ABORT = 4
EXIT_AMBIGUOUS = 5
EXIT_MISSING_KEY = 6
EXIT_FROZEN = 7
EXIT_STRUCTURAL = 8
EXIT_LEAK = 9

Out = Callable[[str], None]


# --------------------------------------------------------------------------- provider


def _load_openai_client_class() -> Any:
    """Resolve the SDK client at call time, inside the adjudication path only.

    The import is dynamic on purpose. `openai` is a Task 9K2 evaluation RUNTIME
    dependency supplied by `uv run --with \'openai>=2,<3\'`, never a Foundry production
    dependency, so importing this module -- or the whole `foundry` package -- must not
    require it to be installed.
    """
    import importlib

    try:
        module = importlib.import_module("openai")
    except ImportError as exc:
        raise Phase2SealViolation(
            "the OpenAI runtime dependency is not installed; run under "
            "`uv run --with \'openai>=2,<3\'`"
        ) from exc
    return module.OpenAI


def resolve_openai_sdk_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(PHASE2_SDK_PACKAGE)
    except PackageNotFoundError as exc:  # pragma: no cover - the CLI requires the SDK
        raise Phase2SealViolation(
            "the OpenAI runtime dependency is not installed; run under "
            "`uv run --with 'openai>=2,<3'`"
        ) from exc


def packet_payload(packet: BlindAdjudicationPacket) -> str:
    """The exact bytes the adjudicator sees. Canonical, blind, and nothing else."""
    return phase2_canonical_json(packet)


def build_openai_adjudicator(
    *, api_key: str
) -> Callable[[BlindAdjudicationPacket], RawAdjudicationResponse]:
    """One fresh Responses call per packet. No tools, no store, no conversation reuse."""
    client_class = _load_openai_client_class()
    client = client_class(api_key=api_key)
    schema = strict_json_schema(PrimaryCaseAdjudication)

    def adjudicate(packet: BlindAdjudicationPacket) -> RawAdjudicationResponse:
        started = time.monotonic()
        response = client.responses.create(
            model=PHASE2_MODEL,
            reasoning={"effort": PHASE2_REASONING_EFFORT},
            store=PHASE2_STORE,
            input=[
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": ADJUDICATOR_INSTRUCTION}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": packet_payload(packet)}],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": STRUCTURED_OUTPUT_NAME,
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(response, "usage", None)
        return RawAdjudicationResponse(
            output_text=_extract_output_text(response),
            provider_response_id=getattr(response, "id", None),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            wall_clock_ms=elapsed_ms,
        )

    return adjudicate


def _extract_output_text(response: Any) -> str:
    """Read the structured payload without parsing, repairing, or reshaping it."""
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    chunks: list[str] = []
    for item in getattr(response, "output", ()) or ():
        for content in getattr(item, "content", ()) or ():
            value = getattr(content, "text", None)
            if isinstance(value, str):
                chunks.append(value)
    joined = "".join(chunks)
    if not joined.strip():
        raise Phase2StructuralFailure(
            "STOP - PRIMARY ADJUDICATION STRUCTURAL FAILURE: the provider returned no "
            "structured output"
        )
    return joined


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foundry.evaluation.phase2_live")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "adjudicate", "verify"):
        child = sub.add_parser(name)
        child.add_argument("--runner-commit", required=True)
        child.add_argument("--repo-root", default=None)
        child.add_argument("--judge-bundle", default=None)
        if name == "adjudicate":
            child.add_argument("--resume", action="store_true")
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
        if args.command == "preflight":
            return run_preflight(
                repo_root=repo_root,
                runner_commit_sha=args.runner_commit,
                judge_bundle_path=judge_bundle_path,
                out=out,
            )
        if args.command == "verify":
            return run_verify(
                repo_root=repo_root,
                runner_commit_sha=args.runner_commit,
                judge_bundle_path=judge_bundle_path,
                out=out,
            )
        return run_adjudicate(
            repo_root=repo_root,
            runner_commit_sha=args.runner_commit,
            judge_bundle_path=judge_bundle_path,
            resume=bool(args.resume),
            env=os.environ,
            out=out,
        )
    except BlindPredictionIdentityLeak as exc:
        out(_safe(str(exc)))
        out("Return to the architect. Adjudication was NOT performed.")
        return EXIT_LEAK
    except Phase2AlreadyFrozen as exc:
        out("STOP - PHASE2 OUTPUT ALREADY FROZEN: " + _safe(str(exc)))
        return EXIT_FROZEN
    except AmbiguousInFlightAdjudication as exc:
        out(_safe(str(exc)))
        return EXIT_AMBIGUOUS
    except Phase2Paused as exc:
        out("PAUSED_INFRASTRUCTURE: " + _safe(str(exc)))
        return EXIT_PAUSED
    except Phase2StructuralFailure as exc:
        out(_safe(str(exc)))
        return EXIT_STRUCTURAL
    except Phase2Abort as exc:
        out(_safe(str(exc)))
        return EXIT_ABORT
    except (Phase2SealViolation, Phase2EvidenceError, ValueError) as exc:
        out("STOP - " + _safe(str(exc)))
        return EXIT_SEAL


def run_preflight(
    *, repo_root: Path, runner_commit_sha: str, judge_bundle_path: Path, out: Out
) -> int:
    report = preflight(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=git_blob_reader(repo_root),
    )
    _report_frozen_contract(out)
    out("sealed cases: " + str(len(report.case_sequence)))
    out("blind outputs: " + str(report.blind_output_count))
    out("adjudication runner commit: " + report.adjudication_runner_commit)
    out("experiment manifest sha256: " + report.experiment_manifest_sha256)
    out("phase1 bundle sha256: " + report.phase1_bundle_sha256)
    out("hidden judge commitment sha256: " + report.hidden_judge_commitment_sha256)
    out("adjudicator instruction sha256: " + report.adjudicator_instruction_sha256)
    out("identity-leak scan: PASS")
    out("prior phase2 output: none")
    out("openai calls made: 0")
    out("PHASE2 PREFLIGHT PASS")
    return EXIT_OK


def run_verify(
    *, repo_root: Path, runner_commit_sha: str, judge_bundle_path: Path, out: Out
) -> int:
    manifest = verify_phase2_output(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=git_blob_reader(repo_root),
    )
    _report_safe_aggregates(manifest, out)
    out("PHASE2 ADJUDICATION BUNDLE VERIFIED")
    return EXIT_OK


def run_adjudicate(
    *,
    repo_root: Path,
    runner_commit_sha: str,
    judge_bundle_path: Path,
    resume: bool,
    env: Mapping[str, str],
    out: Out,
) -> int:
    """The ONLY command permitted to construct an OpenAI client."""
    report = preflight(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        judge_bundle_path=judge_bundle_path,
        blob_reader=git_blob_reader(repo_root),
    )

    api_key = env.get(API_KEY_ENV, "")
    if not api_key:
        out("STOP - OPENAI_API_KEY NOT AVAILABLE IN ENVIRONMENT")
        return EXIT_MISSING_KEY

    sdk_version = resolve_openai_sdk_version()
    out("LIVE BLIND ADJUDICATION STARTING")
    _report_frozen_contract(out)
    out("openai sdk version: " + sdk_version)
    out("sealed cases: " + str(len(report.case_sequence)))

    manifest = run_phase2(
        repo_root=repo_root,
        runner_commit_sha=runner_commit_sha,
        judge_bundle_path=judge_bundle_path,
        adjudicator=build_openai_adjudicator(api_key=api_key),
        openai_sdk_version=sdk_version,
        resume=resume,
        blob_reader=git_blob_reader(repo_root),
        progress=out,
    )
    out("PHASE2 PRIMARY ADJUDICATION COMPLETE")
    _report_safe_aggregates(manifest, out)
    if manifest.human_review_required:
        out("9K2 PRIMARY MODEL PHASE FROZEN")
        out("INDEPENDENT BLIND HUMAN REVIEW REQUIRED")
    else:
        out("9K2 PRIMARY ADJUDICATION COMPLETE")
    return EXIT_OK


def _report_frozen_contract(out: Out) -> None:
    out("provider: " + PHASE2_PROVIDER)
    out("model: " + PHASE2_MODEL)
    out("reasoning effort: " + PHASE2_REASONING_EFFORT)
    out("api: " + PHASE2_API)
    out("store: " + str(PHASE2_STORE))
    out("tools enabled: " + str(PHASE2_TOOLS_ENABLED))


def _report_safe_aggregates(manifest: Phase2OutputManifest, out: Out) -> None:
    """Safe metadata only. No judgment content, no per-system split, no winner."""
    out("cases adjudicated: " + str(len(manifest.calls)))
    out("primary calls attempted: " + str(len(manifest.attempts)))
    out("infrastructure failures: " + str(manifest.infrastructure_failures))
    out("infrastructure retries: " + str(manifest.infrastructure_retries))
    out("combined input tokens: " + str(_total(manifest, "input_tokens")))
    out("combined output tokens: " + str(_total(manifest, "output_tokens")))
    out("combined wall clock ms: " + str(_total(manifest, "wall_clock_ms")))
    out("adjudication uncertain items: " + str(manifest.uncertain_item_count))
    out("human review required: " + str(manifest.human_review_required))


def _total(manifest: Phase2OutputManifest, field: str) -> int:
    return sum(int(getattr(call, field) or 0) for call in manifest.calls)


def _safe(message: str) -> str:
    """Never let a credential reach the terminal through an exception string."""
    return sanitize_error_text(message)


__all__ = [
    "API_KEY_ENV",
    "DEFAULT_JUDGE_BUNDLE_PATH",
    "EXIT_ABORT",
    "EXIT_AMBIGUOUS",
    "EXIT_FROZEN",
    "EXIT_LEAK",
    "EXIT_MISSING_KEY",
    "EXIT_OK",
    "EXIT_PAUSED",
    "EXIT_SEAL",
    "EXIT_STRUCTURAL",
    "STRUCTURED_OUTPUT_NAME",
    "build_openai_adjudicator",
    "build_parser",
    "main",
    "packet_payload",
    "resolve_openai_sdk_version",
    "run_adjudicate",
    "run_preflight",
    "run_verify",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

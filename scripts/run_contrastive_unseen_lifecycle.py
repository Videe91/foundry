"""9P2 unseen-lifecycle entry point: preflight, then (only if authorized and passed)
one live run (spec §14.1, §15, §16, §17.2-§17.4; plan T7; clarification C2; Controller
Ruling 7).

    uv run python scripts/run_contrastive_unseen_lifecycle.py \\
        (--preflight-only | --live) --frozen-sha <40 hex> \\
        --out docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1

The preflight-before-construction law. In every mode the twenty §15 gates are
evaluated over the sealed ``manifest.json``/``expectations.json`` bytes, the six real
request-path sources (C2: a missing one is passed as missing so gate 16 fails; nothing
is fabricated), the §14 leakage gate, injected git facts and injected regression
commands -- BEFORE ``XAI_API_KEY`` is read and BEFORE any reasoner exists.

``--preflight-only`` prints the full preflight document (the exact shape
``write_preflight`` writes) to stdout, writes nothing, reads no key, constructs
nothing, and exits 3 if any gate failed, else 0.

``--live`` (1) requires both seal files, (2) refuses if any §17.2 raw artifact exists
(a preserved failed preflight included), (3) evaluates the gates, (4) writes
``preflight.json`` exactly once, (5) stops with ``ABORTED_PREFLIGHT`` and zero calls
on any failed gate, (6) only then reads ``XAI_API_KEY`` -- a missing or empty key is
``ABORTED_RUNTIME`` / ``MISSING_API_KEY`` recorded with zero calls and no environment
content, (7) constructs F/A/R through the injectable factory, (8) wraps them in the
shared budget and the pre-call identity guard (Ruling 7), (9) runs the schedule once,
(10) always persists whatever raw artifacts exist, and (11) never retries.

Exit codes: 0 completed (or preflight-only passed); 2 usage/refusal; 3 any gate
failed (``ABORTED_PREFLIGHT``); 4 the live run ended in any ``ABORTED_*`` status.

Law of this script: it is the outermost layer and decides nothing scientific -- every
expected value comes from the sealed manifest, the frozen literals in ``integrity``,
or the timeline. It never prints or persists the key or any environment content;
error text reaching artifacts is ``type: message`` only, and every console line is
redacted. The real adapters are constructed ONLY inside ``default_reasoner_factory``,
which no test exercises.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NamedTuple
from uuid import uuid4

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    POLICY_VERSION,
    SYSTEM_INSTRUCTION,
    XAIContrastiveSemanticReasoner,
    XAISemanticReasoner,
    semantic_output_schema_sha256,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.experiments.contrastive_unseen.artifacts import (
    ARTIFACT_FORMAT_VERSION,
    MODEL,
    PREREGISTRATION_FILE_NAMES,
    REASONING_EFFORT,
    existing_raw_artifacts,
    pretty_json,
    redact_secrets,
    write_preflight,
    write_run_artifacts,
)
from foundry.experiments.contrastive_unseen.integrity import (
    MANIFEST_KEY_A_POLICY_VERSION,
    MANIFEST_KEY_A_PROMPT_SHA256,
    MANIFEST_KEY_CEILINGS,
    MANIFEST_KEY_FR_POLICY_VERSION,
    MANIFEST_KEY_FR_PROMPT_SHA256,
    MANIFEST_KEY_OUTPUT_SCHEMA_SHA256,
    REQUIRED_REQUEST_PATH_MODULES,
    CommandRunnerLike,
    GateResult,
    GitCliLike,
    all_passed,
    preflight,
)
from foundry.experiments.contrastive_unseen.leakage import LeakageResult, run_leakage_gate
from foundry.experiments.contrastive_unseen.records import Arm
from foundry.experiments.contrastive_unseen.runner import (
    A_PROJECT_ID,
    F_PROJECT_ID,
    ArmReasoners,
    ArmSummary,
    BudgetedReasoner,
    ExperimentBudget,
    PersistentArm,
    RunResult,
    RunStatus,
    StepRecord,
    build_arm_reasoners,
    r_project_id,
    run_experiment,
)
from foundry.experiments.contrastive_unseen.timeline import (
    ARM_SCHEDULE,
    EXPERIMENT_VERSION,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
)
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

__all__ = [
    "API_KEY_ENV",
    "EXIT_ABORTED",
    "EXIT_OK",
    "EXIT_PREFLIGHT_FAILED",
    "EXIT_REFUSED",
    "MISSING_API_KEY",
    "REQUEST_PATH_DIR",
    "CommandRunner",
    "GitCli",
    "IdentityDrift",
    "IdentityGuardReasoner",
    "ReasonerFactory",
    "build_parser",
    "default_reasoner_factory",
    "main",
]

API_KEY_ENV: Final = "XAI_API_KEY"
MISSING_API_KEY: Final = "MISSING_API_KEY"
REQUEST_PATH_DIR: Final = "src/foundry/experiments/contrastive_unseen"
EXIT_OK: Final = 0
EXIT_REFUSED: Final = 2
EXIT_PREFLIGHT_FAILED: Final = 3
EXIT_ABORTED: Final = 4
_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_INTERRUPTED: Final = "INTERRUPTED: KeyboardInterrupt"
_ARMS: Final[dict[str, Arm]] = {"F": "F", "A": "A", "R": "R"}
_PERSISTENT_PROJECT_IDS: Final[dict[str, str]] = {"F": F_PROJECT_ID, "A": A_PROJECT_ID}

ReasonerFactory = Callable[..., tuple[SemanticReasoner, SemanticReasoner, SemanticReasoner]]


class _Refused(Exception):
    """A usage/seal/artifact refusal; printed and mapped to ``EXIT_REFUSED``."""


# --------------------------------------------------------------------------- subprocess adapters


class GitCli:
    """``GitCliLike`` over read-only git subcommands in ``cwd``. Never used by tests."""

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def _run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - fixed read-only argv, no shell
            ["git", "-C", str(self._cwd), *args], capture_output=True, check=False
        )

    def _text(self, *args: str) -> str:
        completed = self._run(*args)
        if completed.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed ({completed.returncode}): "
                f"{completed.stderr.decode('utf-8', 'replace').strip()}"
            )
        return completed.stdout.decode("utf-8")

    def head(self) -> str:
        return self._text("rev-parse", "HEAD").strip()

    def dirty(self) -> str:
        return self._text("status", "--porcelain")

    def parents(self, sha: str) -> tuple[str, ...]:
        line = self._text("rev-list", "--parents", "-n", "1", sha).strip()
        return tuple(line.split()[1:])

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self._run("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]:
        output = self._text("diff", "--name-only", f"{base}..{head}")
        return tuple(line for line in output.splitlines() if line)

    def show_bytes(self, sha: str, path: str) -> bytes:
        completed = self._run("show", f"{sha}:{path}")
        if completed.returncode != 0:
            raise RuntimeError(f"git show {sha}:{path} failed ({completed.returncode})")
        return completed.stdout


class CommandRunner:
    """``CommandRunnerLike`` over ``subprocess`` in ``cwd``. Never used by tests."""

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def run(self, argv: tuple[str, ...]) -> tuple[int, str]:
        completed = subprocess.run(  # noqa: S603 - argv is a frozen integrity literal
            list(argv), cwd=str(self._cwd), capture_output=True, check=False, text=True
        )
        return completed.returncode, completed.stdout + completed.stderr


# --------------------------------------------------------------------------- factory


def default_reasoner_factory(
    *, api_key: str
) -> tuple[SemanticReasoner, SemanticReasoner, SemanticReasoner]:
    """F and R: ``XAIContrastiveSemanticReasoner``; A: ``XAISemanticReasoner``; all
    ``grok-4.6`` / ``high``. The ONLY place a real adapter is constructed."""
    f = XAIContrastiveSemanticReasoner(
        api_key=api_key, model=MODEL, reasoning_effort=REASONING_EFFORT
    )
    a = XAISemanticReasoner(api_key=api_key, model=MODEL, reasoning_effort=REASONING_EFFORT)
    r = XAIContrastiveSemanticReasoner(
        api_key=api_key, model=MODEL, reasoning_effort=REASONING_EFFORT
    )
    return f, a, r


# --------------------------------------------------------------------------- identity guard


class IdentityDrift(RuntimeError):
    """The in-process policy/prompt/schema/ceiling identity no longer equals the sealed
    manifest. Raised BEFORE the call is forwarded; the runner records ``ABORTED_RUNTIME``."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _identity_drift(manifest: Mapping[str, Any]) -> str | None:
    """The first sealed field whose in-process value drifted, with both values; or
    ``None``. Reads this module's own references so a rebinding here is caught."""
    in_process: dict[str, Any] = {
        MANIFEST_KEY_A_PROMPT_SHA256: _sha256(SYSTEM_INSTRUCTION),
        MANIFEST_KEY_FR_PROMPT_SHA256: _sha256(CONTRASTIVE_SYSTEM_INSTRUCTION),
        MANIFEST_KEY_A_POLICY_VERSION: POLICY_VERSION,
        MANIFEST_KEY_FR_POLICY_VERSION: CONTRASTIVE_POLICY_VERSION,
        MANIFEST_KEY_OUTPUT_SCHEMA_SHA256: semantic_output_schema_sha256(),
        MANIFEST_KEY_CEILINGS: {
            "max_frontier_calls": MAX_FRONTIER_CALLS,
            "max_judge_calls": MAX_JUDGE_CALLS,
            "max_human_authorizations": MAX_HUMAN_AUTHORIZATIONS,
            "max_cost_usd": MAX_COST_USD,
        },
    }
    for key, actual in in_process.items():
        sealed = manifest.get(key)
        if actual != sealed:
            return f"{key}: in process {actual!r} != manifest {sealed!r}"
    return None


class IdentityGuardReasoner(BudgetedReasoner):
    """Installed outside the budget wrapper. Before EVERY forwarded call it re-checks
    the in-process identity against the manifest and raises ``IdentityDrift`` on any
    difference. Otherwise transparent: same recording, same budget, same fingerprint."""

    def __init__(self, inner: BudgetedReasoner, *, manifest: Mapping[str, Any]) -> None:
        super().__init__(inner.recording, inner.budget)
        self._inner = inner
        self._manifest = manifest

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._inner.fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        drift = _identity_drift(self._manifest)
        if drift is not None:
            raise IdentityDrift(f"identity drift before call; refusing to forward -- {drift}")
        return self._inner.propose(request)


# --------------------------------------------------------------------------- preflight


class _Preflight(NamedTuple):
    gates: tuple[GateResult, ...]
    leakage: LeakageResult
    manifest: dict[str, Any]

    @property
    def passed(self) -> bool:
        return all_passed(self.gates)


def _read_seal(out_dir: Path) -> tuple[bytes, bytes]:
    missing = [name for name in PREREGISTRATION_FILE_NAMES if not (out_dir / name).is_file()]
    if missing:
        raise _Refused(f"sealed preregistration file(s) missing under {out_dir}: {missing}")
    return (out_dir / "manifest.json").read_bytes(), (out_dir / "expectations.json").read_bytes()


def _request_path_sources(cwd: Path) -> dict[str, str]:
    """The six real request-path files; a missing/unreadable one is simply absent so
    gate 16 fails on its own terms (C2). Nothing is fabricated."""
    sources: dict[str, str] = {}
    for name in REQUIRED_REQUEST_PATH_MODULES:
        path = cwd / REQUEST_PATH_DIR / name
        try:
            sources[name] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return sources


def _evaluate_preflight(
    *, out_dir: Path, cwd: Path, frozen_sha: str, git: GitCliLike, commands: CommandRunnerLike
) -> _Preflight:
    manifest_bytes, expectations_bytes = _read_seal(out_dir)
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Refused(f"manifest.json is unparsable: {type(exc).__name__}") from exc
    if not isinstance(manifest, dict):
        raise _Refused("manifest.json is not a JSON object")
    leakage = run_leakage_gate()
    gates = preflight(
        git=git,
        commands=commands,
        frozen_sha=frozen_sha,
        manifest=manifest,
        expectations_bytes=expectations_bytes,
        request_path_sources=_request_path_sources(cwd),
        leakage=leakage,
    )
    return _Preflight(gates, leakage, manifest)


def _preflight_document(result: _Preflight, *, frozen_sha: str) -> dict[str, Any]:
    """Exactly the document ``write_preflight`` writes (kept in step by test)."""
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "frozen_sha": frozen_sha,
        "all_passed": result.passed,
        "gates": [gate.model_dump(mode="json") for gate in result.gates],
        "leakage": result.leakage.model_dump(mode="json"),
    }


# --------------------------------------------------------------------------- zero-run result


def _not_run(*, arm: Arm, t: int, position: int, project_id: str) -> StepRecord:
    """A structural NOT_RUN cell: nothing shown, nothing admitted, nothing recorded."""
    return StepRecord(
        arm=arm,
        t=t,
        position=position,
        status="NOT_RUN",
        error=None,
        project_id=project_id,
        evidence_ids_shown=(),
        requests=(),
        stage_decisions=((), ()),
        neighborhood=(),
        claim_neighborhood=(),
        pending_supersede_judgment_ids=(),
        root_designations=(),
        authorizations=(),
        receipts=(),
        draft_payloads=(),
        state_snapshot=None,
        view_snapshot=None,
        ledger=(),
    )


def _empty_summary(
    arm: PersistentArm, project_id: str, reasoner: BudgetedReasoner | None
) -> ArmSummary:
    """An arm that never advanced: empty state and view; whatever request records the
    recording wrapper holds (none when no reasoner ever existed)."""
    state = IntentState(project_id=project_id)
    return ArmSummary(
        arm=arm,
        project_id=project_id,
        roots={},
        ledger=(),
        final_state=state,
        final_view=derive_view(state.semantic),
        replay=None,
        authorizations=(),
        requests=() if reasoner is None else reasoner.recording.records,
    )


def _aborted_runtime_result(
    *, error: str, budget: ExperimentBudget | None, arms: ArmReasoners | None
) -> RunResult:
    """``ABORTED_RUNTIME`` with every schedule position ``NOT_RUN``: the run never
    started (missing key) or the runner itself raised outside its per-step catch.
    Whatever the budget and recording wrappers hold is preserved."""
    steps = tuple(
        _not_run(
            arm=_ARMS[arm],
            t=t,
            position=position,
            project_id=_PERSISTENT_PROJECT_IDS.get(arm) or r_project_id(t),
        )
        for position, (t, arm) in enumerate(ARM_SCHEDULE)
    )
    return RunResult(
        status=RunStatus.ABORTED_RUNTIME,
        error=error,
        steps=steps,
        f=_empty_summary("F", F_PROJECT_ID, None if arms is None else arms.f),
        a=_empty_summary("A", A_PROJECT_ID, None if arms is None else arms.a),
        r_steps={step.t: step for step in steps if step.arm == "R"},
        budget=(budget if budget is not None else ExperimentBudget()).snapshot(),
        schedule=ARM_SCHEDULE,
    )


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- live run


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mint(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _live(
    *,
    out_dir: Path,
    cwd: Path,
    frozen_sha: str,
    env: Mapping[str, str],
    reasoner_factory: ReasonerFactory,
    git: GitCliLike,
    commands: CommandRunnerLike,
) -> int:
    _read_seal(out_dir)
    existing = existing_raw_artifacts(out_dir)
    if existing:
        raise _Refused(
            f"raw artifact(s) already exist under {out_dir}: {list(existing)}; this "
            "experiment identity has already been run or its preflight preserved -- never rerun"
        )
    result = _evaluate_preflight(
        out_dir=out_dir, cwd=cwd, frozen_sha=frozen_sha, git=git, commands=commands
    )
    write_preflight(out_dir, result.gates, frozen_sha=frozen_sha, leakage=result.leakage)
    _say(f"preflight: {'PASS' if result.passed else 'FAIL'} ({len(result.gates)} gates)")
    if not result.passed:
        for gate in result.gates:
            if not gate.passed:
                _say(f"  FAILED {gate.name}: {gate.detail}")
        _say(f"status: {RunStatus.ABORTED_PREFLIGHT.value} (0 calls)")
        return EXIT_PREFLIGHT_FAILED

    api_key = env.get(API_KEY_ENV, "")
    if not api_key:
        run = _aborted_runtime_result(error=MISSING_API_KEY, budget=None, arms=None)
        write_run_artifacts(out_dir, run)
        _say(f"status: {run.status.value} ({run.error}; 0 calls)")
        return EXIT_ABORTED

    inner_f, inner_a, inner_r = reasoner_factory(api_key=api_key)
    del api_key
    budget = ExperimentBudget()
    arms = build_arm_reasoners(inner_f=inner_f, inner_a=inner_a, inner_r=inner_r, budget=budget)
    manifest = result.manifest
    guarded = ArmReasoners(
        f=IdentityGuardReasoner(arms.f, manifest=manifest),
        a=IdentityGuardReasoner(arms.a, manifest=manifest),
        r=IdentityGuardReasoner(arms.r, manifest=manifest),
    )
    try:
        run = run_experiment(
            reasoner_f=guarded.f,
            reasoner_a=guarded.a,
            reasoner_r=guarded.r,
            clock=_utc_now,
            id_factory=_mint,
        )
    except KeyboardInterrupt:
        run = _aborted_runtime_result(error=_INTERRUPTED, budget=budget, arms=arms)
    except Exception as exc:  # noqa: BLE001 - recorded as ABORTED_RUNTIME, never retried
        run = _aborted_runtime_result(error=_error_text(exc), budget=budget, arms=arms)
    write_run_artifacts(out_dir, run)
    _say(
        f"status: {run.status.value} (frontier_calls={run.budget.frontier_calls}, "
        f"cost_usd={run.budget.provider_cost_usd}, "
        f"human_authorizations={run.budget.human_authorizations})"
    )
    if run.error is not None:
        _say(f"error: {run.error}")
    return EXIT_OK if run.status is RunStatus.COMPLETED else EXIT_ABORTED


# --------------------------------------------------------------------------- CLI


def _say(line: str) -> None:
    print(redact_secrets(line))


def _frozen_sha(value: str) -> str:
    if not _SHA_RE.match(value):
        raise argparse.ArgumentTypeError("--frozen-sha must be exactly 40 lowercase hex digits")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="9P2 unseen-lifecycle experiment: preflight, or one gated live run."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight-only",
        action="store_true",
        help="evaluate every gate, print the preflight document, write nothing",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="preflight, then one live run (requires architect authorization)",
    )
    parser.add_argument("--frozen-sha", required=True, type=_frozen_sha, help="final seal SHA")
    parser.add_argument("--out", required=True, type=Path, help="experiment directory")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    reasoner_factory: ReasonerFactory | None = None,
    git: GitCliLike | None = None,
    commands: CommandRunnerLike | None = None,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exit_:
        code = exit_.code
        return code if isinstance(code, int) else EXIT_REFUSED
    root = (cwd if cwd is not None else Path.cwd()).resolve()
    out_dir: Path = args.out if args.out.is_absolute() else root / args.out
    git_cli: GitCliLike = git if git is not None else GitCli(root)
    runner: CommandRunnerLike = commands if commands is not None else CommandRunner(root)
    try:
        if args.preflight_only:
            result = _evaluate_preflight(
                out_dir=out_dir,
                cwd=root,
                frozen_sha=args.frozen_sha,
                git=git_cli,
                commands=runner,
            )
            document = pretty_json(_preflight_document(result, frozen_sha=args.frozen_sha))
            print(redact_secrets(document), end="")
            return EXIT_OK if result.passed else EXIT_PREFLIGHT_FAILED
        return _live(
            out_dir=out_dir,
            cwd=root,
            frozen_sha=args.frozen_sha,
            env=env if env is not None else os.environ,
            reasoner_factory=(
                reasoner_factory if reasoner_factory is not None else default_reasoner_factory
            ),
            git=git_cli,
            commands=runner,
        )
    except _Refused as refusal:
        _say(f"REFUSED: {refusal}")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())

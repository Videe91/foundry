"""Locus-policy live-validation entry point: non-consuming preflight, then (only under
``--live``, and only after every gate passed) the single consuming run (spec §8, §10,
§11, §13, §15; plan T8; controller clarifications 1-4, 7).

    GRPC_DNS_RESOLVER=native uv run python scripts/run_locus_validation.py \\
        (--preflight-only | --live) --frozen-sha <40 hex> \\
        --out docs/superpowers/experiments/2026-09-15-locus-validation-v1

The required launch form sets ``GRPC_DNS_RESOLVER=native`` in the process environment
BEFORE Python starts. This script never sets, defaults or normalises it: it observes
``env.get("GRPC_DNS_RESOLVER")`` exactly once, after the seal files are read (and,
under ``--live``, after the consumed-identity refusal) and before any gate in either
mode, and gate 15 refuses anything but the exact string ``native``.

The identity state machine (spec §10). Preflight is NON-CONSUMING and read-only: in
every mode the 18 ``integrity.GATE_NAMES`` gates are evaluated over the sealed
``manifest.json`` / ``expectations.json`` bytes, the four real request-path sources
read from the package directory (a missing one is passed as missing so gate 13 fails;
nothing is fabricated), the §9 leakage gate, the observed resolver and injected git
facts -- BEFORE ``XAI_API_KEY`` is read and BEFORE any reasoner exists.

``--preflight-only`` prints the preflight document (``frozen_sha``, the 18 gates with
redacted details, ``all_passed``, ``frontier_calls: 0``, the observed resolver) to
stdout, writes nothing, constructs nothing, reads no key, never consumes, and exits 3
if any gate failed, else 0. It may be run any number of times; on a consumed
directory it still evaluates every gate and reports gate 18 as FAILED (informational).

Exit codes: 0 completed (or preflight-only passed); 2 usage / seal / consumed-identity
/ key / identity refusal (nothing written, not consumed); 3 any gate failed (nothing
written, not consumed); 4 aborted after consumption (the full raw tree is written
where it can be) or the raw tree could not be preserved.

``--live``, in this load-bearing order (every step before consumption writes nothing):
(1) both seal files must exist and parse (else ``REFUSED``, exit 2); (2) spec §10: if
ANY raw artifact exists under the directory (``consumption.json`` or ``preflight.json``
alone suffice) the identity is consumed and the run is ``REFUSED`` (exit 2) right
here -- before the resolver read, the leakage gate and the gates; nothing is written,
the key is never read, the factory never called; (3) the resolver is observed once;
(4) leakage, then the complete 18-gate preflight from scratch (an earlier
``--preflight-only`` is never trusted); any failed gate: the failed gates are printed,
exit 3, nothing written, the key unread, the factory uncalled; (5) only then
``env.get("XAI_API_KEY")``: missing or empty is ``REFUSED``, exit 2, nothing
written; (6) the injectable factory constructs the inner reasoner with NO call, the key
name is dropped, and ``require_locus_identity`` guards the instance -- a factory
exception or identity drift here is ``REFUSED`` (redacted ``type: message``), exit 2,
nothing written, NOT consumed; (7) ``write_consumption`` -- THE identity-consuming
write, the first and only write before any call: ``preflight.json`` then
``consumption.json``; (8) inside ONE abort boundary: a fresh ``ExperimentBudget`` and
``run_experiment`` (alpha then beta, fail-fast; the runner records every failure it
sees) -- a ``KeyboardInterrupt`` or ``Exception`` escaping the runner is recorded by
``_aborted_result`` from the ledger records the runner handed over, never retried;
(9) ``evaluate_run`` and ``integrity_verdicts`` over the SAME gate tuple written to
``preflight.json`` (never re-evaluated); (10) ``write_run_artifacts`` exactly once --
any exception there is printed redacted as ``RAW ARTIFACT PRESERVATION FAILED``, exit
4, no second write attempt, no replacement run, ``preflight.json`` /
``consumption.json`` untouched. Exit 0 iff the run ``COMPLETED``, else 4.

Law of this script: it is the outermost layer and decides nothing scientific -- every
expected value comes from the sealed manifest and the frozen literals in ``integrity``,
``protocol`` and ``recording``; it grades no case and names no outcome. It never
prints or persists the key or any environment content; error text reaching artifacts
is ``type: message`` only, and every console line is redacted. The real adapter is
constructed ONLY inside ``default_reasoner_factory``, which no test exercises.
"""

from __future__ import annotations

import argparse
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

import foundry.experiments.locus_validation as experiment_package
from foundry.adapters.semantics.xai_reasoner import (
    SemanticOutputError,
    XAILocusSemanticReasoner,
    XAIProviderError,
)
from foundry.experiments.contrastive_unseen.artifacts import pretty_json
from foundry.experiments.locus_validation.artifacts import (
    ConsumptionRefused,
    existing_raw_artifacts,
    write_consumption,
    write_run_artifacts,
)
from foundry.experiments.locus_validation.corpus import LEDGERS, PROJECT_IDS, SCOPES, Ledger
from foundry.experiments.locus_validation.evaluation import evaluate_run
from foundry.experiments.locus_validation.integrity import (
    MANIFEST_KEY_HARNESS_CODE_SHA,
    GateResult,
    GitCliLike,
    all_passed,
    integrity_verdicts,
    preflight,
)
from foundry.experiments.locus_validation.leakage import (
    REQUEST_PATH_MODULES,
    LeakageResult,
    run_leakage_gate,
)
from foundry.experiments.locus_validation.protocol import (
    EXPERIMENT_ARTIFACT_DIR,
    GRPC_DNS_RESOLVER_ENV,
    MODEL,
    PREREGISTRATION_FILE_NAMES,
    REASONING_EFFORT,
)
from foundry.experiments.locus_validation.recording import (
    BudgetExceeded,
    ExperimentBudget,
    IdentityDrift,
    require_locus_identity,
)
from foundry.experiments.locus_validation.runner import (
    LedgerRecord,
    RunResult,
    RunStatus,
    run_experiment,
)
from foundry.experiments.long_horizon_bounded.runner import ReferenceSnapshotMismatch
from foundry.experiments.longitudinal.artifacts import redact_secrets
from foundry.ports.semantic_reasoner import SemanticReasoner

__all__ = [
    "API_KEY_ENV",
    "DEFAULT_OUT",
    "EXIT_ABORTED",
    "EXIT_OK",
    "EXIT_PREFLIGHT_FAILED",
    "EXIT_REFUSED",
    "REQUEST_PATH_DIR",
    "GitCli",
    "ReasonerFactory",
    "build_parser",
    "default_reasoner_factory",
    "main",
    "request_path_sources",
]

API_KEY_ENV: Final = "XAI_API_KEY"
DEFAULT_OUT: Final = EXPERIMENT_ARTIFACT_DIR.rstrip("/")
REQUEST_PATH_DIR: Final[Path] = Path(experiment_package.__file__).resolve().parent
"""The package directory holding the four real request-path sources gate 13 scans."""
EXIT_OK: Final = 0
EXIT_REFUSED: Final = 2
EXIT_PREFLIGHT_FAILED: Final = 3
EXIT_ABORTED: Final = 4
_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_INTERRUPTED: Final = "INTERRUPTED: KeyboardInterrupt"
_MANIFEST_NAME: Final = PREREGISTRATION_FILE_NAMES[0]
_EXPECTATIONS_NAME: Final = PREREGISTRATION_FILE_NAMES[1]

ReasonerFactory = Callable[..., SemanticReasoner]


class _Refused(Exception):
    """A usage / seal / key / identity refusal; printed and mapped to ``EXIT_REFUSED``.
    Raised only BEFORE consumption: nothing has been written when it is raised."""


# --------------------------------------------------------------------------- subprocess adapter


class GitCli:
    """``GitCliLike`` over read-only git subcommands in ``cwd`` (plain argv, no shell).
    Never used by tests."""

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

    def tree_sha(self, sha: str, path: str) -> str:
        return self._text("rev-parse", f"{sha}:{path}").strip()


# --------------------------------------------------------------------------- factory


def default_reasoner_factory(*, api_key: str) -> SemanticReasoner:
    """The locus adapter at the frozen model and effort. The ONLY place a real adapter
    is constructed; construction makes no call."""
    return XAILocusSemanticReasoner(api_key=api_key, model=MODEL, reasoning_effort=REASONING_EFFORT)


# --------------------------------------------------------------------------- preflight


class _Preflight(NamedTuple):
    gates: tuple[GateResult, ...]
    leakage: LeakageResult
    manifest: dict[str, Any]
    observed_grpc_dns_resolver: str | None
    """The live process's ``GRPC_DNS_RESOLVER`` exactly as observed, once."""

    @property
    def passed(self) -> bool:
        return all_passed(self.gates)


def _read_seal(out_dir: Path) -> tuple[dict[str, Any], bytes]:
    """The sealed pair: the parsed manifest object and the raw expectations bytes.
    Missing, unparsable or non-object files are refusals; nothing is fabricated."""
    missing = [name for name in PREREGISTRATION_FILE_NAMES if not (out_dir / name).is_file()]
    if missing:
        raise _Refused(f"sealed preregistration file(s) missing under {out_dir}: {missing}")
    manifest_bytes = (out_dir / _MANIFEST_NAME).read_bytes()
    expectations_bytes = (out_dir / _EXPECTATIONS_NAME).read_bytes()
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Refused(f"{_MANIFEST_NAME} is unparsable: {type(exc).__name__}") from exc
    if not isinstance(manifest, dict):
        raise _Refused(f"{_MANIFEST_NAME} is not a JSON object")
    return manifest, expectations_bytes


def request_path_sources() -> dict[str, str]:
    """The four real request-path files from the package directory; a missing or
    unreadable one is simply absent so gate 13 fails on its own terms. Nothing is
    fabricated."""
    sources: dict[str, str] = {}
    for name in REQUEST_PATH_MODULES:
        path = REQUEST_PATH_DIR / name
        try:
            sources[name] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return sources


def _refuse_consumed(out_dir: Path) -> None:
    """Spec §10: any raw artifact under ``out_dir`` (``consumption.json`` or
    ``preflight.json`` alone included) means the experiment identity is consumed; a
    later ``--live`` is refused here -- before the resolver read, the leakage gate and
    the 18 gates -- with nothing written, no key read and no factory call."""
    existing = existing_raw_artifacts(out_dir)
    if existing:
        raise _Refused(
            f"raw artifacts already exist under {out_dir}: {list(existing)} (experiment "
            "identity consumed); this seal is never run again"
        )


def _evaluate_preflight(
    *,
    out_dir: Path,
    frozen_sha: str,
    git: GitCliLike,
    env: Mapping[str, str],
    live: bool,
) -> _Preflight:
    """Seal files; under ``--live`` the consumed-identity refusal; then the ONE
    observation of ``GRPC_DNS_RESOLVER`` (never set, defaulted or normalised); the
    leakage gate; the 18 gates -- read-only, key-free, constructing nothing.
    ``--preflight-only`` skips only the refusal: it evaluates every gate (gate 18
    reports a consumed directory as FAILED) and remains non-consuming."""
    manifest, expectations_bytes = _read_seal(out_dir)
    if live:
        _refuse_consumed(out_dir)
    observed_grpc_dns_resolver: str | None = env.get(GRPC_DNS_RESOLVER_ENV)
    leakage = run_leakage_gate()
    gates = preflight(
        git=git,
        frozen_sha=frozen_sha,
        manifest=manifest,
        expectations_bytes=expectations_bytes,
        request_path_sources=request_path_sources(),
        leakage=leakage,
        observed_grpc_dns_resolver=observed_grpc_dns_resolver,
        out_dir=out_dir,
    )
    return _Preflight(gates, leakage, manifest, observed_grpc_dns_resolver)


def _preflight_document(result: _Preflight, *, frozen_sha: str) -> dict[str, Any]:
    """The document ``--preflight-only`` prints (spec §10): gate details redacted,
    ``frontier_calls`` always 0 -- no call has been made and none will be."""
    return {
        "frozen_sha": frozen_sha,
        "gates": [
            gate.model_copy(update={"detail": redact_secrets(gate.detail)}).model_dump(mode="json")
            for gate in result.gates
        ],
        "all_passed": result.passed,
        "frontier_calls": 0,
        "observed_grpc_dns_resolver": result.observed_grpc_dns_resolver,
    }


def _report_failed_gates(result: _Preflight) -> None:
    _say(f"preflight: FAIL ({len(result.gates)} gates)")
    for gate in result.gates:
        if not gate.passed:
            _say(f"  FAILED {gate.name}: {gate.detail}")
    _say("status: PREFLIGHT_FAILED (0 calls; nothing written; not consumed)")


# --------------------------------------------------------------------------- abort recording


def _error_text(exc: BaseException) -> str:
    """``type: message`` only, redacted -- the key never reaches an artifact. An
    interrupt is the runner's own literal."""
    if isinstance(exc, KeyboardInterrupt):
        return _INTERRUPTED
    return redact_secrets(f"{type(exc).__name__}: {exc}")


def _classify(exc: BaseException) -> RunStatus:
    """The runner's classification, restated over its public exception types."""
    if isinstance(exc, XAIProviderError):
        return RunStatus.ABORTED_PROVIDER
    if isinstance(exc, SemanticOutputError | ReferenceSnapshotMismatch):
        return RunStatus.ABORTED_MODEL_CONTRACT
    if isinstance(exc, BudgetExceeded):
        return RunStatus.ABORTED_BUDGET
    if isinstance(exc, IdentityDrift):
        return RunStatus.ABORTED_IDENTITY
    return RunStatus.ABORTED_RUNTIME


def _not_run(ledger: Ledger) -> LedgerRecord:
    """The structural fill for a ledger the walk never reached (the runner's own shape)."""
    return LedgerRecord(
        ledger=ledger,
        project_id=PROJECT_IDS[ledger],
        scope=SCOPES[ledger],
        status="NOT_RUN",
        error=None,
        deltas=(),
        ledger_events=(),
        final_state=None,
        final_view=None,
        replay=None,
    )


def _aborted_result(
    progress: Sequence[LedgerRecord], budget: ExperimentBudget, error: BaseException
) -> RunResult:
    """The ``RunResult`` for a failure that escaped the runner AFTER consumption: every
    ledger record the runner handed over is kept exactly as recorded (COMPLETED or
    FAILED), every unreached ledger is ``NOT_RUN``, the status is classified as the
    runner classifies, the budget is whatever it holds, the error text is redacted.
    Never used before consumption; never a replacement for a preservation failure."""
    recorded = {record.ledger: record for record in progress}
    filled = tuple(recorded.get(ledger) or _not_run(ledger) for ledger in LEDGERS)
    return RunResult(
        status=_classify(error),
        error=_error_text(error),
        ledgers=(filled[0], filled[1]),
        budget=budget.snapshot(),
    )


# --------------------------------------------------------------------------- live run


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mint(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _construct_guarded(
    env: Mapping[str, str], reasoner_factory: ReasonerFactory
) -> SemanticReasoner:
    """Steps 5-6: the key (read once, after the gates), the factory, the drop of the key
    name, the construction-time identity guard. Every failure here is a refusal:
    nothing has been written and nothing is consumed."""
    api_key = env.get(API_KEY_ENV)
    if not api_key:
        raise _Refused(f"{API_KEY_ENV} missing or empty; nothing written; not consumed")
    try:
        inner = reasoner_factory(api_key=api_key)
        del api_key
        require_locus_identity(inner)
    except Exception as exc:
        raise _Refused(
            f"reasoner construction refused ({_error_text(exc)}); nothing written; not consumed"
        ) from exc
    return inner


def _persist(
    out_dir: Path, run: RunResult, *, gates: tuple[GateResult, ...]
) -> tuple[str, ...] | None:
    """Steps 9-10: ``evaluate_run``, ``integrity_verdicts`` over the SAME gate tuple
    written to ``preflight.json``, then ``write_run_artifacts`` exactly once. On any
    failure the writer is never called again, no replacement run is built, the run is
    not mutated and the consumption files are left as they are; the failure is printed
    redacted and ``None`` returned."""
    try:
        case_results = evaluate_run(run)
        verdicts = integrity_verdicts(run, preflight_gates=gates, case_results=case_results)
        return write_run_artifacts(out_dir, run, verdicts, case_results)
    except Exception as exc:  # noqa: BLE001 - reported, never retried
        _say(f"RAW ARTIFACT PRESERVATION FAILED: {_error_text(exc)}")
        _say(f"frontier_calls={run.budget.frontier_calls}")
        return None


def _live(
    *,
    out_dir: Path,
    frozen_sha: str,
    env: Mapping[str, str],
    reasoner_factory: ReasonerFactory,
    git: GitCliLike,
) -> int:
    # (1)-(4): seal files, the consumed-identity refusal, the resolver, leakage and
    # the complete preflight from scratch; a refusal or a failed gate writes nothing.
    result = _evaluate_preflight(
        out_dir=out_dir, frozen_sha=frozen_sha, git=git, env=env, live=True
    )
    gates = result.gates
    if not result.passed:
        _report_failed_gates(result)
        return EXIT_PREFLIGHT_FAILED
    _say(f"preflight: PASS ({len(gates)} gates)")

    # (5)-(6): the key and the guarded construction; refusals write nothing.
    inner = _construct_guarded(env, reasoner_factory)

    # (7): THE consuming write -- the first and only write before any call.
    harness_code_sha = str(result.manifest[MANIFEST_KEY_HARNESS_CODE_SHA])
    try:
        preflight_path, consumption_path = write_consumption(
            out_dir,
            gates=gates,
            frozen_sha=frozen_sha,
            harness_code_sha=harness_code_sha,
            leakage=result.leakage,
            observed_grpc_dns_resolver=result.observed_grpc_dns_resolver,
            consumed_at=_utc_now(),
        )
    except ConsumptionRefused as refusal:
        raise _Refused(f"{refusal}; nothing written; not consumed") from refusal
    _say(f"identity consumed: {preflight_path.name}, {consumption_path.name} written")

    # (8): one abort boundary; every failure is recorded, nothing is retried.
    budget = ExperimentBudget()
    progress: list[LedgerRecord] = []
    try:
        run = run_experiment(
            inner=inner, budget=budget, clock=_utc_now, id_factory=_mint, progress=progress
        )
    except KeyboardInterrupt as interrupt:
        run = _aborted_result(progress, budget, interrupt)
    except Exception as exc:  # noqa: BLE001 - recorded from the ledgers handed over
        run = _aborted_result(progress, budget, exc)

    # (9)-(10): evaluation, verdicts over the same gates, one raw write.
    written = _persist(out_dir, run, gates=gates)
    if written is None:
        return EXIT_ABORTED
    _say(
        f"status: {run.status.value} (frontier_calls={run.budget.frontier_calls}, "
        f"cost_usd={run.budget.provider_cost_usd}, judge_calls={run.budget.judge_calls}, "
        f"human_authorizations={run.budget.human_authorizations})"
    )
    if run.error is not None:
        _say(f"error: {run.error}")
    _say(f"raw artifacts written: {len(written)} paths under {out_dir}")
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
        description=(
            "Locus-policy live-validation experiment: non-consuming preflight, or the single "
            "consuming live run."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight-only",
        action="store_true",
        help="evaluate every gate, print the preflight document, write nothing, consume nothing",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="preflight from scratch, then the one consuming live run (architect-authorized)",
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
    environment: Mapping[str, str] = env if env is not None else os.environ
    try:
        if args.preflight_only:
            result = _evaluate_preflight(
                out_dir=out_dir,
                frozen_sha=args.frozen_sha,
                git=git_cli,
                env=environment,
                live=False,
            )
            document = pretty_json(_preflight_document(result, frozen_sha=args.frozen_sha))
            print(redact_secrets(document), end="")
            return EXIT_OK if result.passed else EXIT_PREFLIGHT_FAILED
        return _live(
            out_dir=out_dir,
            frozen_sha=args.frozen_sha,
            env=environment,
            reasoner_factory=(
                reasoner_factory if reasoner_factory is not None else default_reasoner_factory
            ),
            git=git_cli,
        )
    except _Refused as refusal:
        _say(f"REFUSED: {refusal}")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())

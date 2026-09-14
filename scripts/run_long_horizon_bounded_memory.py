"""9P3 long-horizon bounded-memory entry point: offline preflight, then (only if
explicitly authorized and passed) one live run (spec §12, §14, §16, §17, §19; plan T7;
controller clarifications 1-12).

    GRPC_DNS_RESOLVER=native uv run python scripts/run_long_horizon_bounded_memory.py \\
        (--preflight-only | --live) --frozen-sha <40 hex> \\
        --out docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1

The required launch form sets ``GRPC_DNS_RESOLVER=native`` in the process environment
BEFORE Python starts. This script never sets, defaults or normalises it: it observes
``env.get("GRPC_DNS_RESOLVER")`` exactly once, after argument parsing and before any
gate in either mode, and gate 21 refuses anything but the exact string ``native``. The
observed value is recorded verbatim in the preflight document.

The preflight-before-construction law. In every mode the 23 ``integrity.GATE_NAMES``
gates are evaluated over the sealed ``manifest.json``/``expectations.json`` bytes, the
six real request-path sources read from the package directory (a missing one is passed
as missing so gate 16 fails; nothing is fabricated), the §15 leakage gate, the observed
resolver, injected git facts and injected regression commands -- BEFORE ``XAI_API_KEY``
is read and BEFORE any reasoner exists.

``--preflight-only`` prints the full preflight document (the exact shape
``write_preflight`` writes, gate details redacted) to stdout, writes nothing, reads no
key, constructs nothing, and exits 3 if any gate failed, else 0.

``--live``, in this load-bearing order: (1) both seal files must exist and parse;
(2) refuse if any ``RAW_ARTIFACT_PATHS`` file exists (a preserved failed preflight
included -- a consumed identity is never rerun); (3) leakage, then the 23 gates;
(4) ``write_preflight`` exactly once; (5) stop with exit 3 and zero calls on any failed
gate, the key unread and the factory uncalled; (6) only then read ``XAI_API_KEY`` -- a
missing or empty key is ``ABORTED_RUNTIME`` / ``MISSING_API_KEY`` recorded with zero
calls and no environment content; (7) inside ONE try: construct F/A/R through the
injectable factory, drop the key, wrap each INNER reasoner in the pre-call identity
guard, build the budgeted arms over one shared ``ExperimentBudget`` and run the
48-cell schedule once -- construction, wrapping and the run share one catch, so a
client bootstrap failure or a construction-time identity refusal is recorded as
``ABORTED_RUNTIME`` too; (8) ``integrity_verdicts`` over the SAME gate tuple written to
``preflight.json`` (never re-evaluated); (9) ``write_run_artifacts`` exactly once;
(10) never retry. Exit 0 iff the run ``COMPLETED``, else 4.

Identity is observed, not asserted. ``IdentityGuardReasoner`` wraps the innermost
reasoner of each arm (it must sit inside ``build_arm_reasoners`` because the runner
requires budgeted arms sharing one budget). At construction and before EVERY forwarded
call it compares, besides this module's own references (prompt hashes, policy
versions, output-schema hash, ceilings), the inner reasoner's ``fingerprint.provider``
/ ``model`` / ``policy_version``, its class-level ``policy_version`` and
``system_instruction`` hash, its exposed reasoning effort and -- for F and R -- that it
is on the contrastive adapter path, against the sealed manifest and the frozen
``protocol``. Any difference is ``IdentityDrift`` raised before forwarding: at
construction it is an ``ABORTED_RUNTIME`` tree with zero calls; inside the schedule the
runner records the cell FAILED and every later cell NOT_RUN.

Preservation (spec §16, §19 step 10): the runner appends every cell record to a
caller-owned ``progress`` list; if the runner still raised, ``_aborted_runtime_result``
builds the tree from those records, filling only the missing positions with
``NOT_RUN``. It is used ONLY for failures before a real ``RunResult`` exists. If the
final raw write itself refuses (a secret-shaped scientific request, a binding failure,
a stray target, the contract guard), it is NEVER called again, no replacement run is
built, the run is not mutated, ``preflight.json`` is left untouched, a redacted ``RAW
ARTIFACT PRESERVATION FAILED`` line is printed with the consumed call count, and the
exit is 4 when frontier calls were consumed (the identity is spent) or 2 when none were
(no live attempt began).

Exit codes: 0 completed (or preflight-only passed); 2 usage/seal/artifact refusal;
3 any gate failed (``ABORTED_PREFLIGHT``); 4 the live run ended in any ``ABORTED_*``
status or its raw tree could not be preserved after calls were made.

Law of this script: it is the outermost layer and decides nothing scientific -- every
expected value comes from the sealed manifest, the frozen literals in ``integrity`` and
``protocol``, or the timeline; it never computes architecture selection and never
grades a checkpoint. It never prints or persists the key or any environment content;
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

import foundry.experiments.long_horizon_bounded as experiment_package
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
from foundry.domain.semantic_view import CurrentSemanticView, derive_view
from foundry.domain.state import IntentState
from foundry.experiments.long_horizon_bounded.artifacts import (
    ARTIFACT_FORMAT_VERSION,
    PREREGISTRATION_FILE_NAMES,
    existing_raw_artifacts,
    pretty_json,
    write_preflight,
    write_run_artifacts,
)
from foundry.experiments.long_horizon_bounded.authority import (
    AuthorizationRecord,
    EligibleTargets,
)
from foundry.experiments.long_horizon_bounded.designation import RootDesignation
from foundry.experiments.long_horizon_bounded.integrity import (
    MANIFEST_KEY_A_POLICY_VERSION,
    MANIFEST_KEY_A_PROMPT_SHA256,
    MANIFEST_KEY_CEILINGS,
    MANIFEST_KEY_FR_POLICY_VERSION,
    MANIFEST_KEY_FR_PROMPT_SHA256,
    MANIFEST_KEY_OUTPUT_SCHEMA_SHA256,
    CommandRunnerLike,
    GateResult,
    GitCliLike,
    all_passed,
    integrity_verdicts,
    preflight,
)
from foundry.experiments.long_horizon_bounded.leakage import (
    REQUEST_PATH_MODULES,
    LeakageResult,
    run_leakage_gate,
)
from foundry.experiments.long_horizon_bounded.protocol import (
    A_PROJECT_ID,
    ARM_SCHEDULE,
    F_PROJECT_ID,
    GRPC_DNS_RESOLVER_ENV,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    MAX_SAME_CELL_RERUNS,
    MAX_SEMANTIC_RETRIES,
    MODEL,
    REASONING_EFFORT,
    Arm,
    r_project_id,
)
from foundry.experiments.long_horizon_bounded.runner import (
    ArmReasoners,
    ArmSummary,
    BudgetedReasoner,
    CellRecord,
    ExperimentBudget,
    PersistentArm,
    RunResult,
    RunStatus,
    build_arm_reasoners,
    run_experiment,
)
from foundry.experiments.long_horizon_bounded.timeline import EXPERIMENT_VERSION, Locus
from foundry.experiments.longitudinal.artifacts import redact_secrets
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
REQUEST_PATH_DIR: Final[Path] = Path(experiment_package.__file__).resolve().parent
"""The package directory holding the six real request-path sources gate 16 scans."""
EXIT_OK: Final = 0
EXIT_REFUSED: Final = 2
EXIT_PREFLIGHT_FAILED: Final = 3
EXIT_ABORTED: Final = 4
_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_INTERRUPTED: Final = "INTERRUPTED: KeyboardInterrupt"
_PERSISTENT_PROJECT_IDS: Final[dict[str, str]] = {"F": F_PROJECT_ID, "A": A_PROJECT_ID}
_MANIFEST_KEY_PROVIDER: Final = "provider"
_MANIFEST_KEY_MODEL: Final = "model"
_MANIFEST_KEY_REASONING_EFFORT: Final = "reasoning_effort"
"""``ExperimentManifest`` field names the observed reasoner identity must equal."""
_POLICY_VERSION_ATTRIBUTE: Final = "policy_version"
_SYSTEM_INSTRUCTION_ATTRIBUTE: Final = "system_instruction"
"""The adapter class attributes carrying the arm's policy version and prompt; read
instance-resolved, because the adapter sends ``self.system_instruction``."""
_CONTRASTIVE_PATH_KEY: Final = "include_comparison_context"
"""The adapter class attribute that distinguishes the contrastive path (F, R) from the
historical path (A); compared to the frozen expectation, not to a manifest key."""
_PASS_THROUGH_ATTRIBUTES: Final[frozenset[str]] = frozenset({"receipts", "draft_payloads"})
"""Adapter economics the guard exposes exactly when the inner reasoner does."""

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

    def tree_sha(self, sha: str, path: str) -> str:
        return self._text("rev-parse", f"{sha}:{path}").strip()


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
    """The in-process policy/prompt/schema/ceiling identity, or the wrapped reasoner's
    observable identity, no longer equals the sealed manifest. Raised BEFORE the call is
    forwarded; the runner records the cell FAILED (``ABORTED_RUNTIME``)."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Observation(NamedTuple):
    key: str
    """The sealed manifest field (or the frozen expectation) the value must equal."""
    source: str
    """Where on the reasoner the value was read from (diagnostic only)."""
    actual: Any


def _observed_identity(inner: SemanticReasoner, *, arm: Arm) -> tuple[_Observation, ...]:
    """What the innermost reasoner of ``arm`` observably IS, keyed by the manifest field
    each value must equal: provider, model and policy from its fingerprint; the arm's
    policy version and prompt hash when the class has those attributes (the real
    adapters do), read as the INSTANCE resolves them -- the adapter sends
    ``self.system_instruction``, so an instance attribute shadowing the ClassVar is
    what is observed; the reasoning effort when it exposes one (the frozen adapter
    stores ``_reasoning_effort``); the contrastive-path flag when the class has it,
    instance-resolved likewise. A fake without an attribute is judged on what it does
    expose."""
    if arm == "A":
        policy_key, prompt_key = MANIFEST_KEY_A_POLICY_VERSION, MANIFEST_KEY_A_PROMPT_SHA256
    else:
        policy_key, prompt_key = MANIFEST_KEY_FR_POLICY_VERSION, MANIFEST_KEY_FR_PROMPT_SHA256
    fingerprint = inner.fingerprint
    cls = type(inner)
    observed: list[_Observation] = [
        _Observation(_MANIFEST_KEY_PROVIDER, "fingerprint.provider", fingerprint.provider),
        _Observation(_MANIFEST_KEY_MODEL, "fingerprint.model", fingerprint.model),
        _Observation(policy_key, "fingerprint.policy_version", fingerprint.policy_version),
    ]
    if hasattr(cls, _POLICY_VERSION_ATTRIBUTE):
        observed.append(
            _Observation(
                policy_key,
                f"{cls.__name__}.{_POLICY_VERSION_ATTRIBUTE}",
                getattr(inner, _POLICY_VERSION_ATTRIBUTE),
            )
        )
    if hasattr(cls, _SYSTEM_INSTRUCTION_ATTRIBUTE):
        instruction = getattr(inner, _SYSTEM_INSTRUCTION_ATTRIBUTE)
        observed.append(
            _Observation(
                prompt_key,
                f"sha256({cls.__name__}.{_SYSTEM_INSTRUCTION_ATTRIBUTE})",
                _sha256(instruction)
                if isinstance(instruction, str)
                else f"<{type(instruction).__name__}>",
            )
        )
    for attribute in ("reasoning_effort", "_reasoning_effort"):
        if hasattr(inner, attribute):
            observed.append(
                _Observation(_MANIFEST_KEY_REASONING_EFFORT, attribute, getattr(inner, attribute))
            )
            break
    if hasattr(cls, _CONTRASTIVE_PATH_KEY):
        observed.append(
            _Observation(
                _CONTRASTIVE_PATH_KEY,
                f"{cls.__name__}.{_CONTRASTIVE_PATH_KEY}",
                getattr(inner, _CONTRASTIVE_PATH_KEY),
            )
        )
    return tuple(observed)


def _identity_drift(
    manifest: Mapping[str, Any], inner: SemanticReasoner | None = None, *, arm: Arm | None = None
) -> str | None:
    """The first sealed field whose in-process value drifted, with both values; or
    ``None``. Reads this module's own references so a rebinding here is caught, and --
    when ``inner`` is given -- that arm's innermost reasoner as it observably is now
    (``_observed_identity``), so a reasoner that is not the sealed provider / model /
    policy / prompt / effort / path is refused before its call is forwarded."""
    in_process: dict[str, Any] = {
        MANIFEST_KEY_A_PROMPT_SHA256: _sha256(SYSTEM_INSTRUCTION),
        MANIFEST_KEY_FR_PROMPT_SHA256: _sha256(CONTRASTIVE_SYSTEM_INSTRUCTION),
        MANIFEST_KEY_A_POLICY_VERSION: POLICY_VERSION,
        MANIFEST_KEY_FR_POLICY_VERSION: CONTRASTIVE_POLICY_VERSION,
        MANIFEST_KEY_OUTPUT_SCHEMA_SHA256: semantic_output_schema_sha256(),
        MANIFEST_KEY_CEILINGS: {
            "max_frontier_calls": MAX_FRONTIER_CALLS,
            "max_judge_calls": MAX_JUDGE_CALLS,
            "max_semantic_retries": MAX_SEMANTIC_RETRIES,
            "max_same_cell_reruns": MAX_SAME_CELL_RERUNS,
            "max_human_authorizations": MAX_HUMAN_AUTHORIZATIONS,
            "max_provider_cost_usd": MAX_COST_USD,
        },
    }
    for key, actual in in_process.items():
        sealed = manifest.get(key)
        if actual != sealed:
            return f"{key}: in process {actual!r} != manifest {sealed!r}"
    if inner is None or arm is None:
        return None
    expected_contrastive_path = arm != "A"
    for key, source, actual in _observed_identity(inner, arm=arm):
        sealed = expected_contrastive_path if key == _CONTRASTIVE_PATH_KEY else manifest.get(key)
        if actual != sealed:
            return (
                f"{key}: arm {arm} reasoner {type(inner).__name__} {source} observed "
                f"{actual!r} != {'frozen' if key == _CONTRASTIVE_PATH_KEY else 'manifest'} "
                f"{sealed!r}"
            )
    return None


class IdentityGuardReasoner:
    """Wraps one arm's INNER reasoner (installed by ``build_arm_reasoners`` inside the
    recorder and the budget). Refuses construction and, before EVERY forwarded call,
    re-checks the in-process and observed identity against the manifest, raising
    ``IdentityDrift`` on any difference. Otherwise transparent: same fingerprint, and
    the inner adapter's ``receipts`` / ``draft_payloads`` exposed exactly when the inner
    reasoner exposes them (so the runner's measurement contract is unchanged)."""

    def __init__(self, inner: SemanticReasoner, *, arm: Arm, manifest: Mapping[str, Any]) -> None:
        self._inner = inner
        self._arm: Arm = arm
        self._manifest = manifest
        self._refuse_on_drift("at construction")

    @property
    def inner(self) -> SemanticReasoner:
        return self._inner

    @property
    def arm(self) -> Arm:
        return self._arm

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._inner.fingerprint

    def __getattr__(self, name: str) -> Any:
        if name in _PASS_THROUGH_ATTRIBUTES:
            return getattr(self._inner, name)
        raise AttributeError(name)

    def _refuse_on_drift(self, moment: str) -> None:
        drift = _identity_drift(self._manifest, self._inner, arm=self._arm)
        if drift is not None:
            raise IdentityDrift(f"identity drift {moment}; refusing to forward -- {drift}")

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self._refuse_on_drift("before call")
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


def _request_path_sources() -> dict[str, str]:
    """The six real request-path files from the package directory; a missing or
    unreadable one is simply absent so gate 16 fails on its own terms. Nothing is
    fabricated."""
    sources: dict[str, str] = {}
    for name in REQUEST_PATH_MODULES:
        path = REQUEST_PATH_DIR / name
        try:
            sources[name] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return sources


def _evaluate_preflight(
    *,
    out_dir: Path,
    frozen_sha: str,
    git: GitCliLike,
    commands: CommandRunnerLike,
    observed_grpc_dns_resolver: str | None,
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
        request_path_sources=_request_path_sources(),
        leakage=leakage,
        observed_grpc_dns_resolver=observed_grpc_dns_resolver,
    )
    return _Preflight(gates, leakage, manifest)


def _preflight_document(
    result: _Preflight, *, frozen_sha: str, observed_grpc_dns_resolver: str | None
) -> dict[str, Any]:
    """Exactly the document ``write_preflight`` writes (kept in step by test): a failed
    preflight is ``run_status = ABORTED_PREFLIGHT`` and ``frontier_calls = 0``."""
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "frozen_sha": frozen_sha,
        "all_passed": result.passed,
        "run_status": None if result.passed else RunStatus.ABORTED_PREFLIGHT.value,
        "frontier_calls": 0,
        "gates": [
            gate.model_copy(update={"detail": redact_secrets(gate.detail)}).model_dump(mode="json")
            for gate in result.gates
        ],
        "leakage": result.leakage.model_dump(mode="json"),
        "observed_grpc_dns_resolver": observed_grpc_dns_resolver,
    }


# --------------------------------------------------------------------------- zero-run result


def _not_run(*, arm: Arm, t: int, position: int, project_id: str) -> CellRecord:
    """A structural NOT_RUN cell, the shape of the runner's own fill: nothing shown,
    nothing admitted, nothing measured, nothing recorded."""
    return CellRecord(
        arm=arm,
        t=t,
        position=position,
        status="NOT_RUN",
        error=None,
        project_id=project_id,
        evidence_ids_shown=(),
        requests=(),
        reference_snapshots=(),
        stage_decisions=((), ()),
        neighborhood=(),
        claim_neighborhood=(),
        pending_supersede_judgment_ids=(),
        root_designations=(),
        eligible_targets=None,
        authorizations=(),
        measurements=(),
        receipts=(),
        draft_payloads=(),
        state_snapshot=None,
        view_snapshot=None,
        ledger=(),
    )


def _captured_summary(
    arm: PersistentArm,
    project_id: str,
    reasoner: BudgetedReasoner | None,
    cells: Sequence[CellRecord],
) -> ArmSummary:
    """An arm summarised from the cell records the runner handed over before it raised:
    the last captured ledger/state/view (empty when it never advanced), the roots it
    designated, its eligible-target snapshots and authorizations so far, and whatever
    request records and bound reference snapshots the wrappers hold (none when no
    reasoner ever existed). Never replays."""
    own = [cell for cell in cells if cell.arm == arm]
    with_state = [cell for cell in own if cell.state_snapshot is not None]
    last_state = with_state[-1].state_snapshot if with_state else None
    with_view = [cell for cell in own if cell.view_snapshot is not None]
    last_view = with_view[-1].view_snapshot if with_view else None
    state = last_state if last_state is not None else IntentState(project_id=project_id)
    roots: dict[Locus, RootDesignation] = {
        root.locus: root for cell in own for root in cell.root_designations
    }
    # A captured state without a captured view means view derivation already failed
    # for it once; this runs inside a failure handler, so it is not derived again.
    if last_view is not None:
        view = last_view
    elif last_state is None:
        view = derive_view(state.semantic)
    else:
        view = CurrentSemanticView()
    eligible: tuple[EligibleTargets, ...] = tuple(
        cell.eligible_targets for cell in own if cell.eligible_targets is not None
    )
    authorizations: tuple[AuthorizationRecord, ...] = tuple(
        record for cell in own for record in cell.authorizations
    )
    return ArmSummary(
        arm=arm,
        project_id=project_id,
        roots=roots,
        ledger=with_state[-1].ledger if with_state else (),
        final_state=state,
        final_view=view,
        replay=None,
        eligible_targets=eligible,
        authorizations=authorizations,
        requests=() if reasoner is None else reasoner.recording.records,
        reference_snapshots=() if reasoner is None else reasoner.snapshots,
    )


def _aborted_runtime_result(
    *,
    error: str,
    budget: ExperimentBudget | None,
    arms: ArmReasoners | None,
    cells: Sequence[CellRecord] = (),
) -> RunResult:
    """``ABORTED_RUNTIME`` from whatever was captured: the run never started (missing
    key, factory raise, identity refusal at construction) or the runner itself raised
    outside its per-cell catch. ``cells`` are the records the runner produced before
    that (in schedule order); only the schedule positions they do not cover become
    ``NOT_RUN``. Whatever the budget and wrappers hold is preserved. Used ONLY before a
    real ``RunResult`` exists -- never for a raw-preservation failure after the run."""
    captured = {cell.position: cell for cell in cells}
    filled = tuple(
        captured.get(position)
        or _not_run(
            arm=arm,
            t=t,
            position=position,
            project_id=_PERSISTENT_PROJECT_IDS.get(arm) or r_project_id(t),
        )
        for position, (t, arm) in enumerate(ARM_SCHEDULE)
    )
    return RunResult(
        status=RunStatus.ABORTED_RUNTIME,
        error=error,
        cells=filled,
        f=_captured_summary("F", F_PROJECT_ID, None if arms is None else arms.f, filled),
        a=_captured_summary("A", A_PROJECT_ID, None if arms is None else arms.a, filled),
        r_cells={cell.t: cell for cell in filled if cell.arm == "R"},
        budget=(budget if budget is not None else ExperimentBudget()).snapshot(),
        measurements=tuple(row for cell in filled for row in cell.measurements),
        schedule=ARM_SCHEDULE,
    )


def _error_text(exc: BaseException) -> str:
    """``type: message`` only, redacted -- the key never reaches an artifact."""
    return redact_secrets(f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- live run


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mint(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _persist(out_dir: Path, run: RunResult, *, gates: tuple[GateResult, ...]) -> int | None:
    """The one raw write: ``integrity_verdicts`` over the SAME gate tuple written to
    ``preflight.json``, then ``write_run_artifacts`` exactly once. On any failure the
    writer is never called again, no replacement run is built, the run is not mutated
    and ``preflight.json`` is left as it is; the failure is printed redacted and the
    exit code returned: 4 when frontier calls were consumed, 2 when none were."""
    try:
        verdicts = integrity_verdicts(run, preflight_gates=gates)
        write_run_artifacts(out_dir, run, verdicts)
    except Exception as exc:  # noqa: BLE001 - reported, never retried
        frontier_calls = run.budget.frontier_calls
        _say(f"RAW ARTIFACT PRESERVATION FAILED: {_error_text(exc)}")
        _say(f"frontier_calls={frontier_calls}")
        return EXIT_ABORTED if frontier_calls > 0 else EXIT_REFUSED
    return None


def _live(
    *,
    out_dir: Path,
    frozen_sha: str,
    env: Mapping[str, str],
    reasoner_factory: ReasonerFactory,
    git: GitCliLike,
    commands: CommandRunnerLike,
    observed_grpc_dns_resolver: str | None,
) -> int:
    _read_seal(out_dir)
    existing = existing_raw_artifacts(out_dir)
    if existing:
        raise _Refused(
            f"raw artifact(s) already exist under {out_dir}: {list(existing)}; this "
            "experiment identity has already been run or its preflight preserved -- never rerun"
        )
    result = _evaluate_preflight(
        out_dir=out_dir,
        frozen_sha=frozen_sha,
        git=git,
        commands=commands,
        observed_grpc_dns_resolver=observed_grpc_dns_resolver,
    )
    gates = result.gates
    write_preflight(
        out_dir,
        gates,
        frozen_sha=frozen_sha,
        leakage=result.leakage,
        observed_grpc_dns_resolver=observed_grpc_dns_resolver,
    )
    _say(f"preflight: {'PASS' if result.passed else 'FAIL'} ({len(gates)} gates)")
    if not result.passed:
        for gate in gates:
            if not gate.passed:
                _say(f"  FAILED {gate.name}: {gate.detail}")
        _say(f"status: {RunStatus.ABORTED_PREFLIGHT.value} (0 calls)")
        return EXIT_PREFLIGHT_FAILED

    api_key = env.get(API_KEY_ENV, "")
    if not api_key:
        run = _aborted_runtime_result(error=MISSING_API_KEY, budget=None, arms=None)
        failure = _persist(out_dir, run, gates=gates)
        if failure is not None:
            return failure
        _say(f"status: {run.status.value} ({run.error}; 0 calls)")
        return EXIT_ABORTED

    # Construction, identity wrapping, budget wrapping and the run share one catch: a
    # client bootstrap failure or a construction-time identity refusal is an unhandled
    # runtime failure (spec §16) and must be recorded like any other. Never retried.
    budget: ExperimentBudget | None = None
    arms: ArmReasoners | None = None
    progress: list[CellRecord] = []
    manifest = result.manifest
    try:
        inner_f, inner_a, inner_r = reasoner_factory(api_key=api_key)
        del api_key
        guarded_f = IdentityGuardReasoner(inner_f, arm="F", manifest=manifest)
        guarded_a = IdentityGuardReasoner(inner_a, arm="A", manifest=manifest)
        guarded_r = IdentityGuardReasoner(inner_r, arm="R", manifest=manifest)
        budget = ExperimentBudget()
        arms = build_arm_reasoners(
            inner_f=guarded_f, inner_a=guarded_a, inner_r=guarded_r, budget=budget
        )
        run = run_experiment(reasoners=arms, clock=_utc_now, id_factory=_mint, progress=progress)
    except KeyboardInterrupt:
        run = _aborted_runtime_result(error=_INTERRUPTED, budget=budget, arms=arms, cells=progress)
    except Exception as exc:  # noqa: BLE001 - recorded as ABORTED_RUNTIME, never retried
        run = _aborted_runtime_result(
            error=_error_text(exc), budget=budget, arms=arms, cells=progress
        )
    failure = _persist(out_dir, run, gates=gates)
    if failure is not None:
        return failure
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
        description="9P3 long-horizon bounded-memory experiment: preflight, or one gated live run."
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
        help="preflight, then one live run (requires explicit architect authorization)",
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
    environment: Mapping[str, str] = env if env is not None else os.environ
    # Observed exactly once, in both modes, before any gate; never set or normalised.
    observed_grpc_dns_resolver: str | None = environment.get(GRPC_DNS_RESOLVER_ENV)
    try:
        if args.preflight_only:
            result = _evaluate_preflight(
                out_dir=out_dir,
                frozen_sha=args.frozen_sha,
                git=git_cli,
                commands=runner,
                observed_grpc_dns_resolver=observed_grpc_dns_resolver,
            )
            document = pretty_json(
                _preflight_document(
                    result,
                    frozen_sha=args.frozen_sha,
                    observed_grpc_dns_resolver=observed_grpc_dns_resolver,
                )
            )
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
            commands=runner,
            observed_grpc_dns_resolver=observed_grpc_dns_resolver,
        )
    except _Refused as refusal:
        _say(f"REFUSED: {refusal}")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())

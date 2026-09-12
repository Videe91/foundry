"""Scientific preflight for the 9P2 unseen-lifecycle experiment (spec §15; C2).

``preflight`` evaluates the twenty spec §15 gates, in order, before any reasoner is
constructed, and returns one ``GateResult`` per gate. A gate never raises: one that
cannot be evaluated is a failed gate whose ``detail`` carries the reason. The CLI
(T7) writes the results to ``preflight.json`` and refuses to start unless
``all_passed`` holds. No gate tests network reachability.

Gate semantics, in ``GATE_NAMES`` order:

1.  ``head_equals_final_seal`` (Controller Ruling 5) -- HEAD is the seal commit, the
    seal's only parent is the manifest's ``harness_code_sha``, and the seal changed
    exactly the two preregistration files (``PREREGISTRATION_FILES``).
2.  ``worktree_clean`` -- ``git.dirty()`` is empty.
3.  ``seal_descends_from_frozen_core`` -- ``FROZEN_CORE_SHA`` is an ancestor of the seal.
4.  ``core_paths_unchanged_since_frozen_core`` -- nothing under ``CORE_PATH_PREFIXES``
    changed between frozen core and the seal.
5-9. policy identity -- the in-process adapter constants (a FRESH sha256 of each
    instruction string and ``semantic_output_schema_sha256()``) equal the adapter's
    pasted literals, the spec literals restated here, AND the manifest's values.
10. ``f_calls_per_delta_is_2`` -- frozen production ``CALLS_PER_DELTA == 2``.
11. ``a_two_calls_no_retry`` -- the Arm A source (injected ``ablation.py`` when supplied,
    else the sibling file) parsed with ``ast`` has exactly two ``propose_and_submit``
    Call nodes, NEITHER enclosed at any depth by a ``For``/``AsyncFor``/``While``,
    a comprehension (list/set/dict/generator) or a ``Try``/``TryStar`` node; no
    ``try`` statement anywhere; no identifier containing ``retry``. Two call SITES
    under a loop are not two CALLS. Docstrings and comments are prose, not code, and
    are not scanned; ``ABLATION_CALLS_PER_DELTA`` must also equal 2.
12. ``r_uses_fresh_ledger_per_t`` -- the injected ``runner.py`` source must contain at
    least one ``FunctionDef`` whose name contains ``reconstruction`` that (a) has a
    parameter named ``t`` and (b) constructs ``InMemoryEventStore()`` in its own body
    NOT enclosed by any loop/comprehension node; and (c) no ``InMemoryEventStore()``
    construction anywhere in ``runner.py`` may be enclosed by a loop/comprehension.
    A store built once and handed to per-T governors in a loop therefore fails, as
    does a store built under a loop. Static and deliberately simple; a missing or
    unparsable runner source FAILS (C2: never silently skip). T5 implements to this
    contract (see ``_r_uses_fresh_ledger``).
13. ``evidence_manifest_frozen`` -- ``evidence_records()`` equals the manifest's
    ``evidence`` (ids, kind, refs, lineage, timestamps, scope, hashes, byte lengths,
    order and count).
14. ``arm_schedule_frozen`` -- ``ARM_SCHEDULE`` equals the manifest's ``arm_schedule``.
15. ``ceilings_frozen`` -- timeline ceilings and the manifest's ``ceilings`` both equal
    the spec §12 literals (24 calls, 0 judge calls, 16 authorizations, $8.00).
16. ``answer_key_not_imported_by_request_path`` -- ``request_path_import_gate`` over the
    injected sources: every ``REQUIRED_REQUEST_PATH_MODULES`` key must be present and
    parsable, and no supplied source may import ``expectations`` in any form or a
    grading helper by name.
17. ``contrastive_leakage_gate_passes`` -- the supplied ``LeakageResult`` passed, its
    prompt hashes are the frozen ones, its needle-set sha equals the manifest's, and
    the on-disk expectations bytes (parsed, canonicalised) hash to the manifest's
    ``expectations_sha256``. The expectations check lives here rather than in gate 13
    because both are seal identity of grading data, not evidence.
18-19. regression commands -- exactly ``TRACK_A_REGRESSION_ARGV`` and
    ``SCOPE_CLOSURE_REGRESSION_ARGV`` run through the injected ``CommandRunnerLike``;
    pass iff exit code 0.
20. ``historical_9p_artifacts_unchanged`` -- nothing under any of
    ``HISTORICAL_9P_ARTIFACT_DIRS`` (both previous 9P experiment directories; spec
    §15.20) changed between frozen core and the seal.

Law of this module: it decides nothing semantic and originates no scientific value;
every expected value is a frozen literal, a timeline constant, or a sealed manifest
field. Git and command execution are injected behind protocols; this module never
shells out and never constructs a provider client. It may import ``expectations``
because it never enters the provider request path.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final, Protocol

from pydantic import Field

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
    semantic_output_schema_sha256,
)
from foundry.application.incremental_assimilation import CALLS_PER_DELTA
from foundry.domain.common import FrozenModel
from foundry.experiments.contrastive_unseen import expectations as expectations_module
from foundry.experiments.contrastive_unseen.ablation import ABLATION_CALLS_PER_DELTA
from foundry.experiments.contrastive_unseen.leakage import LeakageResult
from foundry.experiments.contrastive_unseen.timeline import (
    ARM_SCHEDULE,
    FROZEN_CORE_SHA,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    evidence_records,
)

__all__ = [
    "A_POLICY_VERSION_FROZEN",
    "A_PROMPT_SHA256_FROZEN",
    "CEILING_KEYS",
    "CORE_PATH_PREFIXES",
    "EXPERIMENT_ARTIFACT_DIR",
    "FR_POLICY_VERSION_FROZEN",
    "FR_PROMPT_SHA256_FROZEN",
    "GATE_NAMES",
    "HISTORICAL_9P_ARTIFACT_DIRS",
    "HISTORICAL_9P_ARTIFACT_DIR",
    "LOCKED_CEILINGS",
    "MANIFEST_KEY_ARM_SCHEDULE",
    "MANIFEST_KEY_A_POLICY_VERSION",
    "MANIFEST_KEY_A_PROMPT_SHA256",
    "MANIFEST_KEY_CEILINGS",
    "MANIFEST_KEY_EVIDENCE",
    "MANIFEST_KEY_EXPECTATIONS_SHA256",
    "MANIFEST_KEY_FR_POLICY_VERSION",
    "MANIFEST_KEY_FR_PROMPT_SHA256",
    "MANIFEST_KEY_HARNESS_CODE_SHA",
    "MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256",
    "MANIFEST_KEY_OUTPUT_SCHEMA_SHA256",
    "OUTPUT_SCHEMA_SHA256_FROZEN",
    "PREREGISTRATION_FILES",
    "REQUIRED_MANIFEST_KEYS",
    "REQUIRED_REQUEST_PATH_MODULES",
    "SCOPE_CLOSURE_REGRESSION_ARGV",
    "TRACK_A_REGRESSION_ARGV",
    "CommandRunnerLike",
    "GateResult",
    "GitCliLike",
    "all_passed",
    "canonical_sha256",
    "preflight",
    "request_path_import_gate",
]

# --------------------------------------------------------------------------- constants

GATE_NAMES: Final[tuple[str, ...]] = (
    "head_equals_final_seal",
    "worktree_clean",
    "seal_descends_from_frozen_core",
    "core_paths_unchanged_since_frozen_core",
    "fr_policy_is_9p2",
    "fr_prompt_hash_frozen",
    "a_policy_is_9p",
    "a_prompt_hash_frozen",
    "output_schema_hash_frozen",
    "f_calls_per_delta_is_2",
    "a_two_calls_no_retry",
    "r_uses_fresh_ledger_per_t",
    "evidence_manifest_frozen",
    "arm_schedule_frozen",
    "ceilings_frozen",
    "answer_key_not_imported_by_request_path",
    "contrastive_leakage_gate_passes",
    "track_a_regression_passes",
    "scope_closure_regression_passes",
    "historical_9p_artifacts_unchanged",
)

# Spec §15 items 5-9 / Global Constraints 5-6, restated as pasted literals so a drift
# in the adapter's own literals is caught too.
FR_POLICY_VERSION_FROZEN: Final = "intent-v2-9p2-v1"
FR_PROMPT_SHA256_FROZEN: Final = "a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410"
A_POLICY_VERSION_FROZEN: Final = "intent-v2-9p-v4"
A_PROMPT_SHA256_FROZEN: Final = "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1"
OUTPUT_SCHEMA_SHA256_FROZEN: Final = (
    "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
)

EXPERIMENT_ARTIFACT_DIR: Final = (
    "docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/"
)
PREREGISTRATION_FILES: Final[tuple[str, ...]] = (
    EXPERIMENT_ARTIFACT_DIR + "manifest.json",
    EXPERIMENT_ARTIFACT_DIR + "expectations.json",
)
HISTORICAL_9P_ARTIFACT_DIR: Final = (
    "docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/"
)
"""The 9P v2 directory the sealed manifest names (``historical_9p_artifact_dir``); its
meaning is part of the manifest contract and is unchanged."""
HISTORICAL_9P_ARTIFACT_DIRS: Final[tuple[str, ...]] = (
    HISTORICAL_9P_ARTIFACT_DIR,
    "docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/",
)
"""Every previous 9P experiment directory gate 20 protects (spec §15.20). The
2026-09-11 intent-v2 self-dogfood directory is not 9P evidence and is not listed."""
CORE_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "src/foundry/domain/",
    "src/foundry/application/",
    "src/foundry/ports/",
    "src/foundry/adapters/",
)

REQUIRED_REQUEST_PATH_MODULES: Final[tuple[str, ...]] = (
    "timeline.py",
    "designation.py",
    "authority.py",
    "ablation.py",
    "records.py",
    "runner.py",
)

TRACK_A_REGRESSION_ARGV: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "pytest",
    "-q",
    "tests/unit/test_9p2_track_a_regression.py",
)
SCOPE_CLOSURE_REGRESSION_ARGV: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "pytest",
    "-q",
    "tests/unit/test_incremental_assimilation.py",
    "-k",
    "shared_predecessor_never_widens_call_two_into_another_scope or "
    "project_wide_address_remains_eligible_for_a_scoped_delta",
)

# Manifest keys (T6 produces them; the names are defined here, once).
MANIFEST_KEY_HARNESS_CODE_SHA: Final = "harness_code_sha"
MANIFEST_KEY_FR_POLICY_VERSION: Final = "fr_policy_version"
MANIFEST_KEY_FR_PROMPT_SHA256: Final = "fr_prompt_sha256"
MANIFEST_KEY_A_POLICY_VERSION: Final = "a_policy_version"
MANIFEST_KEY_A_PROMPT_SHA256: Final = "a_prompt_sha256"
MANIFEST_KEY_OUTPUT_SCHEMA_SHA256: Final = "output_schema_sha256"
MANIFEST_KEY_ARM_SCHEDULE: Final = "arm_schedule"
MANIFEST_KEY_CEILINGS: Final = "ceilings"
MANIFEST_KEY_EVIDENCE: Final = "evidence"
MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256: Final = "leakage_needle_set_sha256"
MANIFEST_KEY_EXPECTATIONS_SHA256: Final = "expectations_sha256"
REQUIRED_MANIFEST_KEYS: Final[tuple[str, ...]] = (
    MANIFEST_KEY_HARNESS_CODE_SHA,
    MANIFEST_KEY_FR_POLICY_VERSION,
    MANIFEST_KEY_FR_PROMPT_SHA256,
    MANIFEST_KEY_A_POLICY_VERSION,
    MANIFEST_KEY_A_PROMPT_SHA256,
    MANIFEST_KEY_OUTPUT_SCHEMA_SHA256,
    MANIFEST_KEY_ARM_SCHEDULE,
    MANIFEST_KEY_CEILINGS,
    MANIFEST_KEY_EVIDENCE,
    MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256,
    MANIFEST_KEY_EXPECTATIONS_SHA256,
)

CEILING_KEYS: Final[tuple[str, ...]] = (
    "max_frontier_calls",
    "max_judge_calls",
    "max_human_authorizations",
    "max_cost_usd",
)
LOCKED_CEILINGS: Final[dict[str, int | float]] = {
    "max_frontier_calls": 24,
    "max_judge_calls": 0,
    "max_human_authorizations": 16,
    "max_cost_usd": 8.0,
}
"""Spec §12 / Global Constraint 9, as pasted literals."""

_EXPECTATIONS_MODULE: Final = "foundry.experiments.contrastive_unseen.expectations"
_PACKAGE_MODULE: Final = "foundry.experiments.contrastive_unseen"
_GRADING_HELPER_NAMES: Final[frozenset[str]] = frozenset(expectations_module.__all__)
_RUNNER_R_FUNCTION_MARKER: Final = "reconstruction"
"""Gate 12 looks for a ``FunctionDef`` whose name contains this (T5:
``run_reconstruction_step`` / ``_reconstruction_step``)."""
_LOOP_NODES: Final = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


# --------------------------------------------------------------------------- protocols


class GitCliLike(Protocol):
    """Read-only Git facts. Implemented by the CLI over a subprocess; faked in tests."""

    def head(self) -> str: ...

    def dirty(self) -> str:
        """``status --porcelain`` output; empty when clean."""
        ...

    def parents(self, sha: str) -> tuple[str, ...]: ...

    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]: ...

    def show_bytes(self, sha: str, path: str) -> bytes: ...


class CommandRunnerLike(Protocol):
    """Runs one argv and returns ``(exit_code, combined_output)``."""

    def run(self, argv: tuple[str, ...]) -> tuple[int, str]: ...


class GateResult(FrozenModel):
    name: str = Field(min_length=1)
    passed: bool
    detail: str


_Gate = Callable[[], tuple[bool, str]]


# --------------------------------------------------------------------------- entry


def preflight(
    *,
    git: GitCliLike,
    commands: CommandRunnerLike,
    frozen_sha: str,
    manifest: Mapping[str, Any],
    expectations_bytes: bytes,
    request_path_sources: Mapping[str, str],
    leakage: LeakageResult,
) -> tuple[GateResult, ...]:
    """Evaluate every gate in ``GATE_NAMES`` order. Never raises."""
    gates: dict[str, _Gate] = {
        "head_equals_final_seal": lambda: _head_equals_final_seal(git, frozen_sha, manifest),
        "worktree_clean": lambda: _worktree_clean(git.dirty()),
        "seal_descends_from_frozen_core": lambda: _descends(git, frozen_sha),
        "core_paths_unchanged_since_frozen_core": lambda: _no_paths_under(
            git, frozen_sha, CORE_PATH_PREFIXES, "core"
        ),
        "fr_policy_is_9p2": lambda: _policy(
            "F/R policy",
            actual=CONTRASTIVE_POLICY_VERSION,
            frozen=FR_POLICY_VERSION_FROZEN,
            manifest=manifest,
            key=MANIFEST_KEY_FR_POLICY_VERSION,
        ),
        "fr_prompt_hash_frozen": lambda: _prompt_hash(
            "F/R prompt",
            instruction=CONTRASTIVE_SYSTEM_INSTRUCTION,
            adapter_literal=CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
            frozen=FR_PROMPT_SHA256_FROZEN,
            manifest=manifest,
            key=MANIFEST_KEY_FR_PROMPT_SHA256,
        ),
        "a_policy_is_9p": lambda: _policy(
            "A policy",
            actual=POLICY_VERSION,
            frozen=A_POLICY_VERSION_FROZEN,
            manifest=manifest,
            key=MANIFEST_KEY_A_POLICY_VERSION,
        ),
        "a_prompt_hash_frozen": lambda: _prompt_hash(
            "A prompt",
            instruction=SYSTEM_INSTRUCTION,
            adapter_literal=SYSTEM_INSTRUCTION_SHA256,
            frozen=A_PROMPT_SHA256_FROZEN,
            manifest=manifest,
            key=MANIFEST_KEY_A_PROMPT_SHA256,
        ),
        "output_schema_hash_frozen": lambda: _output_schema_hash(manifest),
        "f_calls_per_delta_is_2": _f_calls_per_delta,
        "a_two_calls_no_retry": lambda: _a_two_calls_no_retry(request_path_sources),
        "r_uses_fresh_ledger_per_t": lambda: _r_uses_fresh_ledger(request_path_sources),
        "evidence_manifest_frozen": lambda: _evidence_frozen(manifest),
        "arm_schedule_frozen": lambda: _arm_schedule_frozen(manifest),
        "ceilings_frozen": lambda: _ceilings_frozen(manifest),
        "answer_key_not_imported_by_request_path": lambda: request_path_import_gate(
            request_path_sources
        ),
        "contrastive_leakage_gate_passes": lambda: _leakage_and_expectations(
            leakage, manifest, expectations_bytes
        ),
        "track_a_regression_passes": lambda: _command(commands, TRACK_A_REGRESSION_ARGV),
        "scope_closure_regression_passes": lambda: _command(
            commands, SCOPE_CLOSURE_REGRESSION_ARGV
        ),
        "historical_9p_artifacts_unchanged": lambda: _no_paths_under(
            git, frozen_sha, HISTORICAL_9P_ARTIFACT_DIRS, "historical 9P artifact"
        ),
    }
    return tuple(_evaluate(name, gates[name]) for name in GATE_NAMES)


def all_passed(results: Iterable[GateResult]) -> bool:
    """True iff there is at least one result and every result passed."""
    results = tuple(results)
    return bool(results) and all(r.passed for r in results)


def canonical_sha256(value: Any) -> str:
    """sha256 of ``json.dumps(value, sort_keys=True, separators=(",", ":"),
    ensure_ascii=False)`` encoded as UTF-8 -- the seal's canonical form."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- evaluation


def _evaluate(name: str, gate: _Gate) -> GateResult:
    try:
        passed, detail = gate()
    except Exception as exc:  # noqa: BLE001 - a gate that cannot run is a failed gate
        return GateResult(name=name, passed=False, detail=f"could not evaluate: {_safe(exc)}")
    return GateResult(name=name, passed=passed, detail=detail)


def _safe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _manifest_value(manifest: Mapping[str, Any], key: str) -> Any:
    if key not in manifest:
        raise KeyError(f"manifest lacks required key {key!r}")
    return manifest[key]


def _json_round_trip(value: Any) -> Any:
    """Tuples become lists and enums become their values, as on disk."""
    return json.loads(json.dumps(value, sort_keys=True))


# --------------------------------------------------------------------------- gates 1-4


def _head_equals_final_seal(
    git: GitCliLike, frozen_sha: str, manifest: Mapping[str, Any]
) -> tuple[bool, str]:
    head = git.head()
    if head != frozen_sha:
        return False, f"HEAD {head!r} != final seal {frozen_sha!r}"
    harness_sha = _manifest_value(manifest, MANIFEST_KEY_HARNESS_CODE_SHA)
    parents = git.parents(frozen_sha)
    if parents != (harness_sha,):
        return False, (
            f"seal {frozen_sha} parents {list(parents)} != exactly the manifest "
            f"harness_code_sha [{harness_sha!r}]"
        )
    changed = tuple(sorted(git.changed_paths(harness_sha, frozen_sha)))
    if changed != tuple(sorted(PREREGISTRATION_FILES)):
        return False, (
            f"seal changed {list(changed)}; expected exactly {list(PREREGISTRATION_FILES)}"
        )
    return True, (
        f"HEAD == seal {frozen_sha}; parent == harness {harness_sha}; seal adds exactly "
        f"{list(PREREGISTRATION_FILES)}"
    )


def _worktree_clean(status: str) -> tuple[bool, str]:
    if status.strip() == "":
        return True, "worktree clean"
    return False, f"worktree dirty:\n{status.strip()}"


def _descends(git: GitCliLike, frozen_sha: str) -> tuple[bool, str]:
    if git.is_ancestor(FROZEN_CORE_SHA, frozen_sha):
        return True, f"frozen core {FROZEN_CORE_SHA} is an ancestor of seal {frozen_sha}"
    return False, f"frozen core {FROZEN_CORE_SHA} is NOT an ancestor of seal {frozen_sha}"


def _no_paths_under(
    git: GitCliLike, frozen_sha: str, prefixes: tuple[str, ...], label: str
) -> tuple[bool, str]:
    changed = git.changed_paths(FROZEN_CORE_SHA, frozen_sha)
    offenders = [p for p in changed if any(p.startswith(prefix) for prefix in prefixes)]
    if offenders:
        return False, f"{label} paths changed since frozen core: {offenders}"
    return True, f"no {label} path changed since frozen core ({len(changed)} paths checked)"


# --------------------------------------------------------------------------- gates 5-9


def _policy(
    label: str, *, actual: str, frozen: str, manifest: Mapping[str, Any], key: str
) -> tuple[bool, str]:
    sealed = _manifest_value(manifest, key)
    if actual != frozen:
        return False, f"{label} in process {actual!r} != frozen {frozen!r}"
    if sealed != frozen:
        return False, f"{label} manifest[{key!r}] {sealed!r} != frozen {frozen!r}"
    return True, f"{label} {frozen!r} (in process == frozen == manifest)"


def _prompt_hash(
    label: str,
    *,
    instruction: str,
    adapter_literal: str,
    frozen: str,
    manifest: Mapping[str, Any],
    key: str,
) -> tuple[bool, str]:
    computed = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    sealed = _manifest_value(manifest, key)
    if computed != frozen:
        return False, f"{label} sha256 computed {computed} != frozen {frozen}"
    if adapter_literal != frozen:
        return False, f"{label} adapter literal {adapter_literal} != frozen {frozen}"
    if sealed != frozen:
        return False, f"{label} manifest[{key!r}] {sealed!r} != frozen {frozen}"
    return True, f"{label} sha256 {frozen} (computed == adapter literal == manifest)"


def _output_schema_hash(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    computed = semantic_output_schema_sha256()
    sealed = _manifest_value(manifest, MANIFEST_KEY_OUTPUT_SCHEMA_SHA256)
    frozen = OUTPUT_SCHEMA_SHA256_FROZEN
    if computed != frozen:
        return False, f"output schema sha256 computed {computed} != frozen {frozen}"
    if frozen != SEMANTIC_OUTPUT_SCHEMA_SHA256:
        return False, f"adapter literal {SEMANTIC_OUTPUT_SCHEMA_SHA256} != frozen {frozen}"
    if sealed != frozen:
        return False, (
            f"manifest[{MANIFEST_KEY_OUTPUT_SCHEMA_SHA256!r}] {sealed!r} != frozen {frozen}"
        )
    return True, f"output schema sha256 {frozen} (computed == adapter literal == manifest)"


# --------------------------------------------------------------------------- gates 10-12


def _f_calls_per_delta() -> tuple[bool, str]:
    if CALLS_PER_DELTA == 2:
        return True, "CALLS_PER_DELTA == 2"
    return False, f"CALLS_PER_DELTA == {CALLS_PER_DELTA}, expected 2"


def _source_or_sibling(sources: Mapping[str, str], name: str) -> tuple[str, str]:
    if name in sources:
        return sources[name], f"injected {name}"
    path = Path(__file__).with_name(name)
    return path.read_text(encoding="utf-8"), f"sibling {path.name}"


def _identifiers(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, ast.keyword):
            if node.arg is not None:
                names.append(node.arg)
        elif isinstance(node, ast.alias):
            names.append(node.asname or node.name)
    return names


def _enclosing_nodes(tree: ast.AST) -> dict[int, list[ast.AST]]:
    """Map ``id(node)`` -> its ancestors (outermost first) for every node in ``tree``."""
    ancestors: dict[int, list[ast.AST]] = {}

    def visit(node: ast.AST, path: list[ast.AST]) -> None:
        ancestors[id(node)] = path
        for child in ast.iter_child_nodes(node):
            visit(child, [*path, node])

    visit(tree, [])
    return ancestors


def _enclosed_by(
    node: ast.AST, ancestors: Mapping[int, list[ast.AST]], kinds: tuple[type[ast.AST], ...]
) -> ast.AST | None:
    """The nearest ancestor of ``node`` that is one of ``kinds``, or ``None``."""
    for ancestor in reversed(ancestors[id(node)]):
        if isinstance(ancestor, kinds):
            return ancestor
    return None


def _line(node: ast.AST) -> object:
    return getattr(node, "lineno", "?")


def _is_propose_and_submit(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "propose_and_submit"
    )


def _constructs_store(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "InMemoryEventStore"
    return isinstance(func, ast.Attribute) and func.attr == "InMemoryEventStore"


def _a_two_calls_no_retry(sources: Mapping[str, str]) -> tuple[bool, str]:
    """Gate 11 contract: exactly two ``propose_and_submit`` Call nodes, neither enclosed
    (at any depth) by a loop, a comprehension, or a ``try``; no ``try`` statement; no
    identifier containing ``retry``; ``ABLATION_CALLS_PER_DELTA == 2``."""
    source, origin = _source_or_sibling(sources, "ablation.py")
    tree = ast.parse(source)
    ancestors = _enclosing_nodes(tree)
    calls = [node for node in ast.walk(tree) if _is_propose_and_submit(node)]
    problems: list[str] = []
    if len(calls) != 2:
        problems.append(f"{len(calls)} propose_and_submit call sites (expected 2)")
    for call in calls:
        enclosing = _enclosed_by(call, ancestors, (*_LOOP_NODES, ast.Try, ast.TryStar))
        if enclosing is not None:
            problems.append(
                f"propose_and_submit at line {_line(call)} is enclosed by a "
                f"loop/comprehension/try node ({type(enclosing).__name__} at line "
                f"{_line(enclosing)})"
            )
    if any(isinstance(node, ast.Try | ast.TryStar) for node in ast.walk(tree)):
        problems.append("a try statement is present")
    retry_names = sorted({n for n in _identifiers(tree) if "retry" in n.casefold()})
    if retry_names:
        problems.append(f"retry identifiers present: {retry_names}")
    if ABLATION_CALLS_PER_DELTA != 2:
        problems.append(f"ABLATION_CALLS_PER_DELTA == {ABLATION_CALLS_PER_DELTA}")
    if problems:
        return False, f"{origin}: " + "; ".join(problems)
    return True, (
        f"{origin}: exactly 2 unlooped propose_and_submit calls, no try, no retry identifier"
    )


def _has_t_parameter(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = function.args
    return any(arg.arg == "t" for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))


def _r_uses_fresh_ledger(sources: Mapping[str, str]) -> tuple[bool, str]:
    """Gate 12 contract (binding for T5's ``runner.py``):

    (a) at least one ``FunctionDef`` whose name contains ``reconstruction`` has a
        parameter named ``t``;
    (b) that function constructs ``InMemoryEventStore()`` in its own body, with the
        construction NOT enclosed by any ``For``/``AsyncFor``/``While``/comprehension
        node (a nested function does not count as the function's own body);
    (c) no ``InMemoryEventStore()`` construction anywhere in ``runner.py`` is enclosed
        by a loop/comprehension node.

    A store built once and handed to per-T governors inside a loop fails (a)/(b); a
    store built under a loop fails (b)/(c). Missing or unparsable source fails.
    """
    if "runner.py" not in sources:
        return False, "runner.py source not supplied; cannot verify Arm R fresh ledger"
    tree = ast.parse(sources["runner.py"])
    ancestors = _enclosing_nodes(tree)

    # (c) first: any looped construction anywhere is a violation on its own.
    looped: list[str] = []
    for node in ast.walk(tree):
        if _constructs_store(node):
            loop = _enclosed_by(node, ancestors, _LOOP_NODES)
            if loop is not None:
                function = _enclosed_by(node, ancestors, (ast.FunctionDef, ast.AsyncFunctionDef))
                where = getattr(function, "name", "<module>")
                looped.append(
                    f"InMemoryEventStore() at line {_line(node)} in {where} is enclosed by "
                    f"a loop/comprehension ({type(loop).__name__} at line {_line(loop)})"
                )
    if looped:
        return False, "runner.py: " + "; ".join(looped)

    r_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and _RUNNER_R_FUNCTION_MARKER in node.name.casefold()
    ]
    if not r_functions:
        return False, (
            f"runner.py has no function whose name contains {_RUNNER_R_FUNCTION_MARKER!r}"
        )
    with_t = [f for f in r_functions if _has_t_parameter(f)]
    if not with_t:
        return False, (
            f"runner.py reconstruction functions {[f.name for f in r_functions]} have no "
            "parameter named 't'"
        )
    fresh: list[str] = []
    for function in with_t:
        for node in ast.walk(function):
            if not _constructs_store(node):
                continue
            owner = _enclosed_by(node, ancestors, (ast.FunctionDef, ast.AsyncFunctionDef))
            if owner is function:
                fresh.append(function.name)
                break
    if not fresh:
        return False, (
            f"runner.py reconstruction functions with a 't' parameter "
            f"{[f.name for f in with_t]} do not construct InMemoryEventStore() in their own "
            "body outside any loop"
        )
    return True, (
        f"runner.py constructs InMemoryEventStore() unlooped inside per-T {fresh}; no "
        "looped store construction anywhere"
    )


# --------------------------------------------------------------------------- gates 13-15


def _evidence_frozen(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    sealed = _json_round_trip(_manifest_value(manifest, MANIFEST_KEY_EVIDENCE))
    loaded = _json_round_trip([r.model_dump(mode="json") for r in evidence_records()])
    if not isinstance(sealed, list):
        return False, f"manifest[{MANIFEST_KEY_EVIDENCE!r}] is not a list"
    if len(sealed) != len(loaded):
        return False, f"{len(loaded)} evidence records in process, {len(sealed)} sealed"
    for index, (actual, expected) in enumerate(zip(loaded, sealed, strict=True)):
        if actual != expected:
            return False, f"evidence index {index}: in process {actual} != sealed {expected}"
    return True, f"{len(loaded)} evidence records equal the sealed manifest, in order"


def _arm_schedule_frozen(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    sealed = _json_round_trip(_manifest_value(manifest, MANIFEST_KEY_ARM_SCHEDULE))
    expected = _json_round_trip([[t, arm] for t, arm in ARM_SCHEDULE])
    if sealed != expected:
        return False, f"manifest arm_schedule {sealed} != ARM_SCHEDULE {expected}"
    return True, f"arm schedule equals ARM_SCHEDULE ({len(expected)} entries)"


def _ceilings_frozen(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    sealed = _manifest_value(manifest, MANIFEST_KEY_CEILINGS)
    in_process: dict[str, int | float] = {
        "max_frontier_calls": MAX_FRONTIER_CALLS,
        "max_judge_calls": MAX_JUDGE_CALLS,
        "max_human_authorizations": MAX_HUMAN_AUTHORIZATIONS,
        "max_cost_usd": MAX_COST_USD,
    }
    if in_process != LOCKED_CEILINGS:
        return False, f"timeline ceilings {in_process} != locked {LOCKED_CEILINGS}"
    if not isinstance(sealed, Mapping):
        return False, f"manifest[{MANIFEST_KEY_CEILINGS!r}] is not a mapping"
    if set(sealed) != set(CEILING_KEYS):
        return False, f"manifest ceiling keys {sorted(sealed)} != {sorted(CEILING_KEYS)}"
    for key in CEILING_KEYS:
        if sealed[key] != LOCKED_CEILINGS[key]:
            return False, (
                f"manifest ceilings[{key!r}]={sealed[key]!r} != locked {LOCKED_CEILINGS[key]!r}"
            )
    return True, f"ceilings equal locked values {LOCKED_CEILINGS}"


# --------------------------------------------------------------------------- gate 16


def _forbidden_import(node: ast.Import | ast.ImportFrom) -> str | None:
    """The offending import statement text, or ``None`` when the import is clean."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == _EXPECTATIONS_MODULE or alias.name.startswith(
                _EXPECTATIONS_MODULE + "."
            ):
                return f"import {alias.name}"
        return None
    module = node.module or ""
    names = [alias.name for alias in node.names]
    if node.level == 0:
        is_expectations = module == _EXPECTATIONS_MODULE
        is_package = module == _PACKAGE_MODULE
    else:
        is_expectations = module == "expectations" or module.endswith(".expectations")
        is_package = (
            module == "" or module == "contrastive_unseen" or module.endswith(".contrastive_unseen")
        )
    if is_expectations:
        return f"from {'.' * node.level}{module} import {', '.join(names)}"
    if is_package:
        offenders = [n for n in names if n == "expectations" or n in _GRADING_HELPER_NAMES]
        if offenders:
            return f"from {'.' * node.level}{module} import {', '.join(offenders)}"
    return None


def request_path_import_gate(sources: Mapping[str, str]) -> tuple[bool, str]:
    """C2 gate core: every required request-path module must be supplied and parsable,
    and no supplied source may import the answer key in any form."""
    missing = [name for name in REQUIRED_REQUEST_PATH_MODULES if name not in sources]
    if missing:
        return False, f"request-path sources missing: {missing}"
    offenders: list[str] = []
    for name in sorted(sources):
        try:
            tree = ast.parse(sources[name])
        except SyntaxError as exc:
            offenders.append(f"{name}: unparsable ({exc.msg} at line {exc.lineno})")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                offending = _forbidden_import(node)
                if offending is not None:
                    offenders.append(f"{name}: {offending}")
    if offenders:
        return False, "answer-key import in request path: " + "; ".join(offenders)
    return True, f"no answer-key import in {sorted(sources)}"


# --------------------------------------------------------------------------- gate 17


def _leakage_and_expectations(
    leakage: LeakageResult, manifest: Mapping[str, Any], expectations_bytes: bytes
) -> tuple[bool, str]:
    if not leakage.passed:
        return False, (
            f"leakage gate FAILED: needle {leakage.matched_needle!r} in skeleton "
            f"{leakage.matched_skeleton_id!r}"
        )
    if leakage.fr_prompt_sha256 != FR_PROMPT_SHA256_FROZEN:
        return False, f"leakage scanned F/R prompt {leakage.fr_prompt_sha256}, not the frozen one"
    if leakage.a_prompt_sha256 != A_PROMPT_SHA256_FROZEN:
        return False, f"leakage scanned A prompt {leakage.a_prompt_sha256}, not the frozen one"
    sealed_needles = _manifest_value(manifest, MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256)
    if leakage.needle_set_sha256 != sealed_needles:
        return False, (
            f"needle set sha256 {leakage.needle_set_sha256} != manifest {sealed_needles!r}"
        )
    sealed_expectations = _manifest_value(manifest, MANIFEST_KEY_EXPECTATIONS_SHA256)
    try:
        parsed = json.loads(expectations_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return False, f"expectations bytes unparsable: {_safe(exc)}"
    actual_expectations = canonical_sha256(parsed)
    if actual_expectations != sealed_expectations:
        return False, (
            f"expectations canonical sha256 {actual_expectations} != manifest "
            f"{sealed_expectations!r}"
        )
    return True, (
        f"leakage PASS over {len(leakage.skeletons)} skeletons; needle set "
        f"{leakage.needle_set_sha256}; expectations {actual_expectations}"
    )


# --------------------------------------------------------------------------- gates 18-19


def _command(commands: CommandRunnerLike, argv: tuple[str, ...]) -> tuple[bool, str]:
    code, output = commands.run(argv)
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    if code == 0:
        return True, f"{' '.join(argv)} -> exit 0: {tail}"
    return False, f"{' '.join(argv)} -> exit {code}: {tail}"

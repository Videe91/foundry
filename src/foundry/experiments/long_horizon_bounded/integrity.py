"""Scientific preflight (23 gates) and post-run integrity verdicts I1-I15 for the 9P3
long-horizon bounded-memory experiment (spec §12, §15, §18.3; T5 brief).

``preflight`` evaluates the 9P2 gates carried forward (spec §12, last paragraph) plus
the 9P3-specific ones, in ``GATE_NAMES`` order, before any reasoner is constructed,
and returns one ``GateResult`` per gate. A gate never raises: one that cannot be
evaluated is a failed gate whose ``detail`` carries the reason. Gate semantics, in
order:

1.  ``head_equals_final_seal`` -- HEAD is the seal commit, the seal's only parent is
    the manifest's ``harness_code_sha``, and the seal changed exactly the two
    preregistration files (``PREREGISTRATION_FILES``).
2.  ``worktree_clean`` -- ``git.dirty()`` is empty.
3.  ``seal_descends_from_frozen_core`` -- ``FROZEN_CORE_SHA`` is an ancestor of the seal.
4.  ``core_paths_unchanged_since_frozen_core`` -- nothing under ``CORE_PATH_PREFIXES``
    changed between the frozen core and the seal.
5-9. policy identity -- the in-process adapter constants (a FRESH sha256 of each
    instruction string and ``semantic_output_schema_sha256()``) equal the adapter's
    pasted literals, the ``protocol`` literals, the literals restated here AND the
    manifest's values.
10. ``f_calls_per_delta_is_2`` -- frozen production ``CALLS_PER_DELTA == 2``.
11. ``a_two_calls_no_retry`` -- the reused, unmodified 9P2 ``ablation.py`` (or an
    injected ``ablation.py`` source) passes the frozen 9P2 AST contract: exactly two
    unlooped ``propose_and_submit`` calls, no ``try``, no retry identifier. Evaluated by
    the frozen 9P2 gate function itself, imported -- never re-implemented.
12. ``r_uses_fresh_ledger_per_t`` -- the injected ``runner.py`` source passes the frozen
    9P2 AST contract (a ``reconstruction`` function with a ``t`` parameter constructing
    ``InMemoryEventStore()`` unlooped in its own body; no looped store construction
    anywhere). Evaluated by the frozen 9P2 gate function, imported.
13. ``evidence_manifest_frozen`` -- ``timeline.evidence_records()`` equals the manifest's
    ``evidence`` (192 records; ids, kind, refs, lineage, timestamps, scope, hashes, byte
    lengths, order and count).
14. ``arm_schedule_frozen`` -- ``protocol.ARM_SCHEDULE`` equals the manifest's
    ``arm_schedule``.
15. ``ceilings_frozen`` -- the ``protocol`` ceilings and the manifest's ``ceilings`` both
    equal the spec §17 literals (``LOCKED_CEILINGS``).
16. ``answer_key_not_imported_by_request_path`` -- ``leakage.request_path_import_gate``
    over the injected sources: all six ``REQUEST_PATH_MODULES`` present and parsable,
    no answer-key import in any form.
17. ``leakage_gate_passes`` (I14 ⊙) -- the supplied ``LeakageResult`` passed, its prompt
    hashes are the frozen ones, its typed needle-set sha equals the manifest's, and the
    on-disk expectations bytes (parsed, canonicalised) hash to the manifest's
    ``expectations_sha256``.
18-19. regression commands -- exactly the frozen 9P2 ``TRACK_A_REGRESSION_ARGV`` and
    ``SCOPE_CLOSURE_REGRESSION_ARGV`` run through the injected ``CommandRunnerLike``;
    pass iff exit code 0.
20. ``historical_artifacts_unchanged`` -- ``HISTORICAL_PRESERVATION_BASE_SHA`` (the
    approved 9P3 design commit; never HEAD) is an ancestor of the seal and, for every
    directory in ``HISTORICAL_ARTIFACT_DIRS``, ``git.tree_sha(base, dir) ==
    git.tree_sha(seal, dir) == manifest["historical_artifact_tree_hashes"][dir]``.
21. ``grpc_dns_resolver_is_native`` -- the observed live-process ``GRPC_DNS_RESOLVER``
    (injected by the CLI; this module never reads the environment) and the manifest's
    ``grpc_dns_resolver`` both equal ``"native"`` by exact string equality.
22. ``predecessor_raw_evidence_unchanged`` -- ``PREDECESSOR_RAW_EVIDENCE_SHA`` is an
    ancestor of the seal, no path under ``PREDECESSOR_ARTIFACT_DIR`` changed between it
    and the seal, and the manifest's ``predecessor_raw_evidence_sha`` equals the literal.
23. ``r_cumulative_context_within_bounds`` (I13 ⊙) -- ``r_context_within_bounds``: a
    fresh ``SemanticGovernor`` per T ingests ``reconstruction_corpus(t)`` and the real
    Call-1 ``assemble_assimilation_request`` is compiled for T1..T16 with no reasoner;
    every ``comparison_context_character_count`` is reported; any
    ``ContextUnsupported`` or a T16 count above ``R_CONTEXT_CHAR_BOUND`` fails. The
    persistent T1 requests (F production path, A ablation path) are compiled too.

``integrity_verdicts`` computes the fifteen spec §12 verdicts I1-I15 from a
``RunResult`` alone (durable ledger events are canonical; ``CellRecord.authorizations``
is never the sole source of authority evidence -- clarification 6) plus the preflight
gate tuple, from which I13 consumes exactly ``GATE_I13_NAME`` and I14 exactly
``GATE_I14_NAME`` (absent or duplicated -> ``PreflightGateMissing``; present but failed
-> FAIL). Post-run integrity never re-runs the leakage gate. Every verdict fails
closed: one that cannot be evaluated (including a ``ReferenceSnapshotMismatch`` raised
by the I10 binding check) is a FAIL whose detail carries the exception. ``passed`` is
typed ``bool | None`` for the artifact layer; this module never produces ``None``.

I10 (request-only reference law, the frozen adapter law): ``request_only_reference_check``
binds each ``RequestRecord`` to its ``RequestReferenceSnapshot`` exactly (same call
identity, same ordered tuples, creating-judgment tuple length) and requires every id a
model-originated proposal refers to -- evidence, address, claim, ``SUPERSEDE`` target --
to resolve against the snapshot's request-only sets. Because the snapshot's tuples were
copied from the request object before it was forwarded, an id minted while wrapping a
sibling draft of the same provider response can never appear in them.

Law of this module: it decides nothing semantic and originates no scientific value;
every expected value is a frozen literal, a ``protocol``/``timeline`` constant or a
sealed manifest field. Git and command execution are injected behind protocols, and so
is the one environment observation gate 21 needs; this module never shells out, never
reads or writes the process environment and never constructs a provider client or a
reasoner. It may import ``expectations`` because it never enters the provider request
path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Final, NamedTuple, Protocol

from pydantic import Field

from foundry.adapters.memory.event_store import InMemoryEventStore
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
from foundry.application.assimilation_context import (
    ContextUnsupported,
    assemble_assimilation_request,
)
from foundry.application.contrastive_context import comparison_context_character_count
from foundry.application.incremental_assimilation import CALLS_PER_DELTA
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import FrozenModel
from foundry.domain.events import (
    EventType,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
)
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    DistinctProposal,
    EquivalentProposal,
    JudgmentKind,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
    proposal_signature,
)
from foundry.experiments.contrastive_unseen import integrity as contrastive_integrity
from foundry.experiments.contrastive_unseen.ablation import assemble_ablation_call1
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.contrastive_unseen.integrity import (
    SCOPE_CLOSURE_REGRESSION_ARGV,
    TRACK_A_REGRESSION_ARGV,
    CommandRunnerLike,
    GateResult,
    all_passed,
)
from foundry.experiments.contrastive_unseen.records import RequestRecord
from foundry.experiments.long_horizon_bounded.authority import HUMAN_FINGERPRINT
from foundry.experiments.long_horizon_bounded.leakage import (
    LeakageResult,
    request_path_import_gate,
)
from foundry.experiments.long_horizon_bounded.protocol import (
    A_POLICY_VERSION,
    A_PROJECT_ID,
    A_PROMPT_SHA256,
    ARM_SCHEDULE,
    AUTHORITY_CHECKPOINTS,
    F_PROJECT_ID,
    FR_POLICY_VERSION,
    FR_PROMPT_SHA256,
    FROZEN_CORE_SHA,
    GRPC_DNS_RESOLVER_ENV,
    GRPC_DNS_RESOLVER_FROZEN,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    MAX_SAME_CELL_RERUNS,
    MAX_SEMANTIC_RETRIES,
    OUTPUT_SCHEMA_SHA256,
    Arm,
    r_project_id,
)
from foundry.experiments.long_horizon_bounded.runner import (
    ArmSummary,
    CellRecord,
    ReferenceSnapshotMismatch,
    RequestReferenceSnapshot,
    RunResult,
    RunStatus,
)
from foundry.experiments.long_horizon_bounded.timeline import (
    LOCI,
    SCOPE,
    VERSION_COUNT,
    evidence_records,
    persistent_delta,
    reconstruction_corpus,
)
from foundry.experiments.longitudinal.scoring import replay_matches

__all__ = [
    "A_POLICY_VERSION_FROZEN",
    "A_PROMPT_SHA256_FROZEN",
    "CEILING_KEYS",
    "CORE_PATH_PREFIXES",
    "EXPERIMENT_ARTIFACT_DIR",
    "FR_POLICY_VERSION_FROZEN",
    "FR_PROMPT_SHA256_FROZEN",
    "GATE_I13_NAME",
    "GATE_I14_NAME",
    "GATE_NAMES",
    "HISTORICAL_ARTIFACT_DIRS",
    "HISTORICAL_PRESERVATION_BASE_SHA",
    "LOCKED_CEILINGS",
    "MANIFEST_KEY_ARM_SCHEDULE",
    "MANIFEST_KEY_A_POLICY_VERSION",
    "MANIFEST_KEY_A_PROMPT_SHA256",
    "MANIFEST_KEY_CEILINGS",
    "MANIFEST_KEY_EVIDENCE",
    "MANIFEST_KEY_EXPECTATIONS_SHA256",
    "MANIFEST_KEY_FR_POLICY_VERSION",
    "MANIFEST_KEY_FR_PROMPT_SHA256",
    "MANIFEST_KEY_GRPC_DNS_RESOLVER",
    "MANIFEST_KEY_HARNESS_CODE_SHA",
    "MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES",
    "MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256",
    "MANIFEST_KEY_OUTPUT_SCHEMA_SHA256",
    "MANIFEST_KEY_PREDECESSOR_RAW_EVIDENCE_SHA",
    "OUTPUT_SCHEMA_SHA256_FROZEN",
    "PREDECESSOR_ARTIFACT_DIR",
    "PREDECESSOR_RAW_EVIDENCE_SHA",
    "PREREGISTRATION_FILES",
    "REQUIRED_MANIFEST_KEYS",
    "R_CONTEXT_CHAR_BOUND",
    "VERDICT_IDS",
    "CallJudgments",
    "CommandRunnerLike",
    "GateResult",
    "GitCliLike",
    "IntegrityVerdict",
    "PreflightGateMissing",
    "all_passed",
    "integrity_verdicts",
    "preflight",
    "r_context_within_bounds",
    "request_only_reference_check",
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
    "leakage_gate_passes",
    "track_a_regression_passes",
    "scope_closure_regression_passes",
    "historical_artifacts_unchanged",
    "grpc_dns_resolver_is_native",
    "predecessor_raw_evidence_unchanged",
    "r_cumulative_context_within_bounds",
)
GATE_I13_NAME: Final = "r_cumulative_context_within_bounds"
GATE_I14_NAME: Final = "leakage_gate_passes"

HISTORICAL_PRESERVATION_BASE_SHA: Final = "43e5ea60cd92b700db4c58314a5ce68c50028169"
"""The approved 9P3 design commit; every directory below exists there as accepted
evidence. The baseline is never computed from the mutable harness HEAD."""
HISTORICAL_ARTIFACT_DIRS: Final[tuple[str, ...]] = (
    "docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/",
    "docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood/",
    "docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/",
    "docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/",
)
PREDECESSOR_RAW_EVIDENCE_SHA: Final = "201198f60c51e16269451e7d582027361d7e8a24"
"""The commit recording the 9P2 v3 raw evidence; gate 22 requires it as an ancestor."""
PREDECESSOR_ARTIFACT_DIR: Final = (
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/"
)

# Global Constraint 7 identities, restated as pasted literals so a drift in the adapter's
# or ``protocol``'s own literals is caught too.
FR_POLICY_VERSION_FROZEN: Final = "intent-v2-9p2-v1"
FR_PROMPT_SHA256_FROZEN: Final = "a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410"
A_POLICY_VERSION_FROZEN: Final = "intent-v2-9p-v4"
A_PROMPT_SHA256_FROZEN: Final = "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1"
OUTPUT_SCHEMA_SHA256_FROZEN: Final = (
    "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
)

EXPERIMENT_ARTIFACT_DIR: Final = (
    "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/"
)
PREREGISTRATION_FILES: Final[tuple[str, ...]] = (
    EXPERIMENT_ARTIFACT_DIR + "manifest.json",
    EXPERIMENT_ARTIFACT_DIR + "expectations.json",
)
CORE_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "src/foundry/domain/",
    "src/foundry/application/",
    "src/foundry/ports/",
    "src/foundry/adapters/",
)

R_CONTEXT_CHAR_BOUND: Final[int] = 100_000
"""Spec §12 I13: R's T16 canonical comparison context must not exceed this."""

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
MANIFEST_KEY_GRPC_DNS_RESOLVER: Final = "grpc_dns_resolver"
MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES: Final = "historical_artifact_tree_hashes"
MANIFEST_KEY_PREDECESSOR_RAW_EVIDENCE_SHA: Final = "predecessor_raw_evidence_sha"
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
    MANIFEST_KEY_GRPC_DNS_RESOLVER,
    MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES,
    MANIFEST_KEY_PREDECESSOR_RAW_EVIDENCE_SHA,
)

CEILING_KEYS: Final[tuple[str, ...]] = (
    "max_frontier_calls",
    "max_judge_calls",
    "max_semantic_retries",
    "max_same_cell_reruns",
    "max_human_authorizations",
    "max_provider_cost_usd",
)
LOCKED_CEILINGS: Final[dict[str, int | float]] = {
    "max_frontier_calls": 96,
    "max_judge_calls": 0,
    "max_semantic_retries": 0,
    "max_same_cell_reruns": 0,
    "max_human_authorizations": 48,
    "max_provider_cost_usd": 10.0,
}
"""Spec §17 / Global Constraint 8, as pasted literals."""

VERDICT_IDS: Final[tuple[str, ...]] = tuple(f"I{n}" for n in range(1, 16))

_HUMAN_AUTHORITY_REASON: Final = "HUMAN_AUTHORITY"
_HELD_ROUTES: Final[frozenset[AdmissionRoute]] = frozenset(
    {AdmissionRoute.REQUIRE_SECOND_LENS, AdmissionRoute.REQUIRE_HUMAN}
)
_PERSISTENT_ARMS: Final[tuple[Arm, ...]] = ("F", "A")
_ALL_ARMS: Final[tuple[Arm, ...]] = ("F", "A", "R")
_CONTRASTIVE_ARMS: Final[tuple[Arm, ...]] = ("F", "R")
_EXPECTED_CALL_NUMBERS: Final[tuple[int, ...]] = (1, 2)
_PREFLIGHT_CLOCK: Final = datetime(2000, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- protocols


class GitCliLike(Protocol):
    """Read-only Git facts. Implemented by the CLI over a subprocess; faked in tests.

    A superset of the 9P2 protocol: ``tree_sha`` is ``git rev-parse <sha>:<path>``."""

    def head(self) -> str: ...

    def dirty(self) -> str:
        """``status --porcelain`` output; empty when clean."""
        ...

    def parents(self, sha: str) -> tuple[str, ...]: ...

    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]: ...

    def show_bytes(self, sha: str, path: str) -> bytes: ...

    def tree_sha(self, sha: str, path: str) -> str: ...


_Gate = Callable[[], tuple[bool, str]]


# --------------------------------------------------------------------------- preflight


def preflight(
    *,
    git: GitCliLike,
    commands: CommandRunnerLike,
    frozen_sha: str,
    manifest: Mapping[str, Any],
    expectations_bytes: bytes,
    request_path_sources: Mapping[str, str],
    leakage: LeakageResult,
    observed_grpc_dns_resolver: str | None,
) -> tuple[GateResult, ...]:
    """Evaluate every gate in ``GATE_NAMES`` order. Never raises; constructs no
    reasoner or provider client.

    ``observed_grpc_dns_resolver`` is the live process's ``GRPC_DNS_RESOLVER`` exactly
    as the CLI observed it (``None`` when unset); this function never reads it itself."""
    gates: dict[str, _Gate] = {
        "head_equals_final_seal": lambda: _head_equals_final_seal(git, frozen_sha, manifest),
        "worktree_clean": lambda: _worktree_clean(git.dirty()),
        "seal_descends_from_frozen_core": lambda: _descends(git, frozen_sha),
        "core_paths_unchanged_since_frozen_core": lambda: _core_paths_unchanged(git, frozen_sha),
        "fr_policy_is_9p2": lambda: _policy(
            "F/R policy",
            actual=CONTRASTIVE_POLICY_VERSION,
            protocol=FR_POLICY_VERSION,
            frozen=FR_POLICY_VERSION_FROZEN,
            manifest=manifest,
            key=MANIFEST_KEY_FR_POLICY_VERSION,
        ),
        "fr_prompt_hash_frozen": lambda: _prompt_hash(
            "F/R prompt",
            instruction=CONTRASTIVE_SYSTEM_INSTRUCTION,
            adapter_literal=CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
            protocol=FR_PROMPT_SHA256,
            frozen=FR_PROMPT_SHA256_FROZEN,
            manifest=manifest,
            key=MANIFEST_KEY_FR_PROMPT_SHA256,
        ),
        "a_policy_is_9p": lambda: _policy(
            "A policy",
            actual=POLICY_VERSION,
            protocol=A_POLICY_VERSION,
            frozen=A_POLICY_VERSION_FROZEN,
            manifest=manifest,
            key=MANIFEST_KEY_A_POLICY_VERSION,
        ),
        "a_prompt_hash_frozen": lambda: _prompt_hash(
            "A prompt",
            instruction=SYSTEM_INSTRUCTION,
            adapter_literal=SYSTEM_INSTRUCTION_SHA256,
            protocol=A_PROMPT_SHA256,
            frozen=A_PROMPT_SHA256_FROZEN,
            manifest=manifest,
            key=MANIFEST_KEY_A_PROMPT_SHA256,
        ),
        "output_schema_hash_frozen": lambda: _output_schema_hash(manifest),
        "f_calls_per_delta_is_2": _f_calls_per_delta,
        "a_two_calls_no_retry": lambda: contrastive_integrity._a_two_calls_no_retry(
            request_path_sources
        ),
        "r_uses_fresh_ledger_per_t": lambda: contrastive_integrity._r_uses_fresh_ledger(
            request_path_sources
        ),
        "evidence_manifest_frozen": lambda: _evidence_frozen(manifest),
        "arm_schedule_frozen": lambda: _arm_schedule_frozen(manifest),
        "ceilings_frozen": lambda: _ceilings_frozen(manifest),
        "answer_key_not_imported_by_request_path": lambda: request_path_import_gate(
            request_path_sources
        ),
        "leakage_gate_passes": lambda: _leakage_and_expectations(
            leakage, manifest, expectations_bytes
        ),
        "track_a_regression_passes": lambda: _command(commands, TRACK_A_REGRESSION_ARGV),
        "scope_closure_regression_passes": lambda: _command(
            commands, SCOPE_CLOSURE_REGRESSION_ARGV
        ),
        "historical_artifacts_unchanged": lambda: _historical_artifacts_unchanged(
            git, frozen_sha, manifest
        ),
        "grpc_dns_resolver_is_native": lambda: _grpc_dns_resolver_is_native(
            observed_grpc_dns_resolver, manifest
        ),
        "predecessor_raw_evidence_unchanged": lambda: _predecessor_raw_evidence_unchanged(
            git, frozen_sha, manifest
        ),
        "r_cumulative_context_within_bounds": r_context_within_bounds,
    }
    return tuple(_evaluate(name, gates[name]) for name in GATE_NAMES)


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


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def _core_paths_unchanged(git: GitCliLike, frozen_sha: str) -> tuple[bool, str]:
    changed = git.changed_paths(FROZEN_CORE_SHA, frozen_sha)
    offenders = [p for p in changed if any(p.startswith(prefix) for prefix in CORE_PATH_PREFIXES)]
    if offenders:
        return False, f"core paths changed since frozen core: {offenders}"
    return True, f"no core path changed since frozen core ({len(changed)} paths checked)"


# --------------------------------------------------------------------------- gates 5-9


def _policy(
    label: str,
    *,
    actual: str,
    protocol: str,
    frozen: str,
    manifest: Mapping[str, Any],
    key: str,
) -> tuple[bool, str]:
    sealed = _manifest_value(manifest, key)
    if actual != frozen:
        return False, f"{label} in process {actual!r} != frozen {frozen!r}"
    if protocol != frozen:
        return False, f"{label} protocol literal {protocol!r} != frozen {frozen!r}"
    if sealed != frozen:
        return False, f"{label} manifest[{key!r}] {sealed!r} != frozen {frozen!r}"
    return True, f"{label} {frozen!r} (in process == protocol == frozen == manifest)"


def _prompt_hash(
    label: str,
    *,
    instruction: str,
    adapter_literal: str,
    protocol: str,
    frozen: str,
    manifest: Mapping[str, Any],
    key: str,
) -> tuple[bool, str]:
    computed = _sha256(instruction)
    sealed = _manifest_value(manifest, key)
    if computed != frozen:
        return False, f"{label} sha256 computed {computed} != frozen {frozen}"
    if adapter_literal != frozen:
        return False, f"{label} adapter literal {adapter_literal} != frozen {frozen}"
    if protocol != frozen:
        return False, f"{label} protocol literal {protocol} != frozen {frozen}"
    if sealed != frozen:
        return False, f"{label} manifest[{key!r}] {sealed!r} != frozen {frozen}"
    return True, (f"{label} sha256 {frozen} (computed == adapter literal == protocol == manifest)")


def _output_schema_hash(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    computed = semantic_output_schema_sha256()
    sealed = _manifest_value(manifest, MANIFEST_KEY_OUTPUT_SCHEMA_SHA256)
    frozen = OUTPUT_SCHEMA_SHA256_FROZEN
    if computed != frozen:
        return False, f"output schema sha256 computed {computed} != frozen {frozen}"
    if frozen != SEMANTIC_OUTPUT_SCHEMA_SHA256:
        return False, f"adapter literal {SEMANTIC_OUTPUT_SCHEMA_SHA256} != frozen {frozen}"
    if frozen != OUTPUT_SCHEMA_SHA256:
        return False, f"protocol literal {OUTPUT_SCHEMA_SHA256} != frozen {frozen}"
    if sealed != frozen:
        return False, (
            f"manifest[{MANIFEST_KEY_OUTPUT_SCHEMA_SHA256!r}] {sealed!r} != frozen {frozen}"
        )
    return True, (
        f"output schema sha256 {frozen} (computed == adapter literal == protocol == manifest)"
    )


# --------------------------------------------------------------------------- gates 10-15


def _f_calls_per_delta() -> tuple[bool, str]:
    if CALLS_PER_DELTA == 2:
        return True, "CALLS_PER_DELTA == 2"
    return False, f"CALLS_PER_DELTA == {CALLS_PER_DELTA}, expected 2"


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
        "max_semantic_retries": MAX_SEMANTIC_RETRIES,
        "max_same_cell_reruns": MAX_SAME_CELL_RERUNS,
        "max_human_authorizations": MAX_HUMAN_AUTHORIZATIONS,
        "max_provider_cost_usd": MAX_COST_USD,
    }
    if in_process != LOCKED_CEILINGS:
        return False, f"protocol ceilings {in_process} != locked {LOCKED_CEILINGS}"
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


# --------------------------------------------------------------------------- gate 17


def _leakage_and_expectations(
    leakage: LeakageResult, manifest: Mapping[str, Any], expectations_bytes: bytes
) -> tuple[bool, str]:
    if not leakage.passed:
        return False, (
            f"leakage gate FAILED: needle {leakage.matched_needle!r} "
            f"({leakage.matched_needle_kind}) in skeleton {leakage.matched_skeleton_id!r}"
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
        f"leakage PASS over {len(leakage.skeletons)} skeletons; typed needle set "
        f"{leakage.needle_set_sha256}; expectations {actual_expectations}"
    )


# --------------------------------------------------------------------------- gates 18-19


def _command(commands: CommandRunnerLike, argv: tuple[str, ...]) -> tuple[bool, str]:
    code, output = commands.run(argv)
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    if code == 0:
        return True, f"{' '.join(argv)} -> exit 0: {tail}"
    return False, f"{' '.join(argv)} -> exit {code}: {tail}"


# --------------------------------------------------------------------------- gates 20-22


def _historical_artifacts_unchanged(
    git: GitCliLike, frozen_sha: str, manifest: Mapping[str, Any]
) -> tuple[bool, str]:
    """Gate 20: three-way tree-hash equality per directory against the frozen baseline
    commit (never HEAD), plus the ancestor check."""
    sealed = _manifest_value(manifest, MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES)
    base = HISTORICAL_PRESERVATION_BASE_SHA
    if not git.is_ancestor(base, frozen_sha):
        return False, f"preservation base {base} is NOT an ancestor of seal {frozen_sha}"
    if not isinstance(sealed, Mapping):
        return False, f"manifest[{MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES!r}] is not a mapping"
    for directory in HISTORICAL_ARTIFACT_DIRS:
        if directory not in sealed:
            return False, f"manifest historical tree hashes lack {directory!r}"
        at_base = git.tree_sha(base, directory)
        at_seal = git.tree_sha(frozen_sha, directory)
        if at_seal != at_base:
            return False, (
                f"{directory} tree at seal {at_seal} != tree at preservation base {at_base}"
            )
        if sealed[directory] != at_base:
            return False, (
                f"manifest historical tree hash for {directory} {sealed[directory]!r} != "
                f"tree at preservation base {at_base}"
            )
    return True, (
        f"{len(HISTORICAL_ARTIFACT_DIRS)} historical artifact trees equal at base {base}, "
        f"seal {frozen_sha} and manifest"
    )


def _grpc_dns_resolver_is_native(
    observed: str | None, manifest: Mapping[str, Any]
) -> tuple[bool, str]:
    """Gate 21: exact string equality on both sides; nothing is stripped, casefolded or
    defaulted."""
    frozen = GRPC_DNS_RESOLVER_FROZEN
    if observed != frozen:
        return False, (
            f"observed {GRPC_DNS_RESOLVER_ENV}={observed!r} in the live process environment "
            f"!= frozen {frozen!r}"
        )
    sealed = _manifest_value(manifest, MANIFEST_KEY_GRPC_DNS_RESOLVER)
    if sealed != frozen:
        return False, (
            f"manifest[{MANIFEST_KEY_GRPC_DNS_RESOLVER!r}] {sealed!r} != frozen {frozen!r}"
        )
    return True, f"{GRPC_DNS_RESOLVER_ENV}={frozen} (observed == sealed == frozen)"


def _predecessor_raw_evidence_unchanged(
    git: GitCliLike, frozen_sha: str, manifest: Mapping[str, Any]
) -> tuple[bool, str]:
    """Gate 22: the 9P2 v3 raw-evidence commit is an ancestor of the seal, nothing under
    its directory changed since it, and the manifest names that same commit."""
    sealed = _manifest_value(manifest, MANIFEST_KEY_PREDECESSOR_RAW_EVIDENCE_SHA)
    if not git.is_ancestor(PREDECESSOR_RAW_EVIDENCE_SHA, frozen_sha):
        return False, (
            f"predecessor raw evidence {PREDECESSOR_RAW_EVIDENCE_SHA} is NOT an ancestor of "
            f"seal {frozen_sha}"
        )
    changed = git.changed_paths(PREDECESSOR_RAW_EVIDENCE_SHA, frozen_sha)
    offenders = [p for p in changed if p.startswith(PREDECESSOR_ARTIFACT_DIR)]
    if offenders:
        return False, (
            f"predecessor artifact paths changed since {PREDECESSOR_RAW_EVIDENCE_SHA}: {offenders}"
        )
    if sealed != PREDECESSOR_RAW_EVIDENCE_SHA:
        return False, (
            f"manifest[{MANIFEST_KEY_PREDECESSOR_RAW_EVIDENCE_SHA!r}] {sealed!r} != frozen "
            f"{PREDECESSOR_RAW_EVIDENCE_SHA!r}"
        )
    return True, (
        f"predecessor raw evidence {PREDECESSOR_RAW_EVIDENCE_SHA} is an ancestor of seal "
        f"{frozen_sha}; no path under {PREDECESSOR_ARTIFACT_DIR} changed since it "
        f"({len(changed)} paths checked); manifest names it"
    )


# --------------------------------------------------------------------------- gate 23 (I13)


def _fresh_governor(project_id: str) -> SemanticGovernor:
    return SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=project_id,
        policy=AdmissionPolicy(),
        clock=lambda: _PREFLIGHT_CLOCK,
    )


def r_context_within_bounds() -> tuple[bool, str]:
    """I13 ⊙: compile every R Call-1 request for T1..T16 offline through the real
    assembly path over a fresh governor per T, with no reasoner; report every
    canonical comparison-context character count; fail on ``ContextUnsupported`` or a
    T16 count above ``R_CONTEXT_CHAR_BOUND``. The persistent T1 requests are compiled
    too (spec §12 I13)."""
    counts: dict[int, int] = {}
    try:
        for t in range(1, VERSION_COUNT + 1):
            project_id = r_project_id(t)
            governor = _fresh_governor(project_id)
            corpus = reconstruction_corpus(t, project_id=project_id)
            for item in corpus:
                governor.ingest(item)
            request = assemble_assimilation_request(
                project_id=project_id, delta=corpus, state=governor.state(), scope=SCOPE
            )
            counts[t] = comparison_context_character_count(request.comparison_context)
        f_governor = _fresh_governor(F_PROJECT_ID)
        f_delta = persistent_delta(1, project_id=F_PROJECT_ID)
        for item in f_delta:
            f_governor.ingest(item)
        assemble_assimilation_request(
            project_id=F_PROJECT_ID, delta=f_delta, state=f_governor.state(), scope=SCOPE
        )
        a_governor = _fresh_governor(A_PROJECT_ID)
        a_delta = persistent_delta(1, project_id=A_PROJECT_ID)
        for item in a_delta:
            a_governor.ingest(item)
        assemble_ablation_call1(
            project_id=A_PROJECT_ID, delta=a_delta, state=a_governor.state(), scope=SCOPE
        )
    except ContextUnsupported as exc:
        compiled = ", ".join(f"T{t:02d}={n}" for t, n in counts.items())
        return False, f"offline compilation refused: {_safe(exc)}; compiled so far: {compiled}"
    report = ", ".join(f"T{t:02d}={counts[t]}" for t in sorted(counts))
    t16 = counts[VERSION_COUNT]
    if t16 > R_CONTEXT_CHAR_BOUND:
        return False, (
            f"R T16 comparison context {t16} chars exceeds bound {R_CONTEXT_CHAR_BOUND}; "
            f"counts: {report}"
        )
    return True, (
        f"every R Call-1 request and both persistent T1 requests compile offline; R T16 "
        f"comparison context {t16} <= {R_CONTEXT_CHAR_BOUND} chars; counts: {report}"
    )


# --------------------------------------------------------------------------- I10


class PreflightGateMissing(RuntimeError):
    """A preflight gate a verdict consumes is absent from, or duplicated in, the tuple."""


class IntegrityVerdict(FrozenModel):
    """One spec §12 verdict. ``passed`` is ``None`` only for a verdict a caller records
    as deliberately not evaluated; ``integrity_verdicts`` never produces it."""

    id: str = Field(min_length=1)
    passed: bool | None
    detail: str
    applies_to: tuple[Arm, ...]


class CallJudgments(NamedTuple):
    record: RequestRecord
    snapshot: RequestReferenceSnapshot
    judgments: tuple[SemanticJudgment, ...]
    """The model-originated judgments the governor recorded for this call, in
    submission order."""


class _References(NamedTuple):
    evidence: frozenset[str]
    addresses: frozenset[str]
    claims: frozenset[str]
    targets: frozenset[str]


def _references(judgment: SemanticJudgment) -> _References:
    """Structural read of every id a proposal refers to (no wording)."""
    p = judgment.proposal
    evidence = set(judgment.visible_evidence_ids)
    addresses: set[str] = set()
    claims: set[str] = set()
    targets: set[str] = set()
    match p:
        case CreateAddressProposal():
            evidence |= set(p.candidate.evidence_ids)
        case BindToAddressProposal():
            evidence |= set(p.candidate.evidence_ids)
            addresses.add(p.address_id)
        case AssertClaimProposal():
            evidence |= set(p.evidence_ids)
            addresses.add(p.address_id)
        case SupportsClaimProposal():
            evidence |= set(p.evidence_ids)
            claims.add(p.claim_id)
        case SupersedeProposal():
            targets.add(p.target_judgment_id)
        case ConflictsWithProposal():
            # The adapter's exactly-two draft pair lands in the durable two-field proposal.
            claims |= {p.claim_a, p.claim_b}
        case EquivalentProposal() | DistinctProposal():
            addresses |= {p.address_a, p.address_b}
    return _References(
        frozenset(evidence), frozenset(addresses), frozenset(claims), frozenset(targets)
    )


def _bound(record: RequestRecord, snapshot: RequestReferenceSnapshot) -> None:
    """The snapshot must agree with its RequestRecord exactly (same call identity and
    same tuples, same order) before ``known_claim_creating_judgment_ids`` may be used."""
    if (record.arm, record.t, record.call_number, record.request_sha256) != (
        snapshot.arm,
        snapshot.t,
        snapshot.call_number,
        snapshot.request_sha256,
    ):
        raise ReferenceSnapshotMismatch(
            f"snapshot identity differs from RequestRecord at {record.arm} T{record.t} call "
            f"{record.call_number}"
        )
    if (record.citable_evidence_ids, record.known_address_ids, record.known_claim_ids) != (
        snapshot.citable_evidence_ids,
        snapshot.known_address_ids,
        snapshot.known_claim_ids,
    ):
        raise ReferenceSnapshotMismatch(
            f"snapshot reference tuples differ from RequestRecord at {record.arm} T{record.t} "
            f"call {record.call_number}"
        )
    if len(snapshot.known_claim_creating_judgment_ids) != len(snapshot.known_claim_ids):
        raise ReferenceSnapshotMismatch(
            "creating-judgment tuple length differs from known-claim tuple length"
        )


def request_only_reference_check(calls: tuple[CallJudgments, ...]) -> tuple[bool, str]:
    """I10: every reference of every model-originated judgment resolves against its
    exact request's snapshot; raises ``ReferenceSnapshotMismatch`` when a snapshot is
    not bound to its record (the caller evaluates that as FAIL)."""
    for call in calls:
        _bound(call.record, call.snapshot)
        evidence = frozenset(call.snapshot.citable_evidence_ids)
        addresses = frozenset(call.snapshot.known_address_ids)
        claims = frozenset(call.snapshot.known_claim_ids)
        creating = frozenset(call.snapshot.known_claim_creating_judgment_ids)
        for judgment in call.judgments:
            refs = _references(judgment)
            if not (
                refs.evidence <= evidence
                and refs.addresses <= addresses
                and refs.claims <= claims
                and refs.targets <= creating
            ):
                return False, (
                    f"request-only reference law violated by {judgment.judgment_id} at "
                    f"{call.record.arm} T{call.record.t} call {call.record.call_number}"
                )
    return True, "every reference resolves against its exact request; no same-response id used"


# --------------------------------------------------------------------------- ledger reads


def _ledger_judgments(ledger: Iterable[StoredEvent]) -> dict[str, SemanticJudgment]:
    """``judgment_id -> judgment`` for every recorded judgment, in ledger order."""
    judgments: dict[str, SemanticJudgment] = {}
    for stored in ledger:
        payload = stored.event.payload
        if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED and isinstance(
            payload, SemanticJudgmentPayload
        ):
            judgments[payload.judgment.judgment_id] = payload.judgment
    return judgments


def _ledger_admissions(ledger: Iterable[StoredEvent]) -> dict[str, SemanticAdmissionPayload]:
    """``judgment_id -> latest admission`` in ledger order."""
    admissions: dict[str, SemanticAdmissionPayload] = {}
    for stored in ledger:
        payload = stored.event.payload
        if stored.event.event_type is EventType.SEMANTIC_ADMISSION_DECIDED and isinstance(
            payload, SemanticAdmissionPayload
        ):
            admissions[payload.judgment_id] = payload
    return admissions


def _is_human(judgment: SemanticJudgment) -> bool:
    return judgment.reasoner == HUMAN_FINGERPRINT


def _cell_label(cell: CellRecord) -> str:
    return f"{cell.arm} T{cell.t}"


def _call_label(record: RequestRecord) -> str:
    return f"{record.arm} T{record.t} call {record.call_number}"


def _attempted(run: RunResult) -> tuple[CellRecord, ...]:
    return tuple(cell for cell in run.cells if cell.status != "NOT_RUN")


def _completed(run: RunResult) -> tuple[CellRecord, ...]:
    return tuple(cell for cell in run.cells if cell.status == "COMPLETED")


def _arm_cells(run: RunResult, arm: Arm) -> tuple[CellRecord, ...]:
    return tuple(cell for cell in run.cells if cell.arm == arm)


def _summary(run: RunResult, arm: Arm) -> ArmSummary:
    return run.f if arm == "F" else run.a


def _calls(cell: CellRecord) -> tuple[CallJudgments, ...]:
    """Pair, in order, ``requests[i]`` with ``reference_snapshots[i]`` and the
    model-originated judgments recorded for that call (``stage_decisions[i]``,
    resolved by judgment id in the cell's ledger). A decision whose judgment is not
    in the ledger is a reconciliation failure, raised for the caller to fail closed."""
    judgments = _ledger_judgments(cell.ledger)
    calls: list[CallJudgments] = []
    for index, (record, snapshot) in enumerate(
        zip(cell.requests, cell.reference_snapshots, strict=False)
    ):
        decisions = cell.stage_decisions[index] if index < len(cell.stage_decisions) else ()
        resolved: list[SemanticJudgment] = []
        for decision in decisions:
            judgment = judgments.get(decision.judgment_id)
            if judgment is None:
                raise RuntimeError(
                    f"{_cell_label(cell)}: decision for {decision.judgment_id} has no recorded "
                    "judgment in the cell ledger"
                )
            if _is_human(judgment):
                raise RuntimeError(
                    f"{_cell_label(cell)}: stage decision for {decision.judgment_id} names a "
                    "human judgment; only model-originated judgments are admitted through a call"
                )
            resolved.append(judgment)
        calls.append(CallJudgments(record, snapshot, tuple(resolved)))
    return tuple(calls)


def _ledger_segments(cells: tuple[CellRecord, ...]) -> tuple[tuple[CellRecord, int], ...]:
    """Each cell with a captured ledger and the offset its own segment starts at: for
    a persistent arm the length of the previous captured ledger (one cumulative ledger),
    for R always 0 (every R cell owns a fresh ledger)."""
    segments: list[tuple[CellRecord, int]] = []
    previous = 0
    for cell in cells:
        if not cell.ledger:
            continue
        if cell.arm == "R":
            segments.append((cell, 0))
            continue
        segments.append((cell, previous))
        previous = len(cell.ledger)
    return tuple(segments)


# --------------------------------------------------------------------------- verdicts


def _i1(run: RunResult) -> tuple[bool, str]:
    parts: list[str] = []
    for arm in _PERSISTENT_ARMS:
        roots = _summary(run, arm).roots
        if tuple(roots) != LOCI:
            return False, f"{arm}: roots designated for {list(roots)}, expected {list(LOCI)}"
        undesignated = [locus for locus, root in roots.items() if root.status != "DESIGNATED"]
        if undesignated:
            return False, f"{arm}: undesignated loci {undesignated}"
        addresses = [root.address_id or "" for root in roots.values()]
        if len(set(addresses)) != len(addresses):
            duplicates = sorted({a for a in addresses if addresses.count(a) > 1})
            return (
                False,
                f"{arm}: designated root addresses are not pairwise distinct: {duplicates}",
            )
        parts.append(
            f"{arm}: {len(roots)} designated roots at {len(set(addresses))} distinct addresses"
        )
    return True, "; ".join(parts)


def _i2(run: RunResult) -> tuple[bool, str]:
    completed = _completed(run)
    for cell in completed:
        numbers = tuple(record.call_number for record in cell.requests)
        if numbers != _EXPECTED_CALL_NUMBERS:
            return (
                False,
                f"{_cell_label(cell)} completed with call numbers {numbers}, expected (1, 2)",
            )
        if len(cell.reference_snapshots) != len(cell.requests):
            return False, (
                f"{_cell_label(cell)} completed with {len(cell.reference_snapshots)} reference "
                f"snapshots for {len(cell.requests)} requests"
            )
    return True, f"{len(completed)} completed cells each made exactly calls (1, 2)"


def _i3(run: RunResult) -> tuple[bool, str]:
    for cell in _attempted(run):
        if len(cell.requests) > 2:
            return (
                False,
                f"{_cell_label(cell)} made {len(cell.requests)} calls; a third call is a "
                "retry or phase",
            )
    # Request identity is unique per arm: the rendered request carries no project id, so
    # F T1 Call 1 and R T1 Call 1 legitimately render identically across arms.
    for arm in _ALL_ARMS:
        seen: dict[str, str] = {}
        for cell in _arm_cells(run, arm):
            for record in cell.requests:
                if record.request_sha256 in seen:
                    return False, (
                        f"duplicate request identity {record.request_sha256} at "
                        f"{_call_label(record)} "
                        f"and {seen[record.request_sha256]} (retry shape)"
                    )
                seen[record.request_sha256] = _call_label(record)
    if run.budget.judge_calls != 0:
        return False, f"{run.budget.judge_calls} judge calls recorded; no judge exists"
    return True, "no third call, no duplicate request identity, no judge call"


def _cited_evidence(judgment: SemanticJudgment) -> frozenset[str]:
    return _references(judgment).evidence


def _i4(run: RunResult) -> tuple[bool, str]:
    checked = 0
    for cell in _attempted(run):
        for call in _calls(cell):
            citable = frozenset(call.record.citable_evidence_ids)
            for judgment in call.judgments:
                extra = sorted(_cited_evidence(judgment) - citable)
                if extra:
                    return False, (
                        f"{judgment.judgment_id} at {_call_label(call.record)} cites {extra} "
                        "outside the request evidence"
                    )
                checked += 1
    return True, f"{checked} model-originated judgments cite only their request's evidence"


def _i5(run: RunResult) -> tuple[bool, str]:
    checked = 0
    for cell in _attempted(run):
        if cell.arm not in _CONTRASTIVE_ARMS:
            continue
        for call in _calls(cell):
            historical = frozenset(call.record.historical_comparison_evidence_ids) - frozenset(
                call.record.citable_evidence_ids
            )
            for judgment in call.judgments:
                cited = sorted(_cited_evidence(judgment) & historical)
                if cited:
                    return False, (
                        f"{judgment.judgment_id} at {_call_label(call.record)} cites "
                        "comparison-only "
                        f"predecessor evidence {cited}"
                    )
                checked += 1
    return True, f"{checked} F/R judgments never cite a comparison-only predecessor"


def _address_in_scope(scope: tuple[str, ...]) -> bool:
    return scope == () or SCOPE in scope


def _i6(run: RunResult) -> tuple[bool, str]:
    checked = 0
    for cell in _attempted(run):
        state = cell.state_snapshot
        if state is None:
            continue
        semantic = state.semantic
        for record in cell.requests:
            known = frozenset(record.known_address_ids)
            for address_id in record.known_address_ids:
                address = semantic.addresses.get(address_id)
                if address is None:
                    return (
                        False,
                        f"{_call_label(record)}: known address {address_id} is not in the ledger",
                    )
                if not _address_in_scope(address.scope):
                    return False, (
                        f"{_call_label(record)}: known address {address_id} with scope "
                        f"{list(address.scope)} is not eligible for ({SCOPE!r},)"
                    )
            for claim_id in record.known_claim_ids:
                claim = semantic.claims.get(claim_id)
                if claim is None:
                    return (
                        False,
                        f"{_call_label(record)}: known claim {claim_id} is not in the ledger",
                    )
                if claim.address_id not in known:
                    return False, (
                        f"{_call_label(record)}: known claim {claim_id} sits at "
                        f"{claim.address_id}, "
                        "outside the request's known addresses"
                    )
            checked += 1
        if len(cell.requests) == 2:
            touched = (
                cell.claim_neighborhood if cell.arm in _CONTRASTIVE_ARMS else cell.neighborhood
            )
            shown = frozenset(cell.requests[1].known_address_ids)
            outside = sorted(frozenset(touched) - shown)
            if outside:
                return False, (
                    f"{_cell_label(cell)}: touched addresses {outside} are outside Call 2's "
                    "known addresses"
                )
    return (
        True,
        f"{checked} requests: every known address in scope, every known claim and touched "
        "address within known addresses",
    )


def _i7(run: RunResult) -> tuple[bool, str]:
    checked = 0
    for arm in _PERSISTENT_ARMS:
        ledger = _summary(run, arm).ledger
        admissions = _ledger_admissions(ledger)
        for judgment_id, judgment in _ledger_judgments(ledger).items():
            if judgment.kind is not JudgmentKind.SUPERSEDE or _is_human(judgment):
                continue
            admission = admissions.get(judgment_id)
            if admission is not None and admission.route is AdmissionRoute.APPLY:
                return False, f"{arm}: model-originated SUPERSEDE {judgment_id} was routed APPLY"
            checked += 1
    return True, f"{checked} model-originated SUPERSEDE proposals, none applied by the model"


def _applied_supersessions(ledger: tuple[StoredEvent, ...]) -> tuple[bool, str, int]:
    """Walk one ledger in order; every APPLY of a SUPERSEDE must be a human AGREE
    matching an earlier, still-pending model proposal of equal signature."""
    judgments: dict[str, SemanticJudgment] = {}
    latest: dict[str, SemanticAdmissionPayload] = {}
    applied: set[str] = set()
    agrees = 0
    for stored in ledger:
        payload = stored.event.payload
        if isinstance(payload, SemanticJudgmentPayload):
            judgments[payload.judgment.judgment_id] = payload.judgment
            continue
        if not isinstance(payload, SemanticAdmissionPayload):
            continue
        judgment = judgments.get(payload.judgment_id)
        if (
            judgment is not None
            and judgment.kind is JudgmentKind.SUPERSEDE
            and payload.route is AdmissionRoute.APPLY
        ):
            if not _is_human(judgment):
                return (
                    False,
                    f"applied SUPERSEDE {judgment.judgment_id} is not the frozen human identity",
                    agrees,
                )
            if _HUMAN_AUTHORITY_REASON not in payload.reasons:
                return (
                    False,
                    (
                        f"applied human SUPERSEDE {judgment.judgment_id} lacks reason "
                        f"{_HUMAN_AUTHORITY_REASON}: {list(payload.reasons)}"
                    ),
                    agrees,
                )
            signature = proposal_signature(judgment.proposal)
            pending = [
                earlier_id
                for earlier_id, earlier in judgments.items()
                if earlier_id != judgment.judgment_id
                and not _is_human(earlier)
                and proposal_signature(earlier.proposal) == signature
                and earlier_id not in applied
                and earlier_id in latest
                and latest[earlier_id].route in _HELD_ROUTES
            ]
            if not pending:
                return (
                    False,
                    (
                        f"applied human AGREE {judgment.judgment_id} has no earlier pending model "
                        f"proposal with signature {signature}"
                    ),
                    agrees,
                )
            agrees += 1
        latest[payload.judgment_id] = payload
        if payload.route is AdmissionRoute.APPLY:
            applied.add(payload.judgment_id)
    return True, "", agrees


def _i8(run: RunResult) -> tuple[bool, str]:
    total = 0
    for arm in _PERSISTENT_ARMS:
        ok, detail, agrees = _applied_supersessions(_summary(run, arm).ledger)
        if not ok:
            return False, f"{arm}: {detail}"
        total += agrees
    return True, (
        f"{total} applied human AGREE(s), each APPLY/{_HUMAN_AUTHORITY_REASON} with an earlier "
        "pending model proposal of equal signature"
    )


def _i9(run: RunResult) -> tuple[bool, str]:
    for arm in _PERSISTENT_ARMS:
        summary = _summary(run, arm)
        if summary.replay is None:
            return False, f"{arm}: no replay result was recorded"
        if summary.replay.status != "REPLAY_MATCH":
            return False, f"{arm}: recorded replay {summary.replay.status}"
        recomputed = replay_matches(summary.ledger, summary.final_state)
        if recomputed.status != "REPLAY_MATCH":
            return (
                False,
                f"{arm}: replay of the final ledger does not reproduce the final state/view",
            )
    r_checked = 0
    for cell in _arm_cells(run, "R"):
        if cell.state_snapshot is None or not cell.ledger:
            continue
        recomputed = replay_matches(cell.ledger, cell.state_snapshot)
        if recomputed.status != "REPLAY_MATCH":
            return (
                False,
                f"{_cell_label(cell)}: replay of the cell ledger does not reproduce its state/view",
            )
        r_checked += 1
    return True, f"F and A final ledgers and {r_checked} R ledgers replay exactly"


def _i10(run: RunResult) -> tuple[bool, str]:
    calls: list[CallJudgments] = []
    for cell in _attempted(run):
        calls.extend(_calls(cell))
    passed, detail = request_only_reference_check(tuple(calls))
    return passed, f"{detail} ({len(calls)} calls checked)" if passed else detail


def _i11(run: RunResult) -> tuple[bool, str]:
    checked = 0
    for arm in _PERSISTENT_ARMS:
        summary = _summary(run, arm)
        ledger = summary.ledger
        sequences = [stored.sequence for stored in ledger]
        if sequences != list(range(1, len(ledger) + 1)):
            return (
                False,
                f"{arm}: ledger sequences are not contiguous from 1 ({len(ledger)} events)",
            )
        for cell in _arm_cells(run, arm):
            if cell.ledger and ledger[: len(cell.ledger)] != cell.ledger:
                return (
                    False,
                    f"{_cell_label(cell)}: cell ledger is not a prefix of the final ledger",
                )
        recorded = _ledger_judgments(ledger)
        state = summary.final_state
        for record in state.semantic.supersessions:
            target = record.target_judgment_id
            if target not in recorded:
                return (
                    False,
                    f"{arm}: superseded judgment {target} has no recorded event in the final "
                    "ledger",
                )
            if target not in state.semantic.judgments:
                return (
                    False,
                    f"{arm}: superseded judgment {target} is not readable in the final state",
                )
            if record.superseding_judgment_id not in recorded:
                return False, (
                    f"{arm}: superseding judgment {record.superseding_judgment_id} has no recorded "
                    "event in the final ledger"
                )
            checked += 1
    return True, f"append-only ledgers; {checked} supersession targets remain readable"


def _i12(run: RunResult) -> tuple[bool, str]:
    if [(c.position, c.t, c.arm) for c in run.cells] != [
        (i, t, arm) for i, (t, arm) in enumerate(ARM_SCHEDULE)
    ]:
        return False, "cells do not enumerate ARM_SCHEDULE position by position"
    exposed = any(cell.receipts for cell in run.cells)
    total = 0
    for cell in run.cells:
        if cell.status == "NOT_RUN":
            if cell.requests or cell.reference_snapshots or cell.receipts or cell.ledger:
                return (
                    False,
                    f"{_cell_label(cell)} is NOT_RUN yet carries requests, receipts or ledger "
                    "events",
                )
            continue
        total += len(cell.requests)
        if len(cell.reference_snapshots) != len(cell.requests):
            return False, (
                f"{_cell_label(cell)}: {len(cell.reference_snapshots)} reference snapshots for "
                f"{len(cell.requests)} requests"
            )
        if cell.status == "COMPLETED" and exposed and len(cell.receipts) != len(cell.requests):
            return (
                False,
                f"{_cell_label(cell)}: {len(cell.receipts)} receipts for {len(cell.requests)} "
                "requests",
            )
        if len(cell.receipts) > len(cell.requests):
            return (
                False,
                f"{_cell_label(cell)}: {len(cell.receipts)} receipts for {len(cell.requests)} "
                "requests",
            )
    if total != run.budget.frontier_calls:
        return (
            False,
            f"{total} request records but {run.budget.frontier_calls} frontier calls counted",
        )
    if total > MAX_FRONTIER_CALLS:
        return False, f"{total} request records exceed the {MAX_FRONTIER_CALLS}-call schedule"
    if run.status is RunStatus.COMPLETED and total != MAX_FRONTIER_CALLS:
        return (
            False,
            f"completed run reconciles {total} calls, not the {MAX_FRONTIER_CALLS}-call schedule",
        )
    problem = _ledger_reconciles(run)
    if problem is not None:
        return False, problem
    return True, (
        f"{total} request records == {run.budget.frontier_calls} frontier calls; snapshots, "
        "receipts and "
        f"ledger events reconcile one-to-one with the {MAX_FRONTIER_CALLS}-call schedule"
    )


def _ledger_reconciles(run: RunResult) -> str | None:
    """Every completed cell's ledger segment holds exactly the judgments its stage
    decisions name (plus human AGREEs), each with exactly one admission."""
    for arm in _ALL_ARMS:
        cells = _arm_cells(run, arm)
        for cell, start in _ledger_segments(cells):
            if cell.status != "COMPLETED":
                continue
            segment = cell.ledger[start:]
            recorded = _ledger_judgments(segment)
            admissions = _ledger_admissions(segment)
            decided = [d.judgment_id for stage in cell.stage_decisions for d in stage]
            if len(set(decided)) != len(decided):
                return f"{_cell_label(cell)}: a judgment id is decided twice"
            model_recorded = [jid for jid, j in recorded.items() if not _is_human(j)]
            if sorted(model_recorded) != sorted(decided):
                return (
                    f"{_cell_label(cell)}: ledger segment records model judgments "
                    f"{sorted(model_recorded)} "
                    f"but stage decisions name {sorted(decided)}"
                )
            for judgment_id in recorded:
                if judgment_id not in admissions:
                    return f"{_cell_label(cell)}: judgment {judgment_id} has no admission event"
    return None


def _gate_verdict(gates: tuple[GateResult, ...], name: str) -> tuple[bool, str]:
    matching = [gate for gate in gates if gate.name == name]
    if len(matching) != 1:
        raise PreflightGateMissing(
            f"preflight gate {name!r} must appear exactly once in the preflight tuple; "
            f"found {len(matching)}"
        )
    (gate,) = matching
    return gate.passed, gate.detail


def _i15(run: RunResult) -> tuple[bool, str]:
    agrees = 0
    for arm in _PERSISTENT_ARMS:
        cells = _arm_cells(run, arm)
        final_ledger = _summary(run, arm).ledger
        final_admissions = _ledger_admissions(final_ledger)
        final_judgments = _ledger_judgments(final_ledger)
        in_final = sum(
            1
            for jid, j in final_judgments.items()
            if _is_human(j)
            and j.kind is JudgmentKind.SUPERSEDE
            and jid in final_admissions
            and final_admissions[jid].route is AdmissionRoute.APPLY
        )
        found = 0
        for cell, start in _ledger_segments(cells):
            segment = cell.ledger[start:]
            admissions = _ledger_admissions(cell.ledger)
            earlier: dict[str, SemanticJudgment] = _ledger_judgments(cell.ledger[:start])
            for stored in segment:
                payload = stored.event.payload
                if isinstance(payload, SemanticJudgmentPayload):
                    judgment = payload.judgment
                    if not _is_human(judgment):
                        earlier[judgment.judgment_id] = judgment
                        continue
                    problem = _agree_problem(cell, judgment, admissions, earlier)
                    if problem is not None:
                        return False, problem
                    found += 1
        if found != in_final:
            return (
                False,
                f"{arm}: {in_final} applied human AGREE(s) in the final ledger but {found} "
                "attributable to a cell",
            )
        agrees += found
        for jid, j in final_judgments.items():
            if _is_human(j) or j.kind is not JudgmentKind.SUPERSEDE:
                continue
            admission = final_admissions.get(jid)
            if admission is not None and admission.route is AdmissionRoute.APPLY:
                return False, f"{arm}: pending model SUPERSEDE {jid} was applied"
    pending = sum(
        1
        for arm in _PERSISTENT_ARMS
        for jid, j in _ledger_judgments(_summary(run, arm).ledger).items()
        if not _is_human(j) and j.kind is JudgmentKind.SUPERSEDE
    )
    return True, (
        f"{agrees} applied human AGREE(s) traced through the mechanical chain (eligible pre-T "
        "target, earlier pending model proposal, APPLY/HUMAN_AUTHORITY, checkpoint T, rationale "
        "'AGREE: <id>'); "
        f"{pending} model SUPERSEDE proposal(s) never applied by the model"
    )


def _agree_problem(
    cell: CellRecord,
    judgment: SemanticJudgment,
    admissions: Mapping[str, SemanticAdmissionPayload],
    earlier: Mapping[str, SemanticJudgment],
) -> str | None:
    """Why a human judgment recorded in ``cell`` is not a legitimate mechanical AGREE."""
    label = f"{_cell_label(cell)} human judgment {judgment.judgment_id}"
    proposal = judgment.proposal
    if not isinstance(proposal, SupersedeProposal):
        return f"{label}: the human wrote a {judgment.kind.value}, not an AGREE on a SUPERSEDE"
    admission = admissions.get(judgment.judgment_id)
    if admission is None or admission.route is not AdmissionRoute.APPLY:
        return f"{label}: not routed APPLY"
    if _HUMAN_AUTHORITY_REASON not in admission.reasons:
        return f"{label}: applied without reason {_HUMAN_AUTHORITY_REASON}"
    if cell.t not in AUTHORITY_CHECKPOINTS:
        return f"{label}: AGREE issued at T{cell.t}, not an authority checkpoint"
    eligible = cell.eligible_targets
    if eligible is None:
        return f"{label}: no pre-T eligible-target snapshot exists for this cell"
    if eligible.target_locus != AUTHORITY_CHECKPOINTS[cell.t]:
        return (
            f"{label}: snapshot locus {eligible.target_locus} is not the T{cell.t} checkpoint locus"
        )
    if (eligible.arm, eligible.t) != (cell.arm, cell.t):
        return f"{label}: snapshot identity {(eligible.arm, eligible.t)} is not this cell's"
    target = proposal.target_judgment_id
    if target not in eligible.eligible_judgment_ids:
        return (
            f"{label}: target {target} is outside the pre-T eligible set "
            f"{list(eligible.eligible_judgment_ids)}"
        )
    signature = proposal_signature(judgment.proposal)
    pending_ids = [
        jid
        for jid, j in earlier.items()
        if proposal_signature(j.proposal) == signature
        and jid in admissions
        and admissions[jid].route in _HELD_ROUTES
    ]
    if not pending_ids:
        return f"{label}: no earlier pending model proposal carries signature {signature}"
    expected = [f"AGREE: {jid}" for jid in pending_ids]
    if judgment.rationale not in expected:
        return f"{label}: rationale {judgment.rationale!r} is not exactly one of {expected}"
    if (
        judgment.visible_evidence_ids
        or judgment.compared_object_ids
        or judgment.confidence is not None
    ):
        return f"{label}: AGREE carries evidence, compared objects or confidence"
    return None


def integrity_verdicts(
    run: RunResult, *, preflight_gates: tuple[GateResult, ...]
) -> tuple[IntegrityVerdict, ...]:
    """The fifteen spec §12 verdicts over ``run``. I13 consumes exactly the gate named
    ``GATE_I13_NAME`` and I14 exactly ``GATE_I14_NAME`` (``PreflightGateMissing`` when
    absent or duplicated). Every other verdict is computed from the run alone and
    fails closed on any exception."""
    i13 = _gate_verdict(preflight_gates, GATE_I13_NAME)
    i14 = _gate_verdict(preflight_gates, GATE_I14_NAME)
    plan: tuple[tuple[str, Callable[[], tuple[bool, str]], tuple[Arm, ...]], ...] = (
        ("I1", lambda: _i1(run), _PERSISTENT_ARMS),
        ("I2", lambda: _i2(run), _ALL_ARMS),
        ("I3", lambda: _i3(run), _ALL_ARMS),
        ("I4", lambda: _i4(run), _ALL_ARMS),
        ("I5", lambda: _i5(run), _CONTRASTIVE_ARMS),
        ("I6", lambda: _i6(run), _ALL_ARMS),
        ("I7", lambda: _i7(run), _PERSISTENT_ARMS),
        ("I8", lambda: _i8(run), _PERSISTENT_ARMS),
        ("I9", lambda: _i9(run), _ALL_ARMS),
        ("I10", lambda: _i10(run), _ALL_ARMS),
        ("I11", lambda: _i11(run), _PERSISTENT_ARMS),
        ("I12", lambda: _i12(run), _ALL_ARMS),
        ("I13", lambda: i13, ("R",)),
        ("I14", lambda: i14, _ALL_ARMS),
        ("I15", lambda: _i15(run), _PERSISTENT_ARMS),
    )
    verdicts: list[IntegrityVerdict] = []
    for verdict_id, evaluate, applies_to in plan:
        try:
            passed, detail = evaluate()
        except Exception as exc:  # noqa: BLE001 - a verdict that cannot run fails closed
            passed, detail = False, f"could not evaluate: {_safe(exc)}"
        verdicts.append(
            IntegrityVerdict(id=verdict_id, passed=passed, detail=detail, applies_to=applies_to)
        )
    return tuple(verdicts)

"""The 18 preflight gates (spec §8) and the post-run verdicts L1-L9 (spec §8, §14 rule
0, §17) of the locus-policy live-validation experiment.

``preflight`` evaluates every gate of ``GATE_NAMES`` in spec §8 order and returns one
``GateResult`` per gate. A gate never raises: one that cannot be evaluated is a failed
gate whose ``detail`` carries the exception name (fail closed). There is NO test-suite
gate (spec §8.1: software qualification is a pre-seal requirement of the harness
commit, never a live-identity gate). Gate semantics, in order:

1.  ``head_equals_final_seal`` -- HEAD is the seal, the seal's only parent is the
    manifest's ``harness_code_sha``, and ``parent..seal`` changed exactly the two
    preregistration files (``PREREGISTRATION_FILES``).
2.  ``worktree_clean`` -- ``git.dirty()`` is empty.
3.  ``seal_descends_from_baseline`` -- ``BASELINE_SHA`` is an ancestor of the seal.
4.  ``locus_policy_frozen`` -- in-process ``LOCUS_POLICY_VERSION`` equals
    ``POLICY_VERSION_FROZEN``, the manifest's ``policy_version`` and the adapter
    CLASS attribute ``XAILocusSemanticReasoner.policy_version`` (read only; the
    adapter is never constructed).
5.  ``locus_prompt_hash_frozen`` -- a FRESH sha256 of ``LOCUS_SYSTEM_INSTRUCTION``
    equals the adapter's pasted literal, ``PROMPT_SHA256_FROZEN`` and the manifest.
6.  ``output_schema_hash_frozen`` -- ``semantic_output_schema_sha256()`` equals the
    adapter literal, ``OUTPUT_SCHEMA_SHA256_FROZEN`` and the manifest.
7.  ``historical_prompts_unchanged`` -- fresh sha256s of ``SYSTEM_INSTRUCTION`` (9p-v4)
    and ``CONTRASTIVE_SYSTEM_INSTRUCTION`` (9p2-v1) equal the adapter literals,
    ``HISTORICAL_PROMPT_SHA256S`` and the manifest's ``historical_prompt_sha256s``.
8.  ``model_configuration_frozen`` -- the manifest's provider, model, reasoning
    effort and gRPC resolver equal the protocol literals, and the adapter class
    attribute ``include_comparison_context`` is exactly ``True``.
9.  ``calls_per_delta_is_2`` -- production ``CALLS_PER_DELTA == 2`` and the manifest's
    ``calls_per_delta == 2``.
10. ``evidence_manifest_frozen`` -- ``corpus.evidence_records()`` equals the manifest's
    ``evidence`` (JSON round-tripped, in order) and ``corpus_sha256()`` the manifest's.
11. ``ceilings_frozen`` -- the protocol ceilings and the manifest's ``ceilings`` both
    equal the spec §12 literals ``LOCKED_CEILINGS`` (8 / 0 / 0 / 0 / 0 / 2.00).
12. ``expectations_frozen`` -- the on-disk expectations bytes (parsed, canonicalised)
    hash to the manifest's ``expectations_sha256`` and to the in-process
    ``expectations_document()``.
13. ``answer_key_not_imported_by_request_path`` -- ``leakage.request_path_import_gate``
    over the injected request-path sources.
14. ``leakage_gate_passes`` -- the supplied ``LeakageResult`` passed, its needle-set
    sha equals the manifest's and it scanned the frozen locus prompt.
15. ``grpc_dns_resolver_is_native`` -- the observed live-process ``GRPC_DNS_RESOLVER``
    (injected by the CLI; never read here) equals ``"native"`` by exact equality.
16. ``historical_artifacts_unchanged`` -- ``DESIGN_BASE_SHA`` is an ancestor of the
    seal, the manifest names it, and for every directory in
    ``HISTORICAL_ARTIFACT_DIRS`` the tree at the design base, at the seal and in the
    manifest are equal.
17. ``predecessor_commits_unchanged`` -- the 9P3 raw-run and adjudication commits are
    ancestors of the seal, nothing under ``PREDECESSOR_ARTIFACT_DIR`` changed since
    the adjudication, and the manifest names both commits.
18. ``no_raw_artifacts_exist`` -- the manifest's ``raw_artifact_paths`` is the list of
    ``RAW_ARTIFACT_PATH_COUNT`` relative paths (spec §13) and none exists under
    ``out_dir``.

``integrity_verdicts`` computes the nine spec §8 verdicts from a ``RunResult``, the
preflight tuple and the T4 case results. ``L1`` two calls per completed delta; ``L2``
no third, judge or retried call (``frontier_calls`` equals the request records,
``judge_calls == 0``, no duplicate request identity, no delta with more than two
records); ``L3`` the request-only reference law, the frozen 9P3
``request_only_reference_check`` over ``RequestRecord`` + ``RequestReferenceSnapshot``
pairs with the model judgments of that delta's ledger segment; ``L4`` replay equality
per completed ledger (the recorded result and a fresh ``replay_matches``); ``L5``
receipts, requests, snapshots and ledger events reconcile; ``L6`` no ``SUPERSEDE``
applied and ``human_authorizations == 0``; ``L7`` the identity guard never tripped;
``L8`` cost and calls within the ceilings; ``L9`` every §7.1 case assertion set holds.
Every verdict fails closed: one that cannot be evaluated (a
``ReferenceSnapshotMismatch`` raised by the L3 binding check included) is a FAIL whose
detail carries the exception. ``passed`` is typed ``bool | None`` for the artifact
layer; this module never produces ``None``.

Attribution (the observed attribution law of 9P3 spec §12.1 with ledgers in place of
arms). Every verdict carries ``applies_to = ("alpha", "beta")`` and ``failed_ledgers``:
the ledgers whose OWN evidence violated the verdict, canonical order alpha then beta,
``()`` when passed or when the failure is intrinsically global (budget totals, judge
calls, the run status, case coverage). L1-L5 evaluate each ledger in isolation and a
``NOT_RUN`` ledger is skipped, not failed, unless the run is ``COMPLETED`` (a completed
run has no unreached ledger); an exception inside one ledger's evaluation attributes
that ledger only, an exception escaping a whole verdict attributes none.

Law of this module: it decides nothing semantic and originates no scientific value;
every expected value is a frozen literal, a ``protocol``/``corpus`` constant or a
sealed manifest field. Git is injected behind ``GitCliLike`` and so is the one
environment observation gate 15 needs; this module never shells out, never reads or
writes the process environment, never reads a key, never writes a file and never
constructs a provider client or a reasoner. It may import ``expectations`` because it
never enters the provider request path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, NamedTuple

from pydantic import Field, model_validator

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION,
    LOCUS_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
    XAILocusSemanticReasoner,
    semantic_output_schema_sha256,
)
from foundry.application.incremental_assimilation import CALLS_PER_DELTA
from foundry.domain.common import FrozenModel
from foundry.domain.events import (
    EventType,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
)
from foundry.domain.semantic_judgment import AdmissionRoute, JudgmentKind, SemanticJudgment
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.contrastive_unseen.integrity import GateResult, all_passed
from foundry.experiments.locus_validation.corpus import (
    LEDGERS,
    Ledger,
    corpus_sha256,
    evidence_records,
)
from foundry.experiments.locus_validation.evaluation import CaseResult
from foundry.experiments.locus_validation.expectations import CASE_IDS, expectations_document
from foundry.experiments.locus_validation.leakage import LeakageResult, request_path_import_gate
from foundry.experiments.locus_validation.protocol import (
    BASELINE_SHA,
    CEILING_KEYS,
    DELTAS,
    DESIGN_BASE_SHA,
    EXPERIMENT_ARTIFACT_DIR,
    GRPC_DNS_RESOLVER_ENV,
    GRPC_DNS_RESOLVER_FROZEN,
    HISTORICAL_ARTIFACT_DIRS,
    HISTORICAL_PROMPT_SHA256S,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    MAX_SAME_CELL_RERUNS,
    MAX_SEMANTIC_RETRIES,
    MODEL,
    OUTPUT_SCHEMA_SHA256_FROZEN,
    POLICY_VERSION_FROZEN,
    PREDECESSOR_ADJUDICATION_SHA,
    PREDECESSOR_ARTIFACT_DIR,
    PREDECESSOR_RAW_RUN_SHA,
    PREREGISTRATION_FILE_NAMES,
    PROMPT_SHA256_FROZEN,
    PROVIDER,
    REASONING_EFFORT,
)
from foundry.experiments.locus_validation.runner import (
    DeltaRecord,
    LedgerRecord,
    RunResult,
    RunStatus,
)
from foundry.experiments.long_horizon_bounded.integrity import (
    CallJudgments,
    GitCliLike,
    request_only_reference_check,
)
from foundry.experiments.longitudinal.scoring import replay_matches

__all__ = [
    "GATE_NAMES",
    "LOCKED_CEILINGS",
    "MANIFEST_KEY_CALLS_PER_DELTA",
    "MANIFEST_KEY_CEILINGS",
    "MANIFEST_KEY_CORPUS_SHA256",
    "MANIFEST_KEY_EVIDENCE",
    "MANIFEST_KEY_EXPECTATIONS_SHA256",
    "MANIFEST_KEY_GRPC_DNS_RESOLVER",
    "MANIFEST_KEY_HARNESS_CODE_SHA",
    "MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES",
    "MANIFEST_KEY_HISTORICAL_PRESERVATION_BASE_SHA",
    "MANIFEST_KEY_HISTORICAL_PROMPT_SHA256S",
    "MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256",
    "MANIFEST_KEY_MODEL",
    "MANIFEST_KEY_OUTPUT_SCHEMA_SHA256",
    "MANIFEST_KEY_POLICY_VERSION",
    "MANIFEST_KEY_PREDECESSOR_ADJUDICATION_SHA",
    "MANIFEST_KEY_PREDECESSOR_RAW_RUN_SHA",
    "MANIFEST_KEY_PROMPT_SHA256",
    "MANIFEST_KEY_PROVIDER",
    "MANIFEST_KEY_RAW_ARTIFACT_PATHS",
    "MANIFEST_KEY_REASONING_EFFORT",
    "PREREGISTRATION_FILES",
    "RAW_ARTIFACT_PATH_COUNT",
    "REQUIRED_MANIFEST_KEYS",
    "VERDICT_IDS",
    "CallJudgments",
    "GateResult",
    "GitCliLike",
    "IntegrityVerdict",
    "all_passed",
    "integrity_verdicts",
    "preflight",
    "request_only_reference_check",
]

# --------------------------------------------------------------------------- constants

GATE_NAMES: Final[tuple[str, ...]] = (
    "head_equals_final_seal",
    "worktree_clean",
    "seal_descends_from_baseline",
    "locus_policy_frozen",
    "locus_prompt_hash_frozen",
    "output_schema_hash_frozen",
    "historical_prompts_unchanged",
    "model_configuration_frozen",
    "calls_per_delta_is_2",
    "evidence_manifest_frozen",
    "ceilings_frozen",
    "expectations_frozen",
    "answer_key_not_imported_by_request_path",
    "leakage_gate_passes",
    "grpc_dns_resolver_is_native",
    "historical_artifacts_unchanged",
    "predecessor_commits_unchanged",
    "no_raw_artifacts_exist",
)
"""Spec §8, exactly 18 gates in order. No test suite runs inside preflight (§8.1)."""

VERDICT_IDS: Final[tuple[str, ...]] = tuple(f"L{n}" for n in range(1, 10))

PREREGISTRATION_FILES: Final[tuple[str, ...]] = tuple(
    EXPERIMENT_ARTIFACT_DIR + name for name in PREREGISTRATION_FILE_NAMES
)

RAW_ARTIFACT_PATH_COUNT: Final[int] = 21
"""Spec §13: the raw tree is exactly 21 write-once paths; gate 18 refuses any other
count so the absence check can never be vacuous."""

LOCKED_CEILINGS: Final[dict[str, int | float]] = {
    "max_frontier_calls": 8,
    "max_judge_calls": 0,
    "max_semantic_retries": 0,
    "max_same_cell_reruns": 0,
    "max_human_authorizations": 0,
    "max_provider_cost_usd": 2.0,
}
"""Spec §12, as pasted literals so a drift in ``protocol`` is caught too."""

_COST_CEILING: Final[Decimal] = Decimal("2.0")

# Manifest keys (T7 produces them; the names are defined here, once).
MANIFEST_KEY_HARNESS_CODE_SHA: Final = "harness_code_sha"
MANIFEST_KEY_POLICY_VERSION: Final = "policy_version"
MANIFEST_KEY_PROMPT_SHA256: Final = "prompt_sha256"
MANIFEST_KEY_HISTORICAL_PROMPT_SHA256S: Final = "historical_prompt_sha256s"
MANIFEST_KEY_OUTPUT_SCHEMA_SHA256: Final = "output_schema_sha256"
MANIFEST_KEY_PROVIDER: Final = "provider"
MANIFEST_KEY_MODEL: Final = "model"
MANIFEST_KEY_REASONING_EFFORT: Final = "reasoning_effort"
MANIFEST_KEY_GRPC_DNS_RESOLVER: Final = "grpc_dns_resolver"
MANIFEST_KEY_CALLS_PER_DELTA: Final = "calls_per_delta"
MANIFEST_KEY_EVIDENCE: Final = "evidence"
MANIFEST_KEY_CORPUS_SHA256: Final = "corpus_sha256"
MANIFEST_KEY_CEILINGS: Final = "ceilings"
MANIFEST_KEY_EXPECTATIONS_SHA256: Final = "expectations_sha256"
MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256: Final = "leakage_needle_set_sha256"
MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES: Final = "historical_artifact_tree_hashes"
MANIFEST_KEY_HISTORICAL_PRESERVATION_BASE_SHA: Final = "historical_preservation_base_sha"
MANIFEST_KEY_PREDECESSOR_RAW_RUN_SHA: Final = "predecessor_raw_run_sha"
MANIFEST_KEY_PREDECESSOR_ADJUDICATION_SHA: Final = "predecessor_adjudication_sha"
MANIFEST_KEY_RAW_ARTIFACT_PATHS: Final = "raw_artifact_paths"
REQUIRED_MANIFEST_KEYS: Final[tuple[str, ...]] = (
    MANIFEST_KEY_HARNESS_CODE_SHA,
    MANIFEST_KEY_POLICY_VERSION,
    MANIFEST_KEY_PROMPT_SHA256,
    MANIFEST_KEY_HISTORICAL_PROMPT_SHA256S,
    MANIFEST_KEY_OUTPUT_SCHEMA_SHA256,
    MANIFEST_KEY_PROVIDER,
    MANIFEST_KEY_MODEL,
    MANIFEST_KEY_REASONING_EFFORT,
    MANIFEST_KEY_GRPC_DNS_RESOLVER,
    MANIFEST_KEY_CALLS_PER_DELTA,
    MANIFEST_KEY_EVIDENCE,
    MANIFEST_KEY_CORPUS_SHA256,
    MANIFEST_KEY_CEILINGS,
    MANIFEST_KEY_EXPECTATIONS_SHA256,
    MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256,
    MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES,
    MANIFEST_KEY_HISTORICAL_PRESERVATION_BASE_SHA,
    MANIFEST_KEY_PREDECESSOR_RAW_RUN_SHA,
    MANIFEST_KEY_PREDECESSOR_ADJUDICATION_SHA,
    MANIFEST_KEY_RAW_ARTIFACT_PATHS,
)
"""Every manifest key a gate reads; a missing key fails that gate closed."""

_ALL_LEDGERS: Final[tuple[Ledger, ...]] = LEDGERS
_EXPECTED_CALL_NUMBERS: Final[tuple[int, ...]] = (1, 2)
_IDENTITY_DRIFT_PREFIX: Final = "IdentityDrift"

_Gate = Callable[[], tuple[bool, str]]


# --------------------------------------------------------------------------- preflight


def preflight(
    *,
    git: GitCliLike,
    frozen_sha: str,
    manifest: Mapping[str, Any],
    expectations_bytes: bytes,
    request_path_sources: Mapping[str, str],
    leakage: LeakageResult,
    observed_grpc_dns_resolver: str | None,
    out_dir: Path,
) -> tuple[GateResult, ...]:
    """Evaluate every gate in ``GATE_NAMES`` order. Never raises; never writes; never
    reads a key or the environment; constructs no reasoner or provider client.

    ``observed_grpc_dns_resolver`` is the live process's ``GRPC_DNS_RESOLVER`` exactly
    as the CLI observed it (``None`` when unset). ``out_dir`` is the experiment
    directory gate 18 inspects for the frozen raw artifact paths."""
    gates: dict[str, _Gate] = {
        "head_equals_final_seal": lambda: _head_equals_final_seal(git, frozen_sha, manifest),
        "worktree_clean": lambda: _worktree_clean(git.dirty()),
        "seal_descends_from_baseline": lambda: _descends_from_baseline(git, frozen_sha),
        "locus_policy_frozen": lambda: _locus_policy_frozen(manifest),
        "locus_prompt_hash_frozen": lambda: _locus_prompt_hash_frozen(manifest),
        "output_schema_hash_frozen": lambda: _output_schema_hash_frozen(manifest),
        "historical_prompts_unchanged": lambda: _historical_prompts_unchanged(manifest),
        "model_configuration_frozen": lambda: _model_configuration_frozen(manifest),
        "calls_per_delta_is_2": lambda: _calls_per_delta_is_2(manifest),
        "evidence_manifest_frozen": lambda: _evidence_manifest_frozen(manifest),
        "ceilings_frozen": lambda: _ceilings_frozen(manifest),
        "expectations_frozen": lambda: _expectations_frozen(manifest, expectations_bytes),
        "answer_key_not_imported_by_request_path": lambda: request_path_import_gate(
            request_path_sources
        ),
        "leakage_gate_passes": lambda: _leakage_gate_passes(leakage, manifest),
        "grpc_dns_resolver_is_native": lambda: _grpc_dns_resolver_is_native(
            observed_grpc_dns_resolver
        ),
        "historical_artifacts_unchanged": lambda: _historical_artifacts_unchanged(
            git, frozen_sha, manifest
        ),
        "predecessor_commits_unchanged": lambda: _predecessor_commits_unchanged(
            git, frozen_sha, manifest
        ),
        "no_raw_artifacts_exist": lambda: _no_raw_artifacts_exist(manifest, out_dir),
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


# --------------------------------------------------------------------------- gates 1-3


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
            f"{MANIFEST_KEY_HARNESS_CODE_SHA} [{harness_sha!r}]"
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


def _descends_from_baseline(git: GitCliLike, frozen_sha: str) -> tuple[bool, str]:
    if git.is_ancestor(BASELINE_SHA, frozen_sha):
        return True, f"baseline {BASELINE_SHA} is an ancestor of seal {frozen_sha}"
    return False, f"baseline {BASELINE_SHA} is NOT an ancestor of seal {frozen_sha}"


# --------------------------------------------------------------------------- gates 4-9


def _locus_policy_frozen(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    frozen = POLICY_VERSION_FROZEN
    sealed = _manifest_value(manifest, MANIFEST_KEY_POLICY_VERSION)
    class_version = XAILocusSemanticReasoner.policy_version
    if frozen != LOCUS_POLICY_VERSION:
        return (
            False,
            f"in-process LOCUS_POLICY_VERSION {LOCUS_POLICY_VERSION!r} != frozen {frozen!r}",
        )
    if class_version != frozen:
        return False, (
            f"XAILocusSemanticReasoner.policy_version {class_version!r} != frozen {frozen!r}"
        )
    if sealed != frozen:
        return False, f"manifest[{MANIFEST_KEY_POLICY_VERSION!r}] {sealed!r} != frozen {frozen!r}"
    return True, f"locus policy {frozen!r} (in process == adapter class == frozen == manifest)"


def _locus_prompt_hash_frozen(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    frozen = PROMPT_SHA256_FROZEN
    computed = _sha256(LOCUS_SYSTEM_INSTRUCTION)
    sealed = _manifest_value(manifest, MANIFEST_KEY_PROMPT_SHA256)
    if computed != frozen:
        return False, f"locus prompt sha256 computed {computed} != frozen {frozen}"
    if frozen != LOCUS_SYSTEM_INSTRUCTION_SHA256:
        return False, f"adapter literal {LOCUS_SYSTEM_INSTRUCTION_SHA256} != frozen {frozen}"
    if sealed != frozen:
        return False, f"manifest[{MANIFEST_KEY_PROMPT_SHA256!r}] {sealed!r} != frozen {frozen}"
    return True, f"locus prompt sha256 {frozen} (computed == adapter literal == frozen == manifest)"


def _output_schema_hash_frozen(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    frozen = OUTPUT_SCHEMA_SHA256_FROZEN
    computed = semantic_output_schema_sha256()
    sealed = _manifest_value(manifest, MANIFEST_KEY_OUTPUT_SCHEMA_SHA256)
    if computed != frozen:
        return False, f"output schema sha256 computed {computed} != frozen {frozen}"
    if frozen != SEMANTIC_OUTPUT_SCHEMA_SHA256:
        return False, f"adapter literal {SEMANTIC_OUTPUT_SCHEMA_SHA256} != frozen {frozen}"
    if sealed != frozen:
        return False, (
            f"manifest[{MANIFEST_KEY_OUTPUT_SCHEMA_SHA256!r}] {sealed!r} != frozen {frozen}"
        )
    return (
        True,
        f"output schema sha256 {frozen} (computed == adapter literal == frozen == manifest)",
    )


def _historical_prompts_unchanged(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    sealed = _json_round_trip(_manifest_value(manifest, MANIFEST_KEY_HISTORICAL_PROMPT_SHA256S))
    historical: tuple[tuple[str, str, str, str], ...] = (
        (POLICY_VERSION, SYSTEM_INSTRUCTION, SYSTEM_INSTRUCTION_SHA256, "SYSTEM_INSTRUCTION"),
        (
            CONTRASTIVE_POLICY_VERSION,
            CONTRASTIVE_SYSTEM_INSTRUCTION,
            CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
            "CONTRASTIVE_SYSTEM_INSTRUCTION",
        ),
    )
    if set(HISTORICAL_PROMPT_SHA256S) != {policy for policy, *_ in historical}:
        return False, (
            f"HISTORICAL_PROMPT_SHA256S names {sorted(HISTORICAL_PROMPT_SHA256S)}, expected "
            f"{sorted(policy for policy, *_ in historical)}"
        )
    for policy, instruction, adapter_literal, label in historical:
        frozen = HISTORICAL_PROMPT_SHA256S[policy]
        computed = _sha256(instruction)
        if computed != frozen:
            return False, f"{label} ({policy}) sha256 computed {computed} != frozen {frozen}"
        if adapter_literal != frozen:
            return False, f"{label} ({policy}) adapter literal {adapter_literal} != frozen {frozen}"
    if sealed != _json_round_trip(HISTORICAL_PROMPT_SHA256S):
        return False, (
            f"manifest[{MANIFEST_KEY_HISTORICAL_PROMPT_SHA256S!r}] {sealed!r} != frozen "
            f"{HISTORICAL_PROMPT_SHA256S}"
        )
    return True, (
        f"historical prompts unchanged: {HISTORICAL_PROMPT_SHA256S} (computed == adapter "
        "literal == frozen == manifest)"
    )


def _model_configuration_frozen(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    expected: tuple[tuple[str, str], ...] = (
        (MANIFEST_KEY_PROVIDER, PROVIDER),
        (MANIFEST_KEY_MODEL, MODEL),
        (MANIFEST_KEY_REASONING_EFFORT, REASONING_EFFORT),
        (MANIFEST_KEY_GRPC_DNS_RESOLVER, GRPC_DNS_RESOLVER_FROZEN),
    )
    for key, frozen in expected:
        sealed = _manifest_value(manifest, key)
        if sealed != frozen:
            return False, f"manifest[{key!r}] {sealed!r} != frozen {frozen!r}"
    flag = XAILocusSemanticReasoner.include_comparison_context
    if flag is not True:
        return False, (
            f"XAILocusSemanticReasoner.include_comparison_context is {flag!r}, not True: the "
            "locus policy must run the contrastive path"
        )
    return True, (
        f"provider {PROVIDER!r}, model {MODEL!r}, reasoning effort {REASONING_EFFORT!r}, "
        f"{GRPC_DNS_RESOLVER_ENV} {GRPC_DNS_RESOLVER_FROZEN!r}; include_comparison_context True"
    )


def _calls_per_delta_is_2(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    sealed = _manifest_value(manifest, MANIFEST_KEY_CALLS_PER_DELTA)
    if CALLS_PER_DELTA != 2:
        return False, f"CALLS_PER_DELTA == {CALLS_PER_DELTA}, expected 2"
    if sealed != 2:
        return False, f"manifest[{MANIFEST_KEY_CALLS_PER_DELTA!r}] {sealed!r} != 2"
    return True, "CALLS_PER_DELTA == 2 == manifest"


# --------------------------------------------------------------------------- gates 10-12


def _evidence_manifest_frozen(manifest: Mapping[str, Any]) -> tuple[bool, str]:
    sealed = _json_round_trip(_manifest_value(manifest, MANIFEST_KEY_EVIDENCE))
    sealed_corpus = _manifest_value(manifest, MANIFEST_KEY_CORPUS_SHA256)
    loaded = _json_round_trip([record.model_dump(mode="json") for record in evidence_records()])
    if not isinstance(sealed, list):
        return False, f"manifest[{MANIFEST_KEY_EVIDENCE!r}] is not a list"
    if len(sealed) != len(loaded):
        return False, f"{len(loaded)} evidence records in process, {len(sealed)} sealed"
    for index, (actual, expected) in enumerate(zip(loaded, sealed, strict=True)):
        if actual != expected:
            return False, f"evidence index {index}: in process {actual} != sealed {expected}"
    computed = corpus_sha256()
    if sealed_corpus != computed:
        return False, (
            f"manifest[{MANIFEST_KEY_CORPUS_SHA256!r}] {sealed_corpus!r} != in-process corpus "
            f"sha256 {computed}"
        )
    return True, (
        f"{len(loaded)} evidence records equal the sealed manifest, in order; corpus sha256 "
        f"{computed}"
    )


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
    if tuple(in_process) != CEILING_KEYS or tuple(LOCKED_CEILINGS) != CEILING_KEYS:
        return False, f"ceiling keys {list(in_process)} != CEILING_KEYS {list(CEILING_KEYS)}"
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


def _expectations_frozen(
    manifest: Mapping[str, Any], expectations_bytes: bytes
) -> tuple[bool, str]:
    sealed = _manifest_value(manifest, MANIFEST_KEY_EXPECTATIONS_SHA256)
    try:
        parsed = json.loads(expectations_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return False, f"expectations bytes unparsable: {_safe(exc)}"
    on_disk = canonical_sha256(parsed)
    in_process = canonical_sha256(expectations_document())
    if on_disk != sealed:
        return False, (
            f"on-disk expectations canonical sha256 {on_disk} != manifest "
            f"[{MANIFEST_KEY_EXPECTATIONS_SHA256!r}] {sealed!r}"
        )
    if in_process != sealed:
        return False, (
            f"in-process expectations document canonical sha256 {in_process} != manifest "
            f"[{MANIFEST_KEY_EXPECTATIONS_SHA256!r}] {sealed!r}"
        )
    return True, f"expectations canonical sha256 {sealed} (on disk == manifest == in process)"


# --------------------------------------------------------------------------- gates 14-15


def _leakage_gate_passes(leakage: LeakageResult, manifest: Mapping[str, Any]) -> tuple[bool, str]:
    if not leakage.passed:
        return False, (
            f"leakage gate FAILED: needle {leakage.matched_needle!r} "
            f"({leakage.matched_needle_kind}) in skeleton {leakage.matched_skeleton_id!r}"
        )
    sealed = _manifest_value(manifest, MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256)
    if leakage.needle_set_sha256 != sealed:
        return False, (
            f"needle set sha256 {leakage.needle_set_sha256} != manifest "
            f"[{MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256!r}] {sealed!r}"
        )
    if leakage.prompt_sha256 != PROMPT_SHA256_FROZEN:
        return False, (
            f"leakage scanned prompt {leakage.prompt_sha256}, not the frozen locus prompt "
            f"{PROMPT_SHA256_FROZEN}"
        )
    return True, (
        f"leakage PASS over {len(leakage.skeletons)} skeletons; typed needle set "
        f"{leakage.needle_set_sha256}; frozen locus prompt scanned"
    )


def _grpc_dns_resolver_is_native(observed: str | None) -> tuple[bool, str]:
    """Exact string equality; nothing is stripped, casefolded or defaulted."""
    frozen = GRPC_DNS_RESOLVER_FROZEN
    if observed != frozen:
        return False, (
            f"observed {GRPC_DNS_RESOLVER_ENV}={observed!r} in the live process environment "
            f"!= frozen {frozen!r}"
        )
    return True, f"{GRPC_DNS_RESOLVER_ENV}={frozen!r} observed"


# --------------------------------------------------------------------------- gates 16-18


def _historical_artifacts_unchanged(
    git: GitCliLike, frozen_sha: str, manifest: Mapping[str, Any]
) -> tuple[bool, str]:
    """Three-way tree-hash equality per directory against the approved design base
    (never HEAD), plus the ancestor check and the manifest's base identity."""
    sealed = _manifest_value(manifest, MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES)
    sealed_base = _manifest_value(manifest, MANIFEST_KEY_HISTORICAL_PRESERVATION_BASE_SHA)
    base = DESIGN_BASE_SHA
    if sealed_base != base:
        return False, (
            f"manifest[{MANIFEST_KEY_HISTORICAL_PRESERVATION_BASE_SHA!r}] {sealed_base!r} != "
            f"design base {base}"
        )
    if not git.is_ancestor(base, frozen_sha):
        return False, f"design base {base} is NOT an ancestor of seal {frozen_sha}"
    if not isinstance(sealed, Mapping):
        return False, f"manifest[{MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES!r}] is not a mapping"
    for directory in HISTORICAL_ARTIFACT_DIRS:
        if directory not in sealed:
            return False, f"manifest historical tree hashes lack {directory!r}"
        at_base = git.tree_sha(base, directory)
        at_seal = git.tree_sha(frozen_sha, directory)
        if at_seal != at_base:
            return False, f"{directory} tree at seal {at_seal} != tree at design base {at_base}"
        if sealed[directory] != at_base:
            return False, (
                f"manifest historical tree hash for {directory} {sealed[directory]!r} != "
                f"tree at design base {at_base}"
            )
    return True, (
        f"{len(HISTORICAL_ARTIFACT_DIRS)} historical artifact trees equal at design base "
        f"{base}, seal {frozen_sha} and manifest"
    )


def _predecessor_commits_unchanged(
    git: GitCliLike, frozen_sha: str, manifest: Mapping[str, Any]
) -> tuple[bool, str]:
    sealed_raw = _manifest_value(manifest, MANIFEST_KEY_PREDECESSOR_RAW_RUN_SHA)
    sealed_adjudication = _manifest_value(manifest, MANIFEST_KEY_PREDECESSOR_ADJUDICATION_SHA)
    for label, sha in (
        ("raw run", PREDECESSOR_RAW_RUN_SHA),
        ("adjudication", PREDECESSOR_ADJUDICATION_SHA),
    ):
        if not git.is_ancestor(sha, frozen_sha):
            return False, f"predecessor {label} {sha} is NOT an ancestor of seal {frozen_sha}"
    changed = git.changed_paths(PREDECESSOR_ADJUDICATION_SHA, frozen_sha)
    offenders = [p for p in changed if p.startswith(PREDECESSOR_ARTIFACT_DIR)]
    if offenders:
        return False, (
            f"predecessor artifact paths changed since {PREDECESSOR_ADJUDICATION_SHA}: {offenders}"
        )
    if sealed_raw != PREDECESSOR_RAW_RUN_SHA:
        return False, (
            f"manifest[{MANIFEST_KEY_PREDECESSOR_RAW_RUN_SHA!r}] {sealed_raw!r} != frozen "
            f"{PREDECESSOR_RAW_RUN_SHA!r}"
        )
    if sealed_adjudication != PREDECESSOR_ADJUDICATION_SHA:
        return False, (
            f"manifest[{MANIFEST_KEY_PREDECESSOR_ADJUDICATION_SHA!r}] {sealed_adjudication!r} "
            f"!= frozen {PREDECESSOR_ADJUDICATION_SHA!r}"
        )
    return True, (
        f"predecessor raw run {PREDECESSOR_RAW_RUN_SHA} and adjudication "
        f"{PREDECESSOR_ADJUDICATION_SHA} are ancestors of seal {frozen_sha}; no path under "
        f"{PREDECESSOR_ARTIFACT_DIR} changed since the adjudication ({len(changed)} paths "
        "checked); manifest names both"
    )


def _no_raw_artifacts_exist(manifest: Mapping[str, Any], out_dir: Path) -> tuple[bool, str]:
    """The frozen path list comes from the sealed manifest (never from the artifact
    writer); every entry must be a relative path and none may exist under ``out_dir``."""
    sealed = _manifest_value(manifest, MANIFEST_KEY_RAW_ARTIFACT_PATHS)
    if not isinstance(sealed, list):
        return False, f"manifest[{MANIFEST_KEY_RAW_ARTIFACT_PATHS!r}] is not a list"
    if len(sealed) != RAW_ARTIFACT_PATH_COUNT:
        return False, (
            f"manifest[{MANIFEST_KEY_RAW_ARTIFACT_PATHS!r}] lists {len(sealed)} paths, expected "
            f"{RAW_ARTIFACT_PATH_COUNT}"
        )
    if len(set(sealed)) != len(sealed):
        return False, f"manifest[{MANIFEST_KEY_RAW_ARTIFACT_PATHS!r}] repeats a path"
    present: list[str] = []
    for entry in sealed:
        if not isinstance(entry, str) or not entry:
            return (
                False,
                f"manifest[{MANIFEST_KEY_RAW_ARTIFACT_PATHS!r}] entry {entry!r} is not a path",
            )
        relative = Path(entry)
        if relative.is_absolute() or ".." in relative.parts:
            return False, (
                f"manifest[{MANIFEST_KEY_RAW_ARTIFACT_PATHS!r}] entry {entry!r} is not a relative "
                "path inside the experiment directory"
            )
        if (out_dir / relative).exists():
            present.append(entry)
    if present:
        return False, f"raw artifacts already exist under {out_dir}: {present}"
    return True, f"none of the {len(sealed)} raw artifact paths exists under {out_dir}"


# --------------------------------------------------------------------------- verdict shape


class IntegrityVerdict(FrozenModel):
    """One spec §8 verdict. ``passed`` is ``None`` only for a verdict a caller records
    as deliberately not evaluated; ``integrity_verdicts`` never produces it.

    ``applies_to`` is STATIC scope (always both ledgers here). ``failed_ledgers`` is the
    OBSERVED attribution: only the ledgers whose own evidence violated the verdict,
    computed structurally -- never parsed from ``detail`` and never set to
    ``applies_to`` because the verdict failed. It is always a subset of ``applies_to``
    in the canonical order alpha, beta without duplicates; a non-canonical order is
    rejected, not normalised. Only ``passed is False`` may name a ledger; ``passed is
    False`` with ``failed_ledgers == ()`` is an UNATTRIBUTED failure."""

    id: str = Field(min_length=1)
    passed: bool | None
    detail: str
    applies_to: tuple[Ledger, ...]
    failed_ledgers: tuple[Ledger, ...]

    @model_validator(mode="after")
    def _attribution_law(self) -> IntegrityVerdict:
        if len(set(self.failed_ledgers)) != len(self.failed_ledgers):
            raise ValueError(f"failed_ledgers {self.failed_ledgers} names a ledger more than once")
        outside = [ledger for ledger in self.failed_ledgers if ledger not in self.applies_to]
        if outside:
            raise ValueError(
                f"failed_ledgers names {outside} outside the verdict's static scope "
                f"{self.applies_to}"
            )
        canonical = _canonical_ledgers(self.failed_ledgers)
        if self.failed_ledgers != canonical:
            raise ValueError(
                f"failed_ledgers {self.failed_ledgers} is not in the canonical ledger order "
                f"{canonical}; attribution bytes are explicit, never normalised"
            )
        if self.passed is not False and self.failed_ledgers:
            state = "passed" if self.passed is True else "not-evaluated"
            raise ValueError(
                f"a {state} verdict cannot attribute failed ledgers {self.failed_ledgers}; only "
                "passed False may name a ledger"
            )
        return self


def _canonical_ledgers(ledgers: Iterable[Ledger]) -> tuple[Ledger, ...]:
    """The distinct members of ``ledgers`` in the canonical order alpha, beta."""
    present = frozenset(ledgers)
    return tuple(ledger for ledger in _ALL_LEDGERS if ledger in present)


class _Evaluation(NamedTuple):
    """The single internal result shape every verdict produces; aggregated once into
    the public ``IntegrityVerdict`` by ``integrity_verdicts``."""

    passed: bool
    detail: str
    failed_ledgers: tuple[Ledger, ...]


class _LedgerCheck(NamedTuple):
    """One ledger's isolated evaluation of a ledger-local verdict: ``problem`` is
    ``None`` when that ledger's own evidence is clean, else its first violation;
    ``checked`` counts the structural items verified when clean."""

    problem: str | None
    checked: int


_LedgerRule = Callable[[RunResult, LedgerRecord], _LedgerCheck]


_NOT_RUN_SKIPPED: Final = "NOT_RUN (skipped)"


def _not_run_problem(run: RunResult, record: LedgerRecord) -> str | None:
    """Why a ``NOT_RUN`` ledger is a violation of every ledger-local verdict: it carries
    material (an unreached ledger has none), or the run is ``COMPLETED`` (a completed
    run has no unreached ledger). Otherwise it is skipped, not failed."""
    if (
        record.deltas
        or record.ledger_events
        or record.final_state is not None
        or record.final_view is not None
        or record.replay is not None
    ):
        return "NOT_RUN ledger carries deltas, events, state or replay"
    if run.status is RunStatus.COMPLETED:
        return "NOT_RUN ledger in a completed run"
    return None


def _per_ledger(run: RunResult, rule: _LedgerRule, *, ok: Callable[[int], str]) -> _Evaluation:
    """Evaluate ``rule`` over each ledger in isolation, from that ledger's own evidence
    only. Every ledger is evaluated (no cross-ledger short-circuit); a failing ledger is
    named in ``failed_ledgers`` (canonical order) and its problem in ``detail``; an
    exception escaping one ledger's evaluation (``ReferenceSnapshotMismatch`` included)
    fails closed as that ledger's problem and attributes that ledger only. A ``NOT_RUN``
    ledger never reaches ``rule``: it is skipped, or failed by ``_not_run_problem``."""
    failed: list[Ledger] = []
    details: list[str] = []
    for record in run.ledgers:
        ledger = record.ledger
        if record.status == "NOT_RUN":
            problem = _not_run_problem(run, record)
            if problem is None:
                details.append(f"{ledger}: {_NOT_RUN_SKIPPED}")
                continue
            check = _LedgerCheck(problem, 0)
        else:
            try:
                check = rule(run, record)
            except Exception as exc:  # noqa: BLE001 - a ledger that cannot be evaluated failed
                check = _LedgerCheck(f"could not evaluate: {_safe(exc)}", 0)
        if check.problem is not None:
            failed.append(ledger)
            details.append(f"{ledger}: {check.problem}")
        else:
            details.append(f"{ledger}: {ok(check.checked)}")
    return _Evaluation(
        passed=not failed, detail="; ".join(details), failed_ledgers=_canonical_ledgers(failed)
    )


# --------------------------------------------------------------------------- ledger reads


def _ledger_judgments(events: Iterable[StoredEvent]) -> dict[str, SemanticJudgment]:
    """``judgment_id -> judgment`` for every recorded judgment, in ledger order."""
    judgments: dict[str, SemanticJudgment] = {}
    for stored in events:
        payload = stored.event.payload
        if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED and isinstance(
            payload, SemanticJudgmentPayload
        ):
            judgments[payload.judgment.judgment_id] = payload.judgment
    return judgments


def _ledger_admissions(events: Iterable[StoredEvent]) -> dict[str, SemanticAdmissionPayload]:
    """``judgment_id -> latest admission`` in ledger order."""
    admissions: dict[str, SemanticAdmissionPayload] = {}
    for stored in events:
        payload = stored.event.payload
        if stored.event.event_type is EventType.SEMANTIC_ADMISSION_DECIDED and isinstance(
            payload, SemanticAdmissionPayload
        ):
            admissions[payload.judgment_id] = payload
    return admissions


def _delta_label(record: LedgerRecord, delta: DeltaRecord) -> str:
    return f"{record.ledger} T{delta.t}"


def _completed_deltas(record: LedgerRecord) -> tuple[DeltaRecord, ...]:
    """The deltas that ran to completion: every delta of a ``COMPLETED`` ledger; of a
    ``FAILED`` ledger every delta but the last (the walk begins a delta only after the
    previous one completed, and stops at the first failure)."""
    if record.status == "COMPLETED":
        return record.deltas
    return record.deltas[:-1]


def _segments(record: LedgerRecord) -> tuple[tuple[DeltaRecord, tuple[StoredEvent, ...]], ...]:
    """Each delta with the ledger events its walk appended: the events after the
    previous delta's captured ``last_sequence`` up to its own (the last delta: to the
    ledger's end). Purely by sequence; no event content is read."""
    events = record.ledger_events
    segments: list[tuple[DeltaRecord, tuple[StoredEvent, ...]]] = []
    start = 0
    for index, delta in enumerate(record.deltas):
        state = delta.state_snapshot
        if index == len(record.deltas) - 1:
            end = state.last_sequence if state is not None else len(events)
        elif state is None:
            raise RuntimeError(
                f"{_delta_label(record, delta)}: no state snapshot; its event segment cannot "
                "be bounded"
            )
        else:
            end = state.last_sequence
        segments.append((delta, tuple(e for e in events if start < e.sequence <= end)))
        start = end
    return tuple(segments)


def _calls(
    record: LedgerRecord, delta: DeltaRecord, segment: tuple[StoredEvent, ...]
) -> tuple[CallJudgments, ...]:
    """Pair, in order, ``requests[i]`` with ``reference_snapshots[i]`` and the model
    judgments recorded for that call: the ids of ``stage_decisions[i]`` resolved in
    the delta's own ledger segment. A failed delta records no decisions: with one
    request every judgment of its segment belongs to Call 1; with none, no judgment may
    exist; anything else cannot be attributed and is raised for the caller."""
    label = _delta_label(record, delta)
    judgments = _ledger_judgments(segment)
    pairs = tuple(zip(delta.requests, delta.reference_snapshots, strict=False))
    if delta.stage_decisions == ((), ()):
        if not pairs:
            if judgments:
                raise RuntimeError(f"{label}: {len(judgments)} judgments recorded with no request")
            return ()
        if len(pairs) != 1:
            raise RuntimeError(
                f"{label}: {len(pairs)} requests but no stage decisions; judgments cannot be "
                "attributed to a call"
            )
        request, snapshot = pairs[0]
        return (CallJudgments(request, snapshot, tuple(judgments.values())),)
    calls: list[CallJudgments] = []
    for index, (request, snapshot) in enumerate(pairs):
        decisions = delta.stage_decisions[index] if index < len(delta.stage_decisions) else ()
        resolved: list[SemanticJudgment] = []
        for decision in decisions:
            judgment = judgments.get(decision.judgment_id)
            if judgment is None:
                raise RuntimeError(
                    f"{label}: decision for {decision.judgment_id} has no recorded judgment in "
                    "the delta's ledger segment"
                )
            resolved.append(judgment)
        calls.append(CallJudgments(request, snapshot, tuple(resolved)))
    return tuple(calls)


# --------------------------------------------------------------------------- L1-L5


def _l1_for_ledger(run: RunResult, record: LedgerRecord) -> _LedgerCheck:
    checked = 0
    for delta in _completed_deltas(record):
        numbers = tuple(request.call_number for request in delta.requests)
        if numbers != _EXPECTED_CALL_NUMBERS:
            return _LedgerCheck(
                f"{_delta_label(record, delta)} completed with call numbers {numbers}, "
                "expected (1, 2)",
                0,
            )
        if len(delta.reference_snapshots) != len(delta.requests):
            return _LedgerCheck(
                f"{_delta_label(record, delta)} completed with {len(delta.reference_snapshots)} "
                f"reference snapshots for {len(delta.requests)} requests",
                0,
            )
        checked += 1
    if record.status == "COMPLETED" and tuple(d.t for d in record.deltas) != DELTAS:
        return _LedgerCheck(
            f"completed ledger walked deltas {[d.t for d in record.deltas]}, expected "
            f"{list(DELTAS)}",
            0,
        )
    return _LedgerCheck(None, checked)


def _l1(run: RunResult) -> _Evaluation:
    return _per_ledger(
        run, _l1_for_ledger, ok=lambda n: f"{n} completed delta(s) each made exactly calls (1, 2)"
    )


def _l2_for_ledger(run: RunResult, record: LedgerRecord) -> _LedgerCheck:
    seen: dict[str, str] = {}
    checked = 0
    for delta in record.deltas:
        label = _delta_label(record, delta)
        if len(delta.requests) > CALLS_PER_DELTA:
            return _LedgerCheck(
                f"{label} made {len(delta.requests)} calls; a third call is a retry or phase", 0
            )
        numbers = tuple(request.call_number for request in delta.requests)
        if numbers != _EXPECTED_CALL_NUMBERS[: len(numbers)]:
            return _LedgerCheck(f"{label} call numbers {numbers} are not a prefix of (1, 2)", 0)
        for request in delta.requests:
            call = f"{label} call {request.call_number}"
            if request.request_sha256 in seen:
                return _LedgerCheck(
                    f"duplicate request identity {request.request_sha256} at {call} and "
                    f"{seen[request.request_sha256]} (retry shape)",
                    0,
                )
            seen[request.request_sha256] = call
            checked += 1
    return _LedgerCheck(None, checked)


def _l2(run: RunResult) -> _Evaluation:
    """Ledger-local shape (third call, retry identity) plus the intrinsically global
    budget conditions: every admitted frontier call is a recorded request (an admitted
    but unanswered call is the recorded asymmetry) and no judge call exists."""
    local = _per_ledger(
        run, _l2_for_ledger, ok=lambda n: f"{n} distinct request(s), at most two per delta"
    )
    problems: list[str] = [] if local.passed else [local.detail]
    records = sum(
        len(delta.requests)
        for record in run.ledgers
        if record.status != "NOT_RUN"
        for delta in record.deltas
    )
    if records != run.budget.frontier_calls:
        problems.append(
            f"{records} request records but {run.budget.frontier_calls} frontier calls admitted"
        )
    if run.budget.judge_calls != MAX_JUDGE_CALLS:
        problems.append(f"{run.budget.judge_calls} judge calls recorded; no judge exists")
    if problems:
        return _Evaluation(False, "; ".join(problems), local.failed_ledgers)
    return _Evaluation(
        True,
        f"{local.detail}; {records} request records == {run.budget.frontier_calls} frontier "
        "calls; no judge call",
        (),
    )


def _l3_for_ledger(run: RunResult, record: LedgerRecord) -> _LedgerCheck:
    """The frozen 9P3 law over this ledger's calls only; a ``ReferenceSnapshotMismatch``
    raised by the binding check escapes to ``_per_ledger``, which attributes this
    ledger."""
    calls: list[CallJudgments] = []
    for delta, segment in _segments(record):
        calls.extend(_calls(record, delta, segment))
    passed, detail = request_only_reference_check(tuple(calls))
    if not passed:
        return _LedgerCheck(detail, 0)
    return _LedgerCheck(None, len(calls))


def _l3(run: RunResult) -> _Evaluation:
    return _per_ledger(
        run,
        _l3_for_ledger,
        ok=lambda n: (
            "every reference resolves against its exact request; no same-response id used "
            f"({n} calls checked)"
        ),
    )


def _l4_for_ledger(run: RunResult, record: LedgerRecord) -> _LedgerCheck:
    if record.status != "COMPLETED":
        return _LedgerCheck(None, 0)
    if record.final_state is None:
        return _LedgerCheck("completed ledger carries no final state", 0)
    if record.replay is None:
        return _LedgerCheck("no replay result was recorded", 0)
    if record.replay.status != "REPLAY_MATCH":
        return _LedgerCheck(f"recorded replay {record.replay.status}", 0)
    if record.replay.event_count != len(record.ledger_events):
        return _LedgerCheck(
            f"recorded replay covered {record.replay.event_count} events, ledger holds "
            f"{len(record.ledger_events)}",
            0,
        )
    recomputed = replay_matches(record.ledger_events, record.final_state)
    if recomputed.status != "REPLAY_MATCH":
        return _LedgerCheck("replay of the ledger does not reproduce the final state/view", 0)
    return _LedgerCheck(None, 1)


def _l4(run: RunResult) -> _Evaluation:
    return _per_ledger(
        run,
        _l4_for_ledger,
        ok=lambda n: (
            f"{n} completed ledger(s) replay exactly" if n else "not completed (no replay owed)"
        ),
    )


def _l5_for_ledger(run: RunResult, record: LedgerRecord) -> _LedgerCheck:
    events = record.ledger_events
    if [stored.sequence for stored in events] != list(range(1, len(events) + 1)):
        return _LedgerCheck(f"ledger sequences are not contiguous from 1 ({len(events)} events)", 0)
    if record.final_state is not None and record.final_state.last_sequence != len(events):
        return _LedgerCheck(
            f"final state last_sequence {record.final_state.last_sequence} != {len(events)} "
            "ledger events",
            0,
        )
    exposed = any(delta.receipts for ledger in run.ledgers for delta in ledger.deltas)
    checked = 0
    for delta, segment in _segments(record):
        label = _delta_label(record, delta)
        if len(delta.reference_snapshots) != len(delta.requests):
            return _LedgerCheck(
                f"{label}: {len(delta.reference_snapshots)} reference snapshots for "
                f"{len(delta.requests)} requests",
                0,
            )
        if len(delta.receipts) > len(delta.requests):
            return _LedgerCheck(
                f"{label}: {len(delta.receipts)} receipts for {len(delta.requests)} requests", 0
            )
        completed = delta.stage_decisions != ((), ())
        if completed and exposed and len(delta.receipts) != len(delta.requests):
            return _LedgerCheck(
                f"{label}: {len(delta.receipts)} receipts for {len(delta.requests)} requests", 0
            )
        recorded = _ledger_judgments(segment)
        admissions = _ledger_admissions(segment)
        for judgment_id in recorded:
            if judgment_id not in admissions:
                return _LedgerCheck(f"{label}: judgment {judgment_id} has no admission event", 0)
        if completed:
            decided = [d.judgment_id for stage in delta.stage_decisions for d in stage]
            if len(set(decided)) != len(decided):
                return _LedgerCheck(f"{label}: a judgment id is decided twice", 0)
            if sorted(recorded) != sorted(decided):
                return _LedgerCheck(
                    f"{label}: ledger segment records judgments {sorted(recorded)} but stage "
                    f"decisions name {sorted(decided)}",
                    0,
                )
        elif not delta.requests and recorded:
            return _LedgerCheck(f"{label}: {len(recorded)} judgments recorded with no request", 0)
        checked += len(delta.requests)
    return _LedgerCheck(None, checked)


def _l5(run: RunResult) -> _Evaluation:
    return _per_ledger(
        run,
        _l5_for_ledger,
        ok=lambda n: f"{n} request(s): snapshots, receipts and ledger events reconcile one-to-one",
    )


# --------------------------------------------------------------------------- L6-L9


def _l6(run: RunResult) -> _Evaluation:
    """No human authority exists in this experiment (ceiling 0), so every judgment is
    model-originated and an applied ``SUPERSEDE`` of any origin is a violation of the
    owning ledger; a non-zero human-authorization tally is a global violation."""
    failed: list[Ledger] = []
    problems: list[str] = []
    pending = 0
    for record in run.ledgers:
        admissions = _ledger_admissions(record.ledger_events)
        for judgment_id, judgment in _ledger_judgments(record.ledger_events).items():
            if judgment.kind is not JudgmentKind.SUPERSEDE:
                continue
            admission = admissions.get(judgment_id)
            if admission is not None and admission.route is AdmissionRoute.APPLY:
                failed.append(record.ledger)
                problems.append(f"{record.ledger}: SUPERSEDE {judgment_id} was routed APPLY")
            else:
                pending += 1
        state = record.final_state
        if state is not None and state.semantic.supersessions:
            failed.append(record.ledger)
            problems.append(
                f"{record.ledger}: final state carries {len(state.semantic.supersessions)} "
                "applied supersession(s)"
            )
    if run.budget.human_authorizations != MAX_HUMAN_AUTHORIZATIONS:
        problems.append(
            f"{run.budget.human_authorizations} human authorizations recorded; none may exist"
        )
    if problems:
        return _Evaluation(False, "; ".join(problems), _canonical_ledgers(failed))
    return _Evaluation(
        True, f"{pending} SUPERSEDE proposal(s), none applied; 0 human authorizations", ()
    )


def _l7(run: RunResult) -> _Evaluation:
    failed: list[Ledger] = []
    problems: list[str] = []
    for record in run.ledgers:
        if record.error is not None and record.error.startswith(_IDENTITY_DRIFT_PREFIX):
            failed.append(record.ledger)
            problems.append(f"{record.ledger}: identity guard tripped: {record.error}")
    if run.status is RunStatus.ABORTED_IDENTITY:
        problems.append(f"run status {run.status.value}")
    if run.error is not None and run.error.startswith(_IDENTITY_DRIFT_PREFIX):
        problems.append(f"run error: {run.error}")
    if problems:
        return _Evaluation(False, "; ".join(problems), _canonical_ledgers(failed))
    return _Evaluation(True, "identity guard never tripped", ())


def _l8(run: RunResult) -> _Evaluation:
    problems: list[str] = []
    try:
        cost = Decimal(run.budget.provider_cost_usd)
    except InvalidOperation:
        return _Evaluation(
            False, f"provider cost {run.budget.provider_cost_usd!r} is not a decimal", ()
        )
    if cost > _COST_CEILING:
        problems.append(f"provider cost {cost} USD exceeds ceiling {_COST_CEILING} USD")
    if run.budget.frontier_calls > MAX_FRONTIER_CALLS:
        problems.append(
            f"{run.budget.frontier_calls} frontier calls exceed ceiling {MAX_FRONTIER_CALLS}"
        )
    if problems:
        return _Evaluation(False, "; ".join(problems), ())
    return _Evaluation(
        True,
        f"provider cost {run.budget.provider_cost_usd} USD <= {_COST_CEILING} USD; "
        f"{run.budget.frontier_calls} frontier calls <= {MAX_FRONTIER_CALLS}",
        (),
    )


def _l9(case_results: tuple[CaseResult, ...]) -> _Evaluation:
    """Every case whose structural assertion set was evaluated must hold; the results
    must cover every (ledger, case) of the table exactly once."""
    expected = {(ledger, case_id) for ledger in _ALL_LEDGERS for case_id in CASE_IDS}
    seen = [(result.ledger, result.case_id) for result in case_results]
    problems: list[str] = []
    if len(set(seen)) != len(seen):
        problems.append("a (ledger, case) is reported more than once")
    missing = sorted(expected - set(seen))
    if missing:
        problems.append(f"no result for {missing}")
    unknown = sorted(set(seen) - expected)
    if unknown:
        problems.append(f"results outside the case table: {unknown}")
    failed: list[Ledger] = []
    for result in case_results:
        if result.structural_passed is False:
            failed.append(result.ledger)
            problems.append(f"{result.ledger} {result.case_id} FAILED {list(result.tags)}")
    if problems:
        return _Evaluation(False, "; ".join(problems), _canonical_ledgers(failed))
    evaluated = sum(1 for result in case_results if result.structural_passed is True)
    skipped = len(case_results) - evaluated
    return _Evaluation(
        True,
        f"{evaluated} case assertion set(s) hold; {skipped} not evaluated (delta not run)",
        (),
    )


def integrity_verdicts(
    run: RunResult,
    *,
    preflight_gates: tuple[GateResult, ...],
    case_results: tuple[CaseResult, ...],
) -> tuple[IntegrityVerdict, ...]:
    """The nine spec §8 verdicts over ``run`` and the T4 ``case_results``. The preflight
    tuple is carried for the record (rule 0 treats a failed live gate as invalidity
    upstream of these verdicts; no verdict here consumes a gate). Each verdict's
    ``_Evaluation`` is aggregated once into the public verdict; an exception escaping a
    whole verdict fails closed as ``passed False`` with ``failed_ledgers ()``, while
    one escaping an isolated per-ledger evaluation is caught inside that verdict and
    attributes that ledger only. ``passed`` is never ``None`` here."""
    del preflight_gates
    plan: tuple[tuple[str, Callable[[], _Evaluation]], ...] = (
        ("L1", lambda: _l1(run)),
        ("L2", lambda: _l2(run)),
        ("L3", lambda: _l3(run)),
        ("L4", lambda: _l4(run)),
        ("L5", lambda: _l5(run)),
        ("L6", lambda: _l6(run)),
        ("L7", lambda: _l7(run)),
        ("L8", lambda: _l8(run)),
        ("L9", lambda: _l9(case_results)),
    )
    if tuple(verdict_id for verdict_id, _ in plan) != VERDICT_IDS:
        raise RuntimeError("verdict plan does not enumerate VERDICT_IDS")
    verdicts: list[IntegrityVerdict] = []
    for verdict_id, evaluate in plan:
        try:
            evaluation = evaluate()
        except Exception as exc:  # noqa: BLE001 - a verdict that cannot run fails closed
            evaluation = _Evaluation(False, f"could not evaluate: {_safe(exc)}", ())
        verdicts.append(
            IntegrityVerdict(
                id=verdict_id,
                passed=evaluation.passed,
                detail=evaluation.detail,
                applies_to=_ALL_LEDGERS,
                failed_ledgers=evaluation.failed_ledgers,
            )
        )
    return tuple(verdicts)

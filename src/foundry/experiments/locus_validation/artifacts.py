"""Sealed preregistration, the identity-consuming write, the write-once raw evidence
tree and the guarded architect adjudication writer of the locus-policy live-validation
experiment (spec §10, §11, §13, §14, §16).

Four artifact families live under the experiment directory:

* **preregistration** (``PREREGISTRATION_FILE_NAMES``): ``manifest.json`` -- the typed
  ``ExperimentManifest`` sealing the frozen identity (harness SHA, baseline, spec SHA,
  provider / model / effort / resolver, the locus policy version and prompt hash, the
  two historical prompt hashes, the output-schema hash, the call schedule, both
  ledgers, the 16 evidence records and their corpus hash, the typed needle-set hash,
  the canonical ``expectations_sha256``, the six ceilings as numbers, the
  historical-preservation base and the seven directory tree hashes, both predecessor
  commits and the 21 raw artifact paths) -- and ``expectations.json`` -- exactly
  ``expectations_document()``, pretty-printed. No self-referential seal SHA is
  embedded: the seal commit is identified by ``FINAL_SEAL_RULE`` and checked by
  ``integrity`` gate 1 at run time. Every gate-read field is spelled exactly as
  ``integrity.REQUIRED_MANIFEST_KEYS`` (checked at import).
* **consumption** (``CONSUMPTION_PATHS``): ``write_consumption`` is THE
  identity-consuming write of spec §10, performed once, immediately before the first
  provider-call attempt. It refuses -- writing nothing -- when any raw artifact
  exists or any preflight gate failed, then writes ``preflight.json`` (the passing
  preflight document) and, last, ``consumption.json`` (seal sha, harness sha, policy
  version, prompt hash, model configuration, UTC timestamp), each atomically. Neither
  ever carries a key or a secret-shaped value.
* **raw live artifacts** (the other 19 of ``RAW_ARTIFACT_PATHS``): ``write_run_artifacts``
  requires both consumption files to exist (a raw tree can never exist without a
  consumption record) and none of the 19, then writes them all-or-nothing: eight files
  per ledger (a ``NOT_RUN`` ledger included, so the frozen shape is constant),
  ``measurements.json``, ``verdicts.json`` and ``report.md``.
* **adjudication**: ``write_adjudication`` rewrites exactly ``verdicts.json`` and
  ``report.md`` -- and only after proving that no provider key is present, HEAD is the
  raw-run commit, the worktree is clean and every one of the 21 raw files is
  byte-identical to what that commit holds; afterwards it proves the other 19 files
  unchanged. It is write-once.

Two phases, hard boundary (spec §11). The raw phase carries NO semantic decision:
``verdicts.json`` holds the L1-L9 ``IntegrityVerdict`` dumps (``passed``, ``detail``,
static ``applies_to`` and the observed ``failed_ledgers`` attribution) and the §7.1
case assertion results; ``semantic_assertions``, ``semantic_notes``, ``case_outcomes``
and the experiment outcome are ``null`` -- except that the outcome may already be
``EXPERIMENT_INCONCLUSIVE`` when spec §14 rule 0 holds from deterministic facts alone
(the run did not complete, or one of L1-L8 did not pass), and even then
``case_outcomes`` stay ``null``. ``report.md`` carries the literal
``ADJUDICATION_PENDING_LINE`` while the outcome is null. The raw writers never
reference the validated / not-validated outcome names and never reach
``expectations.experiment_outcome``: it is called by ``write_adjudication`` alone,
with the architect's binary answers to §7.2 and the committed structural results.

Sealing. ``canonical_sha256`` / ``pretty_json`` are the frozen 9P2 functions, imported:
seal hashes are always taken over parsed data, never pretty bytes.

Secret hygiene. No API key or auth value is accepted by any function here; the
adjudication writer checks the provider key by NAME only and never reads a value. A
secret shape inside any exact ``rendered_user_request`` (scientific request material)
refuses the whole raw write -- scientific material is never redacted. ``redact_secrets``
is applied ONLY to diagnostic text (errors, verdict and gate details, case details,
adjudication notes). As a last fail-closed guard, a document that still carries a
secret shape after that is refused, never written.

Law of this module: it records structural facts and decides nothing about meaning. It
may import ``expectations`` because it never enters the provider request path; it
constructs no reasoner, makes no network call, never reads the process environment
(the adjudication ``env`` is injected), never runs git itself (``GitCliLike`` is
injected) and never writes outside ``out_dir``. It names no historical experiment
directory except through the frozen ``protocol`` constants and never touches one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from pydantic import Field, StrictBool, model_validator

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION,
    LOCUS_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    SYSTEM_INSTRUCTION,
    semantic_output_schema_sha256,
)
from foundry.domain.common import FrozenModel
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256, pretty_json
from foundry.experiments.contrastive_unseen.integrity import GateResult, all_passed
from foundry.experiments.contrastive_unseen.records import RequestRecord
from foundry.experiments.locus_validation.corpus import (
    DOCUMENTS,
    LEDGERS,
    PROJECT_IDS,
    SCOPES,
    EvidenceRecord,
    Ledger,
    corpus_sha256,
    evidence_records,
)
from foundry.experiments.locus_validation.evaluation import CaseResult
from foundry.experiments.locus_validation.expectations import (
    CASE_IDS,
    CASE_OUTCOME_RULES,
    OUTCOMES,
    SEMANTIC_ASSERTION_IDS,
    expectations_document,
    experiment_outcome,
)
from foundry.experiments.locus_validation.integrity import (
    GATE_NAMES,
    LOCKED_CEILINGS,
    RAW_ARTIFACT_PATH_COUNT,
    REQUIRED_MANIFEST_KEYS,
    VERDICT_IDS,
    GitCliLike,
    IntegrityVerdict,
)
from foundry.experiments.locus_validation.leakage import LeakageResult, needle_set_sha256
from foundry.experiments.locus_validation.protocol import (
    ARTIFACT_FORMAT_VERSION,
    BASELINE_SHA,
    CALLS_PER_DELTA,
    CEILING_KEYS,
    DELTAS,
    DESIGN_BASE_SHA,
    EXPERIMENT_VERSION,
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
from foundry.experiments.long_horizon_bounded.runner import RequestReferenceSnapshot
from foundry.experiments.longitudinal.artifacts import contains_secret_shape, redact_secrets

__all__ = [
    "ADJUDICATION_PENDING_LINE",
    "CONSUMPTION_PATHS",
    "FINAL_SEAL_RULE",
    "PREREGISTRATION_FILE_NAMES",
    "RAW_ARTIFACT_PATHS",
    "RUN_ARTIFACT_PATHS",
    "SPEC_PATH",
    "Adjudication",
    "AdjudicationRefused",
    "Ceilings",
    "ConsumptionRefused",
    "ExperimentManifest",
    "LedgerSpec",
    "build_manifest",
    "existing_raw_artifacts",
    "expectations_json",
    "manifest_sha256",
    "render_report",
    "verdicts_document",
    "write_adjudication",
    "write_consumption",
    "write_preregistration",
    "write_run_artifacts",
]

# --------------------------------------------------------------------------- literals

SPEC_PATH: Final = "docs/superpowers/specs/2026-09-15-locus-policy-live-validation-design.md"
FINAL_SEAL_RULE: Final = (
    "live HEAD must equal --frozen-sha; its single parent must equal harness_code_sha; "
    "parent..HEAD may add only manifest.json and expectations.json"
)
ADJUDICATION_PENDING_LINE: Final = "experiment_outcome = null (architect adjudication pending)"

_LEDGER_FILES: Final[tuple[str, ...]] = (
    "requests",
    "drafts",
    "receipts",
    "decisions",
    "ledger",
    "state_T1",
    "state_T2",
    "result",
)
RAW_ARTIFACT_PATHS: Final[tuple[str, ...]] = (
    "consumption.json",
    "preflight.json",
    "measurements.json",
    "verdicts.json",
    "report.md",
    *(f"L-{ledger}/{name}.json" for ledger in LEDGERS for name in _LEDGER_FILES),
)
"""Spec §13: every raw live artifact path relative to the experiment directory,
5 + 2 x 8 = 21. Gate 18 refuses to consume when any of them exists."""

CONSUMPTION_PATHS: Final[tuple[str, ...]] = ("consumption.json", "preflight.json")
"""The two files of the consuming write (spec §10); written preflight first,
consumption last."""

RUN_ARTIFACT_PATHS: Final[tuple[str, ...]] = tuple(
    path for path in RAW_ARTIFACT_PATHS if path not in CONSUMPTION_PATHS
)
"""The other 19 raw paths, written once by ``write_run_artifacts``."""

_RAW_PHASE: Final = "raw"
_ADJUDICATED_PHASE: Final = "adjudicated"
_OUTCOME_KEY: Final = "experiment_outcome"
_OUTCOME_LINE_PREFIX: Final = "experiment_outcome = "
_INCONCLUSIVE: Final = "EXPERIMENT_INCONCLUSIVE"
_RULE_ZERO_VERDICT_IDS: Final[tuple[str, ...]] = VERDICT_IDS[:8]
"""Spec §14 rule 0: any of L1-L8 failing invalidates the experiment; L9 (the §7.1 case
assertion sets) is a per-case FAIL, never invalidity."""
_PROVIDER_KEY_ENV: Final = "XAI_API_KEY"
_TREE_SHA: Final = re.compile(r"^[0-9a-f]{40}$")
_TEMP_PREFIX: Final = ".locus-validation-"
_ARM: Final = "F"


def _require_path_contract() -> None:
    if len(RAW_ARTIFACT_PATHS) != RAW_ARTIFACT_PATH_COUNT:
        raise RuntimeError(
            f"RAW_ARTIFACT_PATHS lists {len(RAW_ARTIFACT_PATHS)} paths, spec §13 fixes "
            f"{RAW_ARTIFACT_PATH_COUNT}"
        )
    if len(set(RAW_ARTIFACT_PATHS)) != len(RAW_ARTIFACT_PATHS):
        raise RuntimeError("RAW_ARTIFACT_PATHS repeats a path")
    if _INCONCLUSIVE not in OUTCOMES:
        raise RuntimeError(f"{_INCONCLUSIVE!r} is not in the frozen outcome vocabulary")
    if tuple(f"L{n}" for n in range(1, 9)) != _RULE_ZERO_VERDICT_IDS:
        raise RuntimeError(f"rule 0 verdict ids are {_RULE_ZERO_VERDICT_IDS}, expected L1..L8")


_require_path_contract()


# --------------------------------------------------------------------------- manifest


class Ceilings(FrozenModel):
    """Spec §12 ceilings as NUMBERS; field names are exactly ``protocol.CEILING_KEYS``."""

    max_frontier_calls: int = Field(ge=0)
    max_judge_calls: int = Field(ge=0)
    max_semantic_retries: int = Field(ge=0)
    max_same_cell_reruns: int = Field(ge=0)
    max_human_authorizations: int = Field(ge=0)
    max_provider_cost_usd: float = Field(ge=0.0)


class LedgerSpec(FrozenModel):
    """One ledger of spec §4: id, project, scope and document order (structural only)."""

    id: Ledger
    project_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    documents: tuple[str, ...] = Field(min_length=1)


class ExperimentManifest(FrozenModel):
    """Spec §16 sealed manifest. Every gate-read field is spelled exactly as the
    ``integrity.MANIFEST_KEY_*`` names (checked at import). The historical-preservation
    base and directory list are frozen literals -- never the harness HEAD -- and the
    per-directory tree hashes are inputs the seal tooling reads from git at that base."""

    experiment_version: str = Field(min_length=1)
    artifact_format_version: int = ARTIFACT_FORMAT_VERSION
    harness_code_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    baseline_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    final_seal_rule: str = Field(min_length=1)
    spec_path: str = Field(min_length=1)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)
    grpc_dns_resolver: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_prompt_sha256s: dict[str, str]
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calls_per_delta: int = Field(ge=1)
    ledgers: tuple[LedgerSpec, ...]
    evidence: tuple[EvidenceRecord, ...]
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    leakage_needle_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ceilings: Ceilings
    historical_preservation_base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    historical_artifact_dirs: tuple[str, ...]
    historical_artifact_tree_hashes: dict[str, str]
    predecessor_raw_run_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    predecessor_adjudication_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    raw_artifact_paths: tuple[str, ...]


def _require_manifest_keys() -> None:
    missing = [key for key in REQUIRED_MANIFEST_KEYS if key not in ExperimentManifest.model_fields]
    if missing:
        raise RuntimeError(f"ExperimentManifest lacks gate-read manifest keys {missing}")
    if tuple(Ceilings.model_fields) != CEILING_KEYS:
        raise RuntimeError(
            f"Ceilings fields {tuple(Ceilings.model_fields)} != CEILING_KEYS {CEILING_KEYS}"
        )


_require_manifest_keys()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_frozen_identity() -> None:
    """The in-process adapter identity and the ``protocol`` literals must agree before
    anything is sealed; a drift is a preflight failure waiting to happen, not a
    manifest."""
    checks: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("locus policy", (LOCUS_POLICY_VERSION, POLICY_VERSION_FROZEN)),
        (
            "locus prompt sha256",
            (
                _sha256(LOCUS_SYSTEM_INSTRUCTION),
                LOCUS_SYSTEM_INSTRUCTION_SHA256,
                PROMPT_SHA256_FROZEN,
            ),
        ),
        (
            "output schema sha256",
            (
                semantic_output_schema_sha256(),
                SEMANTIC_OUTPUT_SCHEMA_SHA256,
                OUTPUT_SCHEMA_SHA256_FROZEN,
            ),
        ),
        (
            "historical 9p prompt sha256",
            (_sha256(SYSTEM_INSTRUCTION), HISTORICAL_PROMPT_SHA256S.get(POLICY_VERSION, "")),
        ),
        (
            "historical 9p2 prompt sha256",
            (
                _sha256(CONTRASTIVE_SYSTEM_INSTRUCTION),
                HISTORICAL_PROMPT_SHA256S.get(CONTRASTIVE_POLICY_VERSION, ""),
            ),
        ),
    )
    drift = [f"{label}: {list(values)}" for label, values in checks if len(set(values)) != 1]
    if drift:
        raise RuntimeError(
            "frozen identity drift; refusing to build a manifest: " + "; ".join(drift)
        )


def _validated_tree_hashes(hashes: Mapping[str, str]) -> dict[str, str]:
    """Exactly the seven frozen directories, each mapped to a 40-hex git tree sha, in
    ``HISTORICAL_ARTIFACT_DIRS`` order."""
    missing = [directory for directory in HISTORICAL_ARTIFACT_DIRS if directory not in hashes]
    if missing:
        raise ValueError(f"historical_tree_hashes is missing {missing}")
    unexpected = sorted(set(hashes) - set(HISTORICAL_ARTIFACT_DIRS))
    if unexpected:
        raise ValueError(f"historical_tree_hashes carries unexpected directories {unexpected}")
    malformed = [
        f"{directory}={hashes[directory]!r}"
        for directory in HISTORICAL_ARTIFACT_DIRS
        if not isinstance(hashes[directory], str) or not _TREE_SHA.fullmatch(hashes[directory])
    ]
    if malformed:
        raise ValueError(f"historical_tree_hashes values must be 40-hex git tree shas: {malformed}")
    return {directory: hashes[directory] for directory in HISTORICAL_ARTIFACT_DIRS}


def build_manifest(
    *, harness_code_sha: str, spec_sha256: str, historical_tree_hashes: Mapping[str, str]
) -> ExperimentManifest:
    """The sealed manifest for ``harness_code_sha`` (the clean pre-seal HEAD), the exact
    spec bytes' SHA256 and the seven historical tree hashes read at the design base.
    Everything else is a frozen literal or a ``corpus`` / ``protocol`` / ``expectations``
    / ``leakage`` value; nothing is derived from the environment, git or the clock."""
    _require_frozen_identity()
    return ExperimentManifest(
        experiment_version=EXPERIMENT_VERSION,
        artifact_format_version=ARTIFACT_FORMAT_VERSION,
        harness_code_sha=harness_code_sha,
        baseline_sha=BASELINE_SHA,
        final_seal_rule=FINAL_SEAL_RULE,
        spec_path=SPEC_PATH,
        spec_sha256=spec_sha256,
        provider=PROVIDER,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        grpc_dns_resolver=GRPC_DNS_RESOLVER_FROZEN,
        policy_version=POLICY_VERSION_FROZEN,
        prompt_sha256=PROMPT_SHA256_FROZEN,
        historical_prompt_sha256s=dict(HISTORICAL_PROMPT_SHA256S),
        output_schema_sha256=OUTPUT_SCHEMA_SHA256_FROZEN,
        calls_per_delta=CALLS_PER_DELTA,
        ledgers=tuple(
            LedgerSpec(
                id=ledger,
                project_id=PROJECT_IDS[ledger],
                scope=SCOPES[ledger],
                documents=DOCUMENTS[ledger],
            )
            for ledger in LEDGERS
        ),
        evidence=evidence_records(),
        corpus_sha256=corpus_sha256(),
        leakage_needle_set_sha256=needle_set_sha256(),
        expectations_sha256=canonical_sha256(expectations_document()),
        ceilings=Ceilings(
            max_frontier_calls=MAX_FRONTIER_CALLS,
            max_judge_calls=MAX_JUDGE_CALLS,
            max_semantic_retries=MAX_SEMANTIC_RETRIES,
            max_same_cell_reruns=MAX_SAME_CELL_RERUNS,
            max_human_authorizations=MAX_HUMAN_AUTHORIZATIONS,
            max_provider_cost_usd=MAX_COST_USD,
        ),
        historical_preservation_base_sha=DESIGN_BASE_SHA,
        historical_artifact_dirs=HISTORICAL_ARTIFACT_DIRS,
        historical_artifact_tree_hashes=_validated_tree_hashes(historical_tree_hashes),
        predecessor_raw_run_sha=PREDECESSOR_RAW_RUN_SHA,
        predecessor_adjudication_sha=PREDECESSOR_ADJUDICATION_SHA,
        raw_artifact_paths=RAW_ARTIFACT_PATHS,
    )


def manifest_sha256(manifest: ExperimentManifest) -> str:
    return canonical_sha256(manifest)


def expectations_json() -> str:
    """The on-disk ``expectations.json`` text: exactly ``expectations_document()``."""
    return pretty_json(expectations_document())


def _ceilings_match_locked(ceilings: Ceilings) -> None:
    dumped = ceilings.model_dump(mode="json")
    if dumped != LOCKED_CEILINGS:
        raise ValueError(
            f"manifest ceilings {dumped} != locked {LOCKED_CEILINGS}; refusing to seal"
        )


# --------------------------------------------------------------------------- writing


def _refuse_existing(out_dir: Path, names: Iterable[str]) -> None:
    """Check EVERY target before writing ANY, so a recorded artifact is never partially
    replaced."""
    existing = [name for name in names if (out_dir / name).exists()]
    if existing:
        raise FileExistsError(
            f"refusing to overwrite existing artifact(s) under {out_dir}: {existing}"
        )


def _refuse_secret_shapes(documents: Mapping[str, str], *, phase: str) -> None:
    """Last fail-closed guard: nothing secret-shaped is ever written, and nothing
    non-diagnostic is ever altered to make it so."""
    offenders = [name for name, text in documents.items() if contains_secret_shape(text)]
    if offenders:
        raise ValueError(
            f"secret-shaped token remains in {phase} document(s) {offenders}; refusing to write"
        )


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=_TEMP_PREFIX, suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_all(out_dir: Path, documents: Mapping[str, str], *, phase: str) -> tuple[str, ...]:
    """Guard every document, refuse if any target exists, then write each atomically in
    the mapping's order."""
    _refuse_secret_shapes(documents, phase=phase)
    _refuse_existing(out_dir, documents)
    for name, text in documents.items():
        _write_atomic(out_dir / name, text)
    return tuple(documents)


def write_preregistration(out_dir: Path, manifest: ExperimentManifest) -> dict[str, str]:
    """Write exactly ``manifest.json`` and ``expectations.json``; refuse -- writing
    nothing -- if either exists.

    The manifest's ``expectations_sha256`` must equal the canonical hash of the document
    written next to it and its ceilings must be the locked ones. Preregistration text is
    secret-free by construction, so a secret shape here is refused, never redacted.
    Returns ``{name: canonical sha256}`` for both files.
    """
    expected = canonical_sha256(expectations_document())
    if manifest.expectations_sha256 != expected:
        raise ValueError(
            f"manifest expectations_sha256 {manifest.expectations_sha256} != canonical "
            f"expectations document {expected}; refusing to seal"
        )
    _ceilings_match_locked(manifest.ceilings)
    documents = {
        PREREGISTRATION_FILE_NAMES[0]: pretty_json(manifest),
        PREREGISTRATION_FILE_NAMES[1]: expectations_json(),
    }
    _write_all(out_dir, documents, phase="preregistration")
    return {name: canonical_sha256(json.loads(text)) for name, text in documents.items()}


def existing_raw_artifacts(out_dir: Path) -> tuple[str, ...]:
    """The ``RAW_ARTIFACT_PATHS`` already present under ``out_dir``, in contract order.
    A non-empty result means the experiment identity is consumed."""
    return tuple(name for name in RAW_ARTIFACT_PATHS if (out_dir / name).exists())


# --------------------------------------------------------------------------- consumption


class ConsumptionRefused(RuntimeError):
    """The identity may not be consumed: a raw artifact already exists or the preflight
    did not pass. Nothing is written."""


def _require_commit_sha(label: str, sha: str) -> None:
    if not _TREE_SHA.fullmatch(sha):
        raise ValueError(f"{label} {sha!r} is not a 40-hex commit sha")


def write_consumption(
    out_dir: Path,
    *,
    gates: tuple[GateResult, ...],
    frozen_sha: str,
    harness_code_sha: str,
    leakage: LeakageResult,
    observed_grpc_dns_resolver: str | None,
    consumed_at: datetime,
) -> tuple[Path, Path]:
    """THE identity-consuming write (spec §10): ``preflight.json`` then, last,
    ``consumption.json``, each atomically (temp + rename).

    Refuses with ``ConsumptionRefused`` -- writing nothing -- when any of the 21 raw
    artifact paths exists under ``out_dir`` or when ``all_passed(gates)`` is false; a
    gate tuple that is not exactly ``GATE_NAMES`` in order, a malformed sha or a naive
    timestamp is a ``ValueError``. Gate details are diagnostic text and are redacted;
    the observed resolver is recorded verbatim; ``consumed_at`` is recorded as an ISO
    UTC timestamp. No key and no secret-shaped value can reach either file.
    Returns the two paths in write order.
    """
    present = existing_raw_artifacts(out_dir)
    if present:
        raise ConsumptionRefused(
            f"raw artifact(s) already exist under {out_dir}: {list(present)}; the experiment "
            "identity is consumed"
        )
    if not all_passed(gates):
        failed = [gate.name for gate in gates if not gate.passed]
        raise ConsumptionRefused(
            f"preflight did not pass ({len(gates)} gates, failed {failed}); refusing to consume"
        )
    names = tuple(gate.name for gate in gates)
    if names != GATE_NAMES:
        raise ValueError(f"gates {list(names)} are not exactly GATE_NAMES {list(GATE_NAMES)}")
    _require_commit_sha("frozen_sha", frozen_sha)
    _require_commit_sha("harness_code_sha", harness_code_sha)
    if consumed_at.tzinfo is None or consumed_at.utcoffset() is None:
        raise ValueError("consumed_at must be timezone-aware; a naive timestamp is refused")
    preflight_document = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "frozen_sha": frozen_sha,
        "harness_code_sha": harness_code_sha,
        "all_passed": True,
        "frontier_calls": 0,
        "gates": [
            gate.model_copy(update={"detail": redact_secrets(gate.detail)}).model_dump(mode="json")
            for gate in gates
        ],
        "leakage": leakage.model_dump(mode="json"),
        "observed_grpc_dns_resolver": observed_grpc_dns_resolver,
    }
    consumption_document = {
        "experiment_version": EXPERIMENT_VERSION,
        "frozen_sha": frozen_sha,
        "harness_code_sha": harness_code_sha,
        "policy_version": POLICY_VERSION_FROZEN,
        "prompt_sha256": PROMPT_SHA256_FROZEN,
        "provider": PROVIDER,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "grpc_dns_resolver": GRPC_DNS_RESOLVER_FROZEN,
        "consumed_at": consumed_at.astimezone(UTC).isoformat(),
    }
    documents = {
        "preflight.json": pretty_json(preflight_document),
        "consumption.json": pretty_json(consumption_document),
    }
    written = _write_all(out_dir, documents, phase="consumption")
    return out_dir / written[0], out_dir / written[1]


# --------------------------------------------------------------------------- raw write


def write_run_artifacts(
    out_dir: Path,
    run: RunResult,
    verdicts: tuple[IntegrityVerdict, ...],
    case_results: tuple[CaseResult, ...],
) -> tuple[str, ...]:
    """Write the other 19 raw paths (``RUN_ARTIFACT_PATHS``) at once, write-once.

    Refuses -- writing nothing -- with ``ValueError`` when ``consumption.json`` or
    ``preflight.json`` is absent (a raw tree can never exist without a consumption
    record), when ``verdicts`` is not exactly L1..L9 in order, when any request record
    is not bound one-to-one and in order to its reference snapshot on
    (arm ``"F"``, t, call_number, request_sha256), or when any exact
    ``rendered_user_request`` carries a secret shape; with ``FileExistsError`` when any
    of the 19 exists. Diagnostic text is redacted. Every ledger of every run status is
    written; a ``NOT_RUN`` ledger gets its eight structural files.
    """
    _require_verdict_ids(verdicts)
    missing = [name for name in CONSUMPTION_PATHS if not (out_dir / name).is_file()]
    if missing:
        raise ValueError(
            f"no consumption record under {out_dir}: {missing} missing; a raw tree can never "
            "exist without consumption.json and preflight.json"
        )
    _require_bound_requests(run)
    _require_secret_free_requests(run)
    return _write_all(out_dir, _run_documents(run, verdicts, case_results), phase="raw run")


# --------------------------------------------------------------------------- checks


def _require_verdict_ids(verdicts: tuple[IntegrityVerdict, ...]) -> None:
    ids = tuple(verdict.id for verdict in verdicts)
    if ids != VERDICT_IDS:
        raise ValueError(
            f"integrity verdicts must be exactly {list(VERDICT_IDS)} in order; got {list(ids)}"
        )


def _identity(item: RequestRecord | RequestReferenceSnapshot) -> tuple[str, int, int, str]:
    return (item.arm, item.t, item.call_number, item.request_sha256)


def _require_bound(
    label: str,
    requests: tuple[RequestRecord, ...],
    snapshots: tuple[RequestReferenceSnapshot, ...],
) -> None:
    if len(requests) != len(snapshots):
        raise ValueError(
            f"{label}: {len(requests)} request records but {len(snapshots)} reference "
            "snapshots; every record must be bound to exactly one snapshot"
        )
    for index, (record, snapshot) in enumerate(zip(requests, snapshots, strict=True)):
        if record.arm != _ARM:
            raise ValueError(
                f"{label}: request record {index} carries arm {record.arm!r}; the locus "
                f"policy records arm {_ARM!r} only"
            )
        if _identity(record) != _identity(snapshot):
            raise ValueError(
                f"{label}: request record {index} {_identity(record)} is not the identity of "
                f"its reference snapshot {_identity(snapshot)}"
            )


def _require_bound_requests(run: RunResult) -> None:
    for record in run.ledgers:
        for delta in record.deltas:
            _require_bound(_delta_label(record, delta), delta.requests, delta.reference_snapshots)


def _all_request_records(run: RunResult) -> Iterable[tuple[LedgerRecord, RequestRecord]]:
    for record in run.ledgers:
        for delta in record.deltas:
            for request in delta.requests:
                yield record, request


def _require_secret_free_requests(run: RunResult) -> None:
    for record, request in _all_request_records(run):
        if contains_secret_shape(request.rendered_user_request):
            raise ValueError(
                f"secret-shaped token inside rendered_user_request ({record.ledger} "
                f"T{request.t} call {request.call_number}); refusing to write raw artifacts"
            )


# --------------------------------------------------------------------------- documents


def _delta_label(record: LedgerRecord, delta: DeltaRecord) -> str:
    return f"{record.ledger} T{delta.t}"


def _redacted(text: str | None) -> str | None:
    return None if text is None else redact_secrets(text)


def _base(record: LedgerRecord) -> dict[str, Any]:
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "ledger": record.ledger,
        "project_id": record.project_id,
    }


def _entries(delta: DeltaRecord) -> list[dict[str, Any]]:
    """The paired ``{"record", "reference_snapshot"}`` entries of one delta, in order."""
    return [
        {
            "record": record.model_dump(mode="json"),
            "reference_snapshot": snapshot.model_dump(mode="json"),
        }
        for record, snapshot in zip(delta.requests, delta.reference_snapshots, strict=True)
    ]


def _cost_text(cost: object) -> str:
    try:
        return str(Decimal(str(cost)))
    except InvalidOperation as exc:
        raise ValueError(f"receipt cost_usd {cost!r} is not a decimal") from exc


def _receipt_costs(receipts: Iterable[Any]) -> Decimal:
    """The sum of ``cost_usd`` over the receipts that carry one; never the budget tally."""
    total = Decimal("0")
    for receipt in receipts:
        cost = getattr(receipt, "cost_usd", None)
        if cost is not None:
            total += Decimal(_cost_text(cost))
    return total


def _measurement_row(record: LedgerRecord, request: RequestRecord, receipt: Any) -> dict[str, Any]:
    """One row per ``RequestRecord``: structural facts from the record, economics from
    the receipt at the same call index (``None`` when no receipt was recorded or the
    receipt lacks the field; never coerced, never taken from the budget tally)."""
    cost = getattr(receipt, "cost_usd", None)
    return {
        "ledger": record.ledger,
        "t": request.t,
        "call_number": request.call_number,
        "request_sha256": request.request_sha256,
        "rendered_request_chars": len(request.rendered_user_request),
        "receipt_recorded": receipt is not None,
        "input_tokens": getattr(receipt, "input_tokens", None),
        "output_tokens": getattr(receipt, "output_tokens", None),
        "provider_cost_usd": None if cost is None else _cost_text(cost),
        "wall_clock_ms": getattr(receipt, "wall_clock_ms", None),
    }


def _measurements_document(run: RunResult) -> dict[str, Any]:
    """Rows in ledger, delta, call order. Receipts are appended in call order and a
    raised call leaves no record, so ``receipts[i]`` belongs to ``requests[i]``; a
    receipt beyond the records (an answered-but-refused call) pairs with nothing."""
    rows: list[dict[str, Any]] = []
    for record in run.ledgers:
        for delta in record.deltas:
            for index, request in enumerate(delta.requests):
                receipt = delta.receipts[index] if index < len(delta.receipts) else None
                rows.append(_measurement_row(record, request, receipt))
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "run_status": run.status.value,
        "row_count": len(rows),
        "rows": rows,
    }


def _state_document(record: LedgerRecord, t: int) -> dict[str, Any]:
    """``state_T<t>.json``: the ledger state and derived view after delta ``t``;
    ``present`` false with nulls for a ``NOT_RUN`` ledger, an unreached delta or a delta
    whose state could not be captured."""
    delta = next((d for d in record.deltas if d.t == t), None)
    state = None if delta is None else delta.state_snapshot
    view = None if delta is None else delta.view_snapshot
    present = state is not None and view is not None
    return {
        "ledger": record.ledger,
        "t": t,
        "present": present,
        "state": state.model_dump(mode="json") if present and state is not None else None,
        "view": view.model_dump(mode="json") if present and view is not None else None,
    }


def _ledger_documents(run: RunResult, record: LedgerRecord) -> dict[str, str]:
    prefix = f"L-{record.ledger}"
    requests = {**_base(record), "entries": [e for d in record.deltas for e in _entries(d)]}
    drafts = {
        **_base(record),
        "deltas": [
            {
                "t": delta.t,
                "payloads": [
                    {"index": index, "payload": payload}
                    for index, payload in enumerate(delta.draft_payloads)
                ],
            }
            for delta in record.deltas
        ],
    }
    receipts = {
        **_base(record),
        "deltas": [
            {
                "t": delta.t,
                "receipts": [
                    {"index": index, "receipt": receipt}
                    for index, receipt in enumerate(delta.receipts)
                ],
            }
            for delta in record.deltas
        ],
    }
    decisions = {
        **_base(record),
        "deltas": [
            {
                "t": delta.t,
                "completed": delta.stage_decisions != ((), ()),
                "stage_decisions": [
                    [d.model_dump(mode="json") for d in stage] for stage in delta.stage_decisions
                ],
                "pending_supersede_judgment_ids": list(delta.pending_supersede_judgment_ids),
            }
            for delta in record.deltas
        ],
    }
    ledger = {
        **_base(record),
        "event_count": len(record.ledger_events),
        "events": [stored.model_dump(mode="json") for stored in record.ledger_events],
    }
    result = {
        **_base(record),
        "scope": record.scope,
        "status": record.status,
        "error": _redacted(record.error),
        "run_status": run.status.value,
        "delta_count": len(record.deltas),
        "deltas": [
            {
                "t": delta.t,
                "completed": delta.stage_decisions != ((), ()),
                "request_count": len(delta.requests),
                "reference_snapshot_count": len(delta.reference_snapshots),
                "receipt_count": len(delta.receipts),
                "draft_payload_count": len(delta.draft_payloads),
                "state_present": delta.state_snapshot is not None,
            }
            for delta in record.deltas
        ],
        "request_count": sum(len(d.requests) for d in record.deltas),
        "reference_snapshot_count": sum(len(d.reference_snapshots) for d in record.deltas),
        "receipt_count": sum(len(d.receipts) for d in record.deltas),
        "ledger_event_count": len(record.ledger_events),
        "provider_cost_usd": str(_receipt_costs(r for d in record.deltas for r in d.receipts)),
        "final_state_present": record.final_state is not None,
        "final_view_present": record.final_view is not None,
        "replay": None if record.replay is None else record.replay.model_dump(mode="json"),
    }
    return {
        f"{prefix}/requests.json": pretty_json(requests),
        f"{prefix}/drafts.json": pretty_json(drafts),
        f"{prefix}/receipts.json": pretty_json(receipts),
        f"{prefix}/decisions.json": pretty_json(decisions),
        f"{prefix}/ledger.json": pretty_json(ledger),
        **{f"{prefix}/state_T{t}.json": pretty_json(_state_document(record, t)) for t in DELTAS},
        f"{prefix}/result.json": pretty_json(result),
    }


def _run_documents(
    run: RunResult,
    verdicts: tuple[IntegrityVerdict, ...],
    case_results: tuple[CaseResult, ...],
) -> dict[str, str]:
    documents: dict[str, str] = {}
    if tuple(record.ledger for record in run.ledgers) != LEDGERS:
        raise ValueError(
            f"run ledgers {[r.ledger for r in run.ledgers]} are not {list(LEDGERS)} in order"
        )
    for record in run.ledgers:
        documents.update(_ledger_documents(run, record))
    documents["measurements.json"] = pretty_json(_measurements_document(run))
    documents["verdicts.json"] = pretty_json(verdicts_document(run, verdicts, case_results))
    documents["report.md"] = render_report(run, verdicts, case_results)
    ordered = {name: documents[name] for name in RUN_ARTIFACT_PATHS if name in documents}
    if set(ordered) != set(RUN_ARTIFACT_PATHS) or len(ordered) != len(documents):
        raise RuntimeError("run documents do not cover the raw artifact tree exactly")
    return ordered


# --------------------------------------------------------------------------- verdicts (raw)


def _rule_zero_facts(status: str, integrity_passed: Mapping[str, bool | None]) -> list[str]:
    """Why spec §14 rule 0 holds from deterministic facts alone; empty when it does not."""
    facts: list[str] = []
    if status != RunStatus.COMPLETED.value:
        facts.append(f"run status {status}")
    failed = [
        verdict_id
        for verdict_id in _RULE_ZERO_VERDICT_IDS
        if integrity_passed.get(verdict_id) is not True
    ]
    if failed:
        facts.append(f"verdict(s) {failed} did not pass")
    return facts


def verdicts_document(
    run: RunResult,
    verdicts: tuple[IntegrityVerdict, ...],
    case_results: tuple[CaseResult, ...],
) -> dict[str, Any]:
    """Raw ``verdicts.json`` data: the operational status and budget, the L1-L9
    deterministic verdicts (``passed``, redacted ``detail``, static ``applies_to`` and
    the observed ``failed_ledgers`` attribution, ``[]`` on pass), the §7.1 case
    assertion results (details redacted), and every architect field ``null``. The
    outcome is ``null`` unless rule 0 already holds from these facts, in which case it
    is recorded as inconclusive while ``case_outcomes`` stay ``null``."""
    _require_verdict_ids(verdicts)
    facts = _rule_zero_facts(run.status.value, {v.id: v.passed for v in verdicts})
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "phase": _RAW_PHASE,
        "status": run.status.value,
        "error": _redacted(run.error),
        "budget": run.budget.model_dump(mode="json"),
        "integrity": {
            verdict.id: {
                "passed": verdict.passed,
                "detail": redact_secrets(verdict.detail),
                "applies_to": list(verdict.applies_to),
                "failed_ledgers": list(verdict.failed_ledgers),
            }
            for verdict in verdicts
        },
        "case_assertions": [
            result.model_copy(update={"detail": redact_secrets(result.detail)}).model_dump(
                mode="json"
            )
            for result in case_results
        ],
        "semantic_assertions": None,
        "semantic_notes": None,
        "case_outcomes": None,
        _OUTCOME_KEY: _INCONCLUSIVE if facts else None,
    }


# --------------------------------------------------------------------------- report


def _md(value: object) -> str:
    text = "null" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _tri(value: bool | None) -> str:
    return "null" if value is None else str(value).lower()


def render_report(
    run: RunResult,
    verdicts: tuple[IntegrityVerdict, ...],
    case_results: tuple[CaseResult, ...],
) -> str:
    """The deterministic raw report, from the run, the verdicts and the case results
    only. Carries ``ADJUDICATION_PENDING_LINE`` unless rule 0 already holds."""
    _require_verdict_ids(verdicts)
    facts = _rule_zero_facts(run.status.value, {v.id: v.passed for v in verdicts})
    lines: list[str] = [
        "# Locus-policy live validation -- raw run report",
        "",
        f"- experiment_version: {EXPERIMENT_VERSION}",
        f"- artifact_format_version: {ARTIFACT_FORMAT_VERSION}",
        f"- policy_version: {POLICY_VERSION_FROZEN}",
        f"- prompt_sha256: {PROMPT_SHA256_FROZEN}",
        f"- status: {run.status.value}",
        f"- error: {_md(_redacted(run.error))}",
        "",
        "## Ledgers",
        "",
        "| ledger | project_id | scope | status | deltas | requests | receipts | error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in run.ledgers:
        lines.append(
            f"| {record.ledger} | {record.project_id} | {record.scope} | {record.status} "
            f"| {len(record.deltas)} | {sum(len(d.requests) for d in record.deltas)} "
            f"| {sum(len(d.receipts) for d in record.deltas)} | {_md(_redacted(record.error))} |"
        )
    budget = run.budget
    lines += [
        "",
        "## Budget",
        "",
        f"- frontier_calls: {budget.frontier_calls}",
        f"- judge_calls: {budget.judge_calls}",
        f"- human_authorizations: {budget.human_authorizations}",
        f"- provider_cost_usd: {budget.provider_cost_usd}",
        "",
        "## Deterministic integrity verdicts (L1-L9)",
        "",
        "| id | passed | applies_to | failed_ledgers | detail |",
        "|---|---|---|---|---|",
    ]
    for verdict in verdicts:
        lines.append(
            f"| {verdict.id} | {_tri(verdict.passed)} | {','.join(verdict.applies_to)} "
            f"| {','.join(verdict.failed_ledgers) or '-'} "
            f"| {_md(redact_secrets(verdict.detail))} |"
        )
    lines += [
        "",
        "## Case assertions (spec 7.1, deterministic)",
        "",
        "| ledger | case_id | structural_passed | tags | detail |",
        "|---|---|---|---|---|",
    ]
    for result in case_results:
        lines.append(
            f"| {result.ledger} | {result.case_id} | {_tri(result.structural_passed)} "
            f"| {','.join(result.tags) or '-'} | {_md(redact_secrets(result.detail))} |"
        )
    lines += [
        "",
        "## Outcome",
        "",
        "The semantic assertions, notes, case outcomes and the outcome of the experiment",
        "are `null` in `verdicts.json`; they are architect adjudication after the raw-run",
        "commit (spec 11, 14).",
        "",
    ]
    if facts:
        lines.append(
            f"{_OUTCOME_LINE_PREFIX}{_INCONCLUSIVE} (rule 0 holds from deterministic facts: "
            f"{'; '.join(facts)}; case_outcomes null; architect adjudication pending)"
        )
    else:
        lines.append(ADJUDICATION_PENDING_LINE)
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- adjudication


class AdjudicationRefused(RuntimeError):
    """The raw tree is not the committed, clean, byte-identical, un-adjudicated
    evidence the architect adjudicated, or a provider key is present; nothing is
    written."""


class Adjudication(FrozenModel):
    """The architect's binary answers to the spec §7.2 semantic assertions, per ledger,
    after the raw freeze (spec §11, §14).

    ``semantic_answers`` must carry exactly both ledgers, each answering exactly
    ``SEMANTIC_ASSERTION_IDS`` (V04 has no semantic assertion; an answer for it, or for
    any unknown id, is refused). Answers are strict booleans. This module never infers
    or defaults an answer.
    """

    semantic_answers: dict[Ledger, dict[str, StrictBool]]
    notes: str

    @model_validator(mode="after")
    def _check_shape(self) -> Adjudication:
        missing_ledgers = [ledger for ledger in LEDGERS if ledger not in self.semantic_answers]
        if missing_ledgers:
            raise ValueError(
                f"semantic_answers lacks ledger(s) {missing_ledgers}; both {list(LEDGERS)} are "
                "required"
            )
        for ledger, answers in self.semantic_answers.items():
            unknown = sorted(set(answers) - set(SEMANTIC_ASSERTION_IDS))
            if unknown:
                raise ValueError(
                    f"semantic_answers[{ledger!r}] answers unknown assertion(s) {unknown}; only "
                    f"{list(SEMANTIC_ASSERTION_IDS)} exist"
                )
            missing = [id_ for id_ in SEMANTIC_ASSERTION_IDS if id_ not in answers]
            if missing:
                raise ValueError(f"semantic_answers[{ledger!r}] lacks answer(s) for {missing}")
        return self


def _repo_relative(out_dir: Path, repo_root: Path) -> str:
    try:
        relative = out_dir.resolve().relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"out_dir {out_dir} is not inside repo_root {repo_root}; the repo-relative "
            "path of every raw artifact must be derivable"
        ) from exc
    return relative.as_posix()


def _committed_raw_tree(
    out_dir: Path, *, relative: str, raw_run_commit_sha: str, git: GitCliLike
) -> dict[str, bytes]:
    """Every raw path must exist on disk and equal the bytes ``raw_run_commit_sha``
    holds for it; refuse on the first miss."""
    committed: dict[str, bytes] = {}
    for name in RAW_ARTIFACT_PATHS:
        path = out_dir / name
        if not path.is_file():
            raise AdjudicationRefused(f"raw artifact {name} is missing under {out_dir}")
        repo_path = f"{relative}/{name}" if relative not in ("", ".") else name
        try:
            shown = git.show_bytes(raw_run_commit_sha, repo_path)
        except Exception as exc:
            raise AdjudicationRefused(
                f"raw artifact {name} cannot be read at {raw_run_commit_sha} "
                f"({repo_path}): {type(exc).__name__}: {exc}"
            ) from exc
        if path.read_bytes() != shown:
            raise AdjudicationRefused(
                f"raw artifact {name} on disk differs from the bytes committed at "
                f"{raw_run_commit_sha}"
            )
        committed[name] = shown
    return committed


def _require_boolean_verdicts(integrity: Mapping[str, Any]) -> None:
    """Every committed integrity entry must carry a boolean ``passed``: a ``null``,
    missing or non-bool value is not a verdict rule 0 may read, so the adjudication is
    refused before any outcome is derived and nothing is written."""
    for verdict_id in VERDICT_IDS:
        entry = integrity.get(verdict_id)
        passed = entry.get("passed") if isinstance(entry, Mapping) else None
        if not isinstance(passed, bool):
            raise AdjudicationRefused(
                f"committed verdicts.json integrity[{verdict_id!r}].passed is {passed!r}, not "
                "a boolean; a verdict that was not evaluated cannot feed rule 0 (spec §14); "
                "refusing to adjudicate"
            )


def _committed_structural(
    case_assertions: object,
) -> dict[tuple[str, str], tuple[bool | None, list[str]]]:
    """``(ledger, case_id) -> (structural_passed, tags)`` from the committed
    ``case_assertions``; refuse unless the twelve cases are covered exactly once."""
    if not isinstance(case_assertions, list):
        raise AdjudicationRefused("committed verdicts.json carries no case_assertions list")
    expected = [(ledger, case_id) for ledger in LEDGERS for case_id in CASE_IDS]
    structural: dict[tuple[str, str], tuple[bool | None, list[str]]] = {}
    seen: list[tuple[str, str]] = []
    for entry in case_assertions:
        if not isinstance(entry, Mapping):
            raise AdjudicationRefused("committed case_assertions carries a non-object entry")
        key = (str(entry.get("ledger")), str(entry.get("case_id")))
        passed = entry.get("structural_passed")
        if passed is not None and not isinstance(passed, bool):
            raise AdjudicationRefused(
                f"committed case assertion {key} structural_passed is {passed!r}, not a boolean "
                "or null"
            )
        tags = entry.get("tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise AdjudicationRefused(f"committed case assertion {key} carries no tag list")
        seen.append(key)
        structural[key] = (passed, list(tags))
    if seen != expected:
        missing = [key for key in expected if key not in seen]
        extra = [key for key in seen if key not in expected]
        raise AdjudicationRefused(
            "committed case_assertions do not cover the case table exactly once in order; "
            f"missing={missing} extra={extra}; refusing to adjudicate"
        )
    return structural


def _adjudicated_report(
    raw_report: str,
    *,
    raw_run_commit_sha: str,
    rule_zero: bool,
    outcome: str,
    adjudication: Adjudication,
    case_outcomes: list[dict[str, Any]],
) -> str:
    lines = raw_report.split("\n")
    outcome_lines = [i for i, line in enumerate(lines) if line.startswith(_OUTCOME_LINE_PREFIX)]
    if len(outcome_lines) != 1:
        raise AdjudicationRefused(
            "committed report.md does not carry exactly one outcome line; the raw tree is "
            "not un-adjudicated raw evidence"
        )
    lines[outcome_lines[0]] = (
        f"{_OUTCOME_LINE_PREFIX}{outcome} (architect adjudication over raw-run commit "
        f"{raw_run_commit_sha})"
    )
    ledgers = list(LEDGERS)
    lines += [
        "## Adjudication",
        "",
        f"- raw_run_commit_sha: {raw_run_commit_sha}",
        f"- rule_zero: {_tri(rule_zero)}",
        f"- decision: {outcome}",
        "",
        "### Semantic assertions (spec 7.2)",
        "",
        "| assertion | " + " | ".join(ledgers) + " |",
        "|---|" + "---|" * len(ledgers),
    ]
    for assertion_id in SEMANTIC_ASSERTION_IDS:
        cells = " | ".join(
            _tri(adjudication.semantic_answers[ledger][assertion_id]) for ledger in LEDGERS
        )
        lines.append(f"| {assertion_id} | {cells} |")
    lines += [
        "",
        "### Case outcomes (spec 14)",
        "",
        "| ledger | case_id | structural_passed | semantic_answer | passed | tags |",
        "|---|---|---|---|---|---|",
    ]
    for entry in case_outcomes:
        lines.append(
            f"| {entry['ledger']} | {entry['case_id']} | {_tri(entry['structural_passed'])} "
            f"| {_tri(entry['semantic_answer'])} | {_tri(entry['passed'])} "
            f"| {','.join(entry['tags']) or '-'} |"
        )
    failing = [entry for entry in case_outcomes if entry["passed"] is False]
    lines += ["", "### Failing cases", ""]
    if not failing:
        lines.append("- none")
    for entry in failing:
        lines.append(
            f"- {entry['ledger']} {entry['case_id']}: tags {entry['tags']}; "
            f"{entry['semantic_assertion_id'] or 'no semantic assertion'} answered "
            f"{_tri(entry['semantic_answer'])}"
        )
    lines += ["", "### Notes", "", _md(redact_secrets(adjudication.notes)), ""]
    return "\n".join(lines)


def write_adjudication(
    out_dir: Path,
    *,
    raw_run_commit_sha: str,
    git: GitCliLike,
    adjudication: Adjudication,
    repo_root: Path,
    env: Mapping[str, str],
) -> tuple[str, ...]:
    """Record the architect's adjudication over a committed raw tree; the ONLY place
    ``expectations.experiment_outcome`` runs.

    Refuses with ``AdjudicationRefused`` -- writing nothing -- unless: ``XAI_API_KEY``
    is absent from ``env`` (presence only; the value is never read); ``git.head()`` is
    ``raw_run_commit_sha``; ``git.dirty()`` is empty; every one of the 21 raw files
    exists and equals ``git.show_bytes(raw_run_commit_sha, "<out_dir relative to
    repo_root>/<path>")``; the committed ``verdicts.json`` is still phase ``raw``
    (write-once); every committed L1-L9 ``passed`` is a boolean; and the committed
    ``case_assertions`` cover the twelve cases exactly. ``out_dir`` must be inside
    ``repo_root`` (``ValueError``).

    Then, from the committed facts and the architect's answers only: rule 0 holds iff
    the raw status is not ``COMPLETED`` or any of L1-L8 did not pass; each case passes
    by ``CASE_OUTCOME_RULES`` (structural holds and, where one exists, the semantic
    answer is yes) and is ``null`` where its structural result is ``null`` (only
    possible under rule 0, which is then already decisive); the experiment outcome is
    ``expectations.experiment_outcome``. Exactly ``verdicts.json`` (every raw entry kept
    semantically identical; ``phase`` ``adjudicated``; the null fields filled) and
    ``report.md`` are rewritten, and the other 19 files are proven byte-identical
    afterwards.
    """
    if _PROVIDER_KEY_ENV in env:
        raise AdjudicationRefused(
            f"{_PROVIDER_KEY_ENV} is present in the adjudication environment (presence-only "
            "check; its value was never read); adjudication runs with no provider key"
        )
    relative = _repo_relative(out_dir, repo_root)
    head = git.head()
    if head != raw_run_commit_sha:
        raise AdjudicationRefused(
            f"HEAD {head!r} != raw-run commit {raw_run_commit_sha!r}; adjudication is "
            "recorded only over the committed raw evidence"
        )
    dirty = git.dirty()
    if dirty.strip():
        raise AdjudicationRefused(f"worktree dirty; refusing to adjudicate:\n{dirty.strip()}")
    committed = _committed_raw_tree(
        out_dir, relative=relative, raw_run_commit_sha=raw_run_commit_sha, git=git
    )
    raw = json.loads(committed["verdicts.json"].decode("utf-8"))
    if not isinstance(raw, dict):
        raise AdjudicationRefused("committed verdicts.json is not an object")
    if (
        raw.get("phase") != _RAW_PHASE
        or raw.get("semantic_assertions") is not None
        or raw.get("case_outcomes") is not None
    ):
        raise AdjudicationRefused(
            f"committed verdicts.json is already adjudicated (phase {raw.get('phase')!r}); "
            "adjudication is write-once"
        )
    integrity = raw.get("integrity") or {}
    _require_boolean_verdicts(integrity)
    structural = _committed_structural(raw.get("case_assertions"))
    status = str(raw.get("status"))
    rule_zero = bool(_rule_zero_facts(status, {v: integrity[v]["passed"] for v in VERDICT_IDS}))
    uncomputable = [key for key, (passed, _) in structural.items() if passed is None]
    if uncomputable and not rule_zero:
        raise AdjudicationRefused(
            f"committed case assertions {uncomputable} were not evaluated although the run "
            "completed and every rule-0 verdict passed; refusing to adjudicate inconsistent "
            "evidence"
        )

    case_outcomes: list[dict[str, Any]] = []
    case_passes: dict[tuple[Ledger, str], bool] = {}
    for ledger in LEDGERS:
        for case_id in CASE_IDS:
            rule = CASE_OUTCOME_RULES[case_id]
            answer = (
                None
                if rule.semantic_assertion_id is None
                else adjudication.semantic_answers[ledger][rule.semantic_assertion_id]
            )
            structural_passed, tags = structural[(ledger, case_id)]
            passed = (
                None
                if structural_passed is None
                else rule.case_passes(structural=structural_passed, semantic=answer)
            )
            case_outcomes.append(
                {
                    "ledger": ledger,
                    "case_id": case_id,
                    "structural_passed": structural_passed,
                    "semantic_assertion_id": rule.semantic_assertion_id,
                    "semantic_answer": answer,
                    "passed": passed,
                    "tags": tags,
                }
            )
            # A null case is only reachable under rule 0, which outranks aggregation.
            case_passes[(ledger, case_id)] = passed is True
    outcome = experiment_outcome(rule_zero=rule_zero, case_passes=case_passes)

    document: dict[str, Any] = {
        **raw,
        "phase": _ADJUDICATED_PHASE,
        "raw_run_commit_sha": raw_run_commit_sha,
        "rule_zero": rule_zero,
        "semantic_assertions": {
            ledger: dict(adjudication.semantic_answers[ledger]) for ledger in LEDGERS
        },
        "semantic_notes": redact_secrets(adjudication.notes),
        "case_outcomes": case_outcomes,
        _OUTCOME_KEY: outcome,
    }
    documents = {
        "verdicts.json": pretty_json(document),
        "report.md": _adjudicated_report(
            committed["report.md"].decode("utf-8"),
            raw_run_commit_sha=raw_run_commit_sha,
            rule_zero=rule_zero,
            outcome=outcome,
            adjudication=adjudication,
            case_outcomes=case_outcomes,
        ),
    }
    _refuse_secret_shapes(documents, phase="adjudication")
    preserved = {
        name: hashlib.sha256(committed[name]).hexdigest()
        for name in RAW_ARTIFACT_PATHS
        if name not in documents
    }
    for name, text in documents.items():
        _write_atomic(out_dir / name, text)
    changed = [
        name
        for name, digest in preserved.items()
        if hashlib.sha256((out_dir / name).read_bytes()).hexdigest() != digest
    ]
    if changed:
        raise AdjudicationRefused(
            f"raw artifact(s) {changed} changed during adjudication; only verdicts.json and "
            "report.md may change"
        )
    return tuple(documents)

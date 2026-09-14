"""Sealed preregistration, the write-once raw evidence tree and the post-commit architect
adjudication writer for the 9P3 long-horizon bounded-memory experiment (spec §12, §14,
§16, §17, §19; T6 brief; clarifications 1-9).

Three artifact families live under the experiment directory:

* **preregistration** (``PREREGISTRATION_FILE_NAMES``): ``manifest.json`` -- the typed
  ``ExperimentManifest`` sealing the frozen identity (core SHA, predecessor raw-evidence
  SHA, pre-seal harness HEAD, spec SHA, provider/model/effort, every policy version and
  prompt hash, the output-schema hash, arm schedule, the six ceilings, the 192 evidence
  records and their corpus hash, the typed needle-set hash, the canonical
  ``expectations_sha256``, the economy/growth/difference rule literals, the measurement
  windows, the decision names and the historical-preservation baseline) -- and
  ``expectations.json`` -- exactly ``expectations_document()``, pretty-printed. No
  self-referential seal SHA is embedded: the seal commit is identified by
  ``FINAL_SEAL_RULE`` and checked by ``integrity`` gate 1 at run time.
* **raw live artifacts** (``RAW_ARTIFACT_PATHS``, 116 paths): ``preflight.json``,
  ``measurements.json``, ``verdicts.json``, ``report.md``, eight files per persistent arm
  (F and A each aggregate their sixteen cells) and six files per R cell (``R/T01`` ..
  ``R/T16``). Written once and never overwritten; every schedule position is written,
  including ``FAILED`` and ``NOT_RUN`` cells, so a cell is never silently omitted.
* **adjudication**: ``write_adjudication`` rewrites exactly ``verdicts.json`` and
  ``report.md`` -- and only after proving that HEAD is the raw-run commit, the worktree
  is clean and every one of the 116 raw files is byte-identical to what that commit
  holds.

Two phases, hard boundary (clarification 2). The raw phase (``write_preflight``,
``write_run_artifacts``) is machine-produced and carries NO semantic architecture
decision: ``verdicts.json`` holds the I1-I15 ``IntegrityVerdict`` dumps and
``semantic_checkpoints``, ``material_errors``, ``control_errors``, ``errors_total`` and
``architecture_selection`` are all ``null``; ``report.md`` carries the literal
``ADJUDICATION_PENDING_LINE``. ``select_architecture`` is referenced by
``write_adjudication`` alone; the live runner path never reaches it.

Sealing. ``canonical_bytes`` / ``canonical_sha256`` / ``pretty_json`` are the frozen 9P2
functions, imported: seal hashes are always taken over parsed data, never pretty bytes.

Secret hygiene. No API key or auth value is accepted by any function here. A secret shape
inside any exact ``rendered_user_request`` (a scientific request string) refuses the whole
write -- scientific material is never redacted. ``redact_secrets`` is applied ONLY to
diagnostic text (cell errors, the run error, verdict details, gate details, adjudication
notes). As a last fail-closed guard, a document that still carries a secret shape after
that is refused, never written.

Law of this module: it records structural facts and decides nothing about meaning. It
may import ``expectations`` because it never enters the provider request path; it
constructs no reasoner, makes no network call, never runs git itself (``GitCliLike`` is
injected) and never writes outside ``out_dir``. It names no historical experiment
directory except through the frozen ``integrity`` constants and never touches one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from pydantic import Field, model_validator

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
from foundry.domain.common import FrozenModel
from foundry.domain.events import StoredEvent
from foundry.experiments.contrastive_unseen.artifacts import (
    canonical_bytes,
    canonical_sha256,
    pretty_json,
)
from foundry.experiments.contrastive_unseen.records import RequestRecord
from foundry.experiments.long_horizon_bounded.expectations import (
    CHECKPOINTS,
    DECISION_NAMES,
    SelectionInputs,
    SelectionOutcome,
    expectations_document,
    select_architecture,
)
from foundry.experiments.long_horizon_bounded.integrity import (
    A_POLICY_VERSION_FROZEN,
    A_PROMPT_SHA256_FROZEN,
    CEILING_KEYS,
    EXPERIMENT_ARTIFACT_DIR,
    FR_POLICY_VERSION_FROZEN,
    FR_PROMPT_SHA256_FROZEN,
    HISTORICAL_ARTIFACT_DIRS,
    HISTORICAL_PRESERVATION_BASE_SHA,
    LOCKED_CEILINGS,
    OUTPUT_SCHEMA_SHA256_FROZEN,
    PREDECESSOR_ARTIFACT_DIR,
    REQUIRED_MANIFEST_KEYS,
    VERDICT_IDS,
    GateResult,
    GitCliLike,
    IntegrityVerdict,
    all_passed,
)
from foundry.experiments.long_horizon_bounded.leakage import LeakageResult, needle_set_sha256
from foundry.experiments.long_horizon_bounded.measurements import (
    CallMeasurement,
    MeasurementMismatch,
    TokenSummary,
    summarize,
)
from foundry.experiments.long_horizon_bounded.protocol import (
    A_POLICY_VERSION,
    A_PROMPT_SHA256,
    ARM_SCHEDULE,
    EARLY_WINDOW,
    FR_POLICY_VERSION,
    FR_PROMPT_SHA256,
    FROZEN_CORE_SHA,
    GRPC_DNS_RESOLVER_FROZEN,
    LATE_WINDOW,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    MAX_SAME_CELL_RERUNS,
    MAX_SEMANTIC_RETRIES,
    MODEL,
    OUTPUT_SCHEMA_SHA256,
    PREDECESSOR_RAW_EVIDENCE_SHA,
    PROVIDER,
    REASONING_EFFORT,
    Arm,
)
from foundry.experiments.long_horizon_bounded.runner import (
    ArmSummary,
    CellRecord,
    RequestReferenceSnapshot,
    RunResult,
    RunStatus,
)
from foundry.experiments.long_horizon_bounded.timeline import (
    EXPERIMENT_VERSION,
    PROJECT_ID,
    SCOPE,
    VERSION_COUNT,
    EvidenceRecord,
    corpus_sha256,
    evidence_records,
)
from foundry.experiments.longitudinal.artifacts import contains_secret_shape, redact_secrets

__all__ = [
    "ADJUDICATION_PENDING_LINE",
    "ARTIFACT_FORMAT_VERSION",
    "BOUNDED_GROWTH_RULE",
    "ECONOMY_RULE",
    "EXPERIMENT_ARTIFACT_DIR",
    "EXPERIMENT_WIDE_VERDICT_IDS",
    "FINAL_SEAL_RULE",
    "PREREGISTRATION_FILE_NAMES",
    "RAW_ARTIFACT_PATHS",
    "R_GROWTH_RULE",
    "SPEC_PATH",
    "TOKEN_DIFF_RULE",
    "Adjudication",
    "AdjudicationRefused",
    "Ceilings",
    "ExperimentManifest",
    "build_manifest",
    "canonical_bytes",
    "canonical_sha256",
    "existing_raw_artifacts",
    "expectations_json",
    "manifest_sha256",
    "pretty_json",
    "render_report",
    "verdicts_document",
    "write_adjudication",
    "write_preflight",
    "write_preregistration",
    "write_run_artifacts",
]

# --------------------------------------------------------------------------- literals

ARTIFACT_FORMAT_VERSION: Final = 1
SPEC_PATH: Final = "docs/superpowers/specs/2026-09-13-9p3-long-horizon-bounded-memory-design.md"
FINAL_SEAL_RULE: Final = (
    "live HEAD must equal --frozen-sha; its single parent must equal harness_code_sha; "
    "parent..HEAD may add only manifest.json and expectations.json"
)
ECONOMY_RULE: Final = "4*X_TOTAL <= 3*R_TOTAL for X in {F, A}, T2..T16 input tokens"
BOUNDED_GROWTH_RULE: Final = "X_LATE_MEAN <= 27/20 * X_EARLY_MEAN"
R_GROWTH_RULE: Final = "R_LATE_MEAN >= 3/2 * R_EARLY_MEAN"
TOKEN_DIFF_RULE: Final = "abs(F_TOTAL-A_TOTAL)/min(F_TOTAL,A_TOTAL) >= 1/20 is meaningful"
PREREGISTRATION_FILE_NAMES: Final[tuple[str, ...]] = ("manifest.json", "expectations.json")
ADJUDICATION_PENDING_LINE: Final = "architecture_selection = null (architect adjudication pending)"
EXPERIMENT_WIDE_VERDICT_IDS: Final[tuple[str, ...]] = ("I2", "I3", "I12", "I13", "I14")
"""Spec §16.2 rule 0: the integrity failures that invalidate the experiment as a whole
(invalid call counts, retry/fallback/judge, reconciliation, offline compilation,
leakage) rather than one arm's semantic behaviour."""

_ARM_FILES: Final[tuple[str, ...]] = (
    "requests",
    "drafts",
    "receipts",
    "decisions",
    "eligible_targets",
    "authorizations",
    "ledger",
    "result",
)
_R_FILES: Final[tuple[str, ...]] = (
    "requests",
    "drafts",
    "receipts",
    "decisions",
    "ledger",
    "result",
)
_VERSIONS: Final[tuple[int, ...]] = tuple(range(1, VERSION_COUNT + 1))
_PERSISTENT_ARMS: Final[tuple[Arm, ...]] = ("F", "A")
_ALL_ARMS: Final[tuple[Arm, ...]] = ("F", "A", "R")
RAW_ARTIFACT_PATHS: Final[tuple[str, ...]] = (
    "preflight.json",
    "measurements.json",
    "verdicts.json",
    "report.md",
    *(f"{arm}/{name}.json" for arm in _PERSISTENT_ARMS for name in _ARM_FILES),
    *(f"R/T{t:02d}/{name}.json" for t in _VERSIONS for name in _R_FILES),
)
"""Every raw live artifact path relative to the experiment directory: 4 + 16 + 96 = 116.
T7 refuses to start when any of them exists."""

_ADJUDICATION_PENDING: Final = "architect adjudication pending"
_ADJUDICATION_RECORDED: Final = "architect adjudication recorded"
_CHECKPOINT_IDS: Final[tuple[str, ...]] = tuple(checkpoint.id for checkpoint in CHECKPOINTS)
_TREE_SHA: Final = re.compile(r"^[0-9a-f]{40}$")
_TEMP_PREFIX: Final = ".9p3-"
_CALL_IDENTITY_FIELDS: Final = ("arm", "t", "call_number", "request_sha256")


def _r_dir(t: int) -> str:
    return f"R/T{t:02d}"


# --------------------------------------------------------------------------- manifest


class Ceilings(FrozenModel):
    """Spec §17 ceilings; field names are exactly ``integrity.CEILING_KEYS``."""

    max_frontier_calls: int = Field(ge=0)
    max_judge_calls: int = Field(ge=0)
    max_semantic_retries: int = Field(ge=0)
    max_same_cell_reruns: int = Field(ge=0)
    max_human_authorizations: int = Field(ge=0)
    max_provider_cost_usd: float = Field(ge=0.0)


class ExperimentManifest(FrozenModel):
    """Spec §19 step 7 sealed manifest. Every gate-read field is spelled exactly as the
    ``integrity.MANIFEST_KEY_*`` names (checked at import). The historical-preservation
    baseline and directory list are frozen literals -- never the harness HEAD -- and the
    per-directory tree hashes are inputs T7 reads from git at that baseline."""

    experiment_version: str = Field(min_length=1)
    artifact_format_version: int = ARTIFACT_FORMAT_VERSION
    frozen_core_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    predecessor_raw_evidence_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    harness_code_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    final_seal_rule: str = Field(min_length=1)
    spec_path: str = Field(min_length=1)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)
    grpc_dns_resolver: str = Field(min_length=1)
    fr_policy_version: str = Field(min_length=1)
    fr_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    a_policy_version: str = Field(min_length=1)
    a_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    arm_schedule: tuple[tuple[int, str], ...]
    ceilings: Ceilings
    evidence: tuple[EvidenceRecord, ...]
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    leakage_needle_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    economy_rule: str = ECONOMY_RULE
    bounded_growth_rule: str = BOUNDED_GROWTH_RULE
    r_growth_rule: str = R_GROWTH_RULE
    token_diff_rule: str = TOKEN_DIFF_RULE
    early_window: tuple[int, ...]
    late_window: tuple[int, ...]
    decision_names: tuple[str, ...]
    historical_preservation_base_sha: str = Field(
        default=HISTORICAL_PRESERVATION_BASE_SHA, pattern=r"^[0-9a-f]{40}$"
    )
    historical_artifact_dirs: tuple[str, ...] = HISTORICAL_ARTIFACT_DIRS
    historical_artifact_tree_hashes: dict[str, str]
    predecessor_artifact_dir: str = PREDECESSOR_ARTIFACT_DIR
    lifecycle_project_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)


def _require_manifest_keys() -> None:
    missing = [key for key in REQUIRED_MANIFEST_KEYS if key not in ExperimentManifest.model_fields]
    if missing:
        raise RuntimeError(f"ExperimentManifest lacks gate-read manifest keys {missing}")
    if tuple(Ceilings.model_fields) != CEILING_KEYS:
        raise RuntimeError(
            f"Ceilings fields {tuple(Ceilings.model_fields)} != CEILING_KEYS {CEILING_KEYS}"
        )


_require_manifest_keys()


def _require_frozen_identity() -> None:
    """The in-process adapter identity, the ``protocol`` literals and the ``integrity``
    literals must agree before anything is sealed; a drift is a preflight failure
    waiting to happen, not a manifest."""
    fr_prompt = hashlib.sha256(CONTRASTIVE_SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest()
    a_prompt = hashlib.sha256(SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest()
    schema = semantic_output_schema_sha256()
    checks: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("F/R policy", (CONTRASTIVE_POLICY_VERSION, FR_POLICY_VERSION, FR_POLICY_VERSION_FROZEN)),
        (
            "F/R prompt sha256",
            (
                fr_prompt,
                CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
                FR_PROMPT_SHA256,
                FR_PROMPT_SHA256_FROZEN,
            ),
        ),
        ("A policy", (POLICY_VERSION, A_POLICY_VERSION, A_POLICY_VERSION_FROZEN)),
        (
            "A prompt sha256",
            (a_prompt, SYSTEM_INSTRUCTION_SHA256, A_PROMPT_SHA256, A_PROMPT_SHA256_FROZEN),
        ),
        (
            "output schema sha256",
            (
                schema,
                SEMANTIC_OUTPUT_SCHEMA_SHA256,
                OUTPUT_SCHEMA_SHA256,
                OUTPUT_SCHEMA_SHA256_FROZEN,
            ),
        ),
    )
    drift = [f"{label}: {list(values)}" for label, values in checks if len(set(values)) != 1]
    if drift:
        raise RuntimeError(
            "frozen identity drift; refusing to build a manifest: " + "; ".join(drift)
        )


def _validated_tree_hashes(hashes: Mapping[str, str]) -> dict[str, str]:
    """Exactly the six frozen directories, each mapped to a 40-hex git tree sha, in
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
    spec bytes' SHA256 and the six historical tree hashes read at the frozen baseline.
    Everything else is a frozen literal or a ``timeline`` / ``protocol`` /
    ``expectations`` / ``leakage`` value."""
    _require_frozen_identity()
    return ExperimentManifest(
        experiment_version=EXPERIMENT_VERSION,
        artifact_format_version=ARTIFACT_FORMAT_VERSION,
        frozen_core_sha=FROZEN_CORE_SHA,
        predecessor_raw_evidence_sha=PREDECESSOR_RAW_EVIDENCE_SHA,
        harness_code_sha=harness_code_sha,
        final_seal_rule=FINAL_SEAL_RULE,
        spec_path=SPEC_PATH,
        spec_sha256=spec_sha256,
        provider=PROVIDER,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        grpc_dns_resolver=GRPC_DNS_RESOLVER_FROZEN,
        fr_policy_version=FR_POLICY_VERSION,
        fr_prompt_sha256=FR_PROMPT_SHA256,
        a_policy_version=A_POLICY_VERSION,
        a_prompt_sha256=A_PROMPT_SHA256,
        output_schema_sha256=OUTPUT_SCHEMA_SHA256,
        arm_schedule=ARM_SCHEDULE,
        ceilings=Ceilings(
            max_frontier_calls=MAX_FRONTIER_CALLS,
            max_judge_calls=MAX_JUDGE_CALLS,
            max_semantic_retries=MAX_SEMANTIC_RETRIES,
            max_same_cell_reruns=MAX_SAME_CELL_RERUNS,
            max_human_authorizations=MAX_HUMAN_AUTHORIZATIONS,
            max_provider_cost_usd=MAX_COST_USD,
        ),
        evidence=evidence_records(),
        corpus_sha256=corpus_sha256(),
        leakage_needle_set_sha256=needle_set_sha256(),
        expectations_sha256=canonical_sha256(expectations_document()),
        economy_rule=ECONOMY_RULE,
        bounded_growth_rule=BOUNDED_GROWTH_RULE,
        r_growth_rule=R_GROWTH_RULE,
        token_diff_rule=TOKEN_DIFF_RULE,
        early_window=EARLY_WINDOW,
        late_window=LATE_WINDOW,
        decision_names=DECISION_NAMES,
        historical_preservation_base_sha=HISTORICAL_PRESERVATION_BASE_SHA,
        historical_artifact_dirs=HISTORICAL_ARTIFACT_DIRS,
        historical_artifact_tree_hashes=_validated_tree_hashes(historical_tree_hashes),
        predecessor_artifact_dir=PREDECESSOR_ARTIFACT_DIR,
        lifecycle_project_id=PROJECT_ID,
        scope=SCOPE,
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
    """Guard every document, refuse if any target exists, then write each atomically."""
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
        "manifest.json": pretty_json(manifest),
        "expectations.json": expectations_json(),
    }
    _write_all(out_dir, documents, phase="preregistration")
    return {name: canonical_sha256(json.loads(text)) for name, text in documents.items()}


def existing_raw_artifacts(out_dir: Path) -> tuple[str, ...]:
    """The ``RAW_ARTIFACT_PATHS`` already present under ``out_dir``, in contract order.
    T7 must refuse to start when this is non-empty (a preserved failed preflight
    included)."""
    return tuple(name for name in RAW_ARTIFACT_PATHS if (out_dir / name).exists())


def write_preflight(
    out_dir: Path,
    gates: tuple[GateResult, ...],
    *,
    frozen_sha: str,
    leakage: LeakageResult,
    observed_grpc_dns_resolver: str | None,
) -> Path:
    """Write ``preflight.json`` (passed or failed alike); refuse if it already exists.

    A failed preflight is ``run_status = ABORTED_PREFLIGHT`` with ``frontier_calls = 0``,
    stated explicitly; a passed one has no run status of its own (``null``) and, being
    pre-construction, still zero calls. The observed ``GRPC_DNS_RESOLVER`` is recorded
    verbatim (``None`` when unset) so gate 21 is auditable. Gate details are diagnostic
    text and are redacted."""
    passed = all_passed(gates)
    document = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "frozen_sha": frozen_sha,
        "all_passed": passed,
        "run_status": None if passed else RunStatus.ABORTED_PREFLIGHT.value,
        "frontier_calls": 0,
        "gates": [
            gate.model_copy(update={"detail": redact_secrets(gate.detail)}).model_dump(mode="json")
            for gate in gates
        ],
        "leakage": leakage.model_dump(mode="json"),
        "observed_grpc_dns_resolver": observed_grpc_dns_resolver,
    }
    _write_all(out_dir, {"preflight.json": pretty_json(document)}, phase="preflight")
    return out_dir / "preflight.json"


def write_run_artifacts(
    out_dir: Path, run: RunResult, verdicts: tuple[IntegrityVerdict, ...]
) -> tuple[str, ...]:
    """Write the whole raw tree except ``preflight.json`` (115 paths) at once.

    Refuses -- writing nothing -- when any of those paths exists, when any request
    record is not bound one-to-one and in order to its reference snapshot, when
    ``verdicts`` is not exactly I1..I15 in order, or when any exact
    ``rendered_user_request`` carries a secret shape. Diagnostic text is redacted.
    Every cell of every run status is written; ``NOT_RUN`` cells are structural
    entries. ``select_architecture`` is never reached here.
    """
    _require_verdict_ids(verdicts)
    _require_bound_requests(run)
    _require_secret_free_requests(run)
    return _write_all(out_dir, _run_documents(run, verdicts), phase="raw run")


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
        if _identity(record) != _identity(snapshot):
            raise ValueError(
                f"{label}: request record {index} {_identity(record)} is not the identity of "
                f"its reference snapshot {_identity(snapshot)}"
            )


def _require_bound_requests(run: RunResult) -> None:
    for cell in run.cells:
        _require_bound(_cell_label(cell), cell.requests, cell.reference_snapshots)
    for summary in (run.f, run.a):
        _require_bound(f"{summary.arm} summary", summary.requests, summary.reference_snapshots)


def _all_request_records(run: RunResult) -> Iterable[RequestRecord]:
    for cell in run.cells:
        yield from cell.requests
    yield from run.f.requests
    yield from run.a.requests


def _require_secret_free_requests(run: RunResult) -> None:
    for record in _all_request_records(run):
        if contains_secret_shape(record.rendered_user_request):
            raise ValueError(
                f"secret-shaped token inside rendered_user_request ({_call_label(record)}); "
                "refusing to write raw artifacts"
            )


# --------------------------------------------------------------------------- documents


def _cell_label(cell: CellRecord) -> str:
    return f"{cell.arm} T{cell.t}"


def _call_label(record: RequestRecord) -> str:
    return f"arm {record.arm} T{record.t} call {record.call_number}"


def _redacted(text: str | None) -> str | None:
    return None if text is None else redact_secrets(text)


def _arm_cells(run: RunResult, arm: Arm) -> tuple[CellRecord, ...]:
    return tuple(sorted((cell for cell in run.cells if cell.arm == arm), key=lambda c: c.t))


def _entries(cell: CellRecord) -> list[dict[str, Any]]:
    """The paired ``{"record", "reference_snapshot"}`` entries of one cell, in order."""
    return [
        {
            "record": record.model_dump(mode="json"),
            "reference_snapshot": snapshot.model_dump(mode="json"),
        }
        for record, snapshot in zip(cell.requests, cell.reference_snapshots, strict=True)
    ]


def _calls(cell: CellRecord) -> list[dict[str, Any]]:
    """Per-call structural facts aligned by call order: receipts, measurements and
    drafts are appended in call order and a call that fails leaves none, so index
    ``i`` belongs to call ``i``."""
    calls: list[dict[str, Any]] = []
    for index, record in enumerate(cell.requests):
        receipt = cell.receipts[index] if index < len(cell.receipts) else None
        row = cell.measurements[index] if index < len(cell.measurements) else None
        calls.append(
            {
                "t": record.t,
                "call_number": record.call_number,
                "request_sha256": record.request_sha256,
                "rendered_request_chars": len(record.rendered_user_request),
                "receipt": receipt,
                "measurement": None if row is None else row.model_dump(mode="json"),
                "draft_recorded": index < len(cell.draft_payloads),
            }
        )
    return calls


def _cell_result(cell: CellRecord) -> dict[str, Any]:
    return {
        "arm": cell.arm,
        "t": cell.t,
        "position": cell.position,
        "status": cell.status,
        "error": _redacted(cell.error),
        "project_id": cell.project_id,
        "evidence_ids_shown": list(cell.evidence_ids_shown),
        "neighborhood": list(cell.neighborhood),
        "claim_neighborhood": list(cell.claim_neighborhood),
        "pending_supersede_judgment_ids": list(cell.pending_supersede_judgment_ids),
        "root_designations": [r.model_dump(mode="json") for r in cell.root_designations],
        "eligible_targets": (
            None if cell.eligible_targets is None else cell.eligible_targets.model_dump(mode="json")
        ),
        "authorizations": [a.model_dump(mode="json") for a in cell.authorizations],
        "calls": _calls(cell),
        "request_count": len(cell.requests),
        "reference_snapshot_count": len(cell.reference_snapshots),
        "receipt_count": len(cell.receipts),
        "measurement_count": len(cell.measurements),
        "ledger_event_count": len(cell.ledger),
        "state_revision": None if cell.state_snapshot is None else cell.state_snapshot.revision,
    }


def _ledger_document(project_id: str, ledger: tuple[StoredEvent, ...]) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "event_count": len(ledger),
        "events": [stored.model_dump(mode="json") for stored in ledger],
    }


def _drafts_document(arm: Arm, project_id: str, cells: Iterable[CellRecord]) -> dict[str, Any]:
    return {
        "arm": arm,
        "project_id": project_id,
        "drafts": [
            {"t": cell.t, "index": index, "payload": payload}
            for cell in cells
            for index, payload in enumerate(cell.draft_payloads)
        ],
    }


def _receipts_document(arm: Arm, project_id: str, cells: Iterable[CellRecord]) -> dict[str, Any]:
    return {
        "arm": arm,
        "project_id": project_id,
        "receipts": [
            {"t": cell.t, "index": index, "receipt": receipt}
            for cell in cells
            for index, receipt in enumerate(cell.receipts)
        ],
    }


def _decisions_document(arm: Arm, project_id: str, cells: Iterable[CellRecord]) -> dict[str, Any]:
    return {
        "arm": arm,
        "project_id": project_id,
        "steps": [
            {
                "t": cell.t,
                "position": cell.position,
                "status": cell.status,
                "stage_decisions": [
                    [d.model_dump(mode="json") for d in stage] for stage in cell.stage_decisions
                ],
            }
            for cell in cells
        ],
    }


def _requests_document(
    arm: Arm, project_id: str, cells: Iterable[CellRecord], *, t: int | None = None
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "arm": arm,
        "project_id": project_id,
    }
    if t is not None:
        document["t"] = t
    document["entries"] = [entry for cell in cells for entry in _entries(cell)]
    return document


def _arm_documents(run: RunResult, summary: ArmSummary) -> dict[str, str]:
    arm: Arm = summary.arm
    cells = _arm_cells(run, arm)
    project_id = summary.project_id
    result = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "arm": arm,
        "project_id": project_id,
        "run_status": run.status.value,
        "run_error": _redacted(run.error),
        "steps": [_cell_result(cell) for cell in cells],
        "roots": {locus: root.model_dump(mode="json") for locus, root in summary.roots.items()},
        "replay": None if summary.replay is None else summary.replay.model_dump(mode="json"),
        "authorization_count": len(summary.authorizations),
        "eligible_target_snapshot_count": len(summary.eligible_targets),
        "request_count": len(summary.requests),
        "reference_snapshot_count": len(summary.reference_snapshots),
        "ledger_event_count": len(summary.ledger),
        "budget": run.budget.model_dump(mode="json"),
        "final_state": summary.final_state.model_dump(mode="json"),
        "final_view": summary.final_view.model_dump(mode="json"),
    }
    eligible = {
        "arm": arm,
        "project_id": project_id,
        "snapshots": [e.model_dump(mode="json") for e in summary.eligible_targets],
        "by_cell": [
            {
                "t": cell.t,
                "eligible_targets": (
                    None
                    if cell.eligible_targets is None
                    else cell.eligible_targets.model_dump(mode="json")
                ),
            }
            for cell in cells
        ],
    }
    authorizations = {
        "arm": arm,
        "project_id": project_id,
        "records": [a.model_dump(mode="json") for a in summary.authorizations],
        "by_cell": [
            {"t": cell.t, "records": [a.model_dump(mode="json") for a in cell.authorizations]}
            for cell in cells
        ],
    }
    return {
        f"{arm}/requests.json": pretty_json(_requests_document(arm, project_id, cells)),
        f"{arm}/drafts.json": pretty_json(_drafts_document(arm, project_id, cells)),
        f"{arm}/receipts.json": pretty_json(_receipts_document(arm, project_id, cells)),
        f"{arm}/decisions.json": pretty_json(_decisions_document(arm, project_id, cells)),
        f"{arm}/eligible_targets.json": pretty_json(eligible),
        f"{arm}/authorizations.json": pretty_json(authorizations),
        f"{arm}/ledger.json": pretty_json(_ledger_document(project_id, summary.ledger)),
        f"{arm}/result.json": pretty_json(result),
    }


def _r_documents(run: RunResult, cell: CellRecord) -> dict[str, str]:
    prefix = _r_dir(cell.t)
    project_id = cell.project_id
    result = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "run_status": run.status.value,
        **_cell_result(cell),
        "budget": run.budget.model_dump(mode="json"),
        "state_snapshot": (
            None if cell.state_snapshot is None else cell.state_snapshot.model_dump(mode="json")
        ),
        "view_snapshot": (
            None if cell.view_snapshot is None else cell.view_snapshot.model_dump(mode="json")
        ),
    }
    one = (cell,)
    return {
        f"{prefix}/requests.json": pretty_json(_requests_document("R", project_id, one, t=cell.t)),
        f"{prefix}/drafts.json": pretty_json(_drafts_document("R", project_id, one)),
        f"{prefix}/receipts.json": pretty_json(_receipts_document("R", project_id, one)),
        f"{prefix}/decisions.json": pretty_json(_decisions_document("R", project_id, one)),
        f"{prefix}/ledger.json": pretty_json(_ledger_document(project_id, cell.ledger)),
        f"{prefix}/result.json": pretty_json(result),
    }


def _measurements_document(run: RunResult) -> dict[str, Any]:
    """The run's per-call rows exactly as measured: F/A rows carry ``null`` for the
    R-only cumulative raw-evidence count, R rows the integer; never coerced."""
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "run_status": run.status.value,
        "row_count": len(run.measurements),
        "rows": [row.model_dump(mode="json") for row in run.measurements],
    }


def _run_documents(run: RunResult, verdicts: tuple[IntegrityVerdict, ...]) -> dict[str, str]:
    documents: dict[str, str] = {}
    documents.update(_arm_documents(run, run.f))
    documents.update(_arm_documents(run, run.a))
    for t in _VERSIONS:
        cell = run.r_cells.get(t)
        if cell is None:
            raise ValueError(f"run carries no R record for T{t:02d}; every cell must be recorded")
        if cell.arm != "R" or cell.t != t:
            raise ValueError(f"r_cells[{t}] is {_cell_label(cell)}, not R T{t}")
        documents.update(_r_documents(run, cell))
    documents["measurements.json"] = pretty_json(_measurements_document(run))
    documents["verdicts.json"] = pretty_json(verdicts_document(run, verdicts))
    documents["report.md"] = render_report(run, verdicts)
    ordered = {name: documents[name] for name in RAW_ARTIFACT_PATHS if name in documents}
    if set(ordered) != set(RAW_ARTIFACT_PATHS) - {"preflight.json"}:
        raise RuntimeError("run documents do not cover the raw artifact tree exactly")
    return ordered


# --------------------------------------------------------------------------- verdicts (raw)


def verdicts_document(run: RunResult, verdicts: tuple[IntegrityVerdict, ...]) -> dict[str, Any]:
    """Raw ``verdicts.json`` data: the operational status and budget, the I1-I15
    deterministic verdicts (details redacted), and every architect field ``null``.
    ``select_architecture`` is never called here."""
    _require_verdict_ids(verdicts)
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "phase": "raw",
        "status": run.status.value,
        "error": _redacted(run.error),
        "budget": run.budget.model_dump(mode="json"),
        "integrity": {
            verdict.id: {
                "passed": verdict.passed,
                "detail": redact_secrets(verdict.detail),
                "applies_to": list(verdict.applies_to),
            }
            for verdict in verdicts
        },
        "semantic_checkpoints": None,
        "material_errors": None,
        "control_errors": None,
        "errors_total": None,
        "architecture_selection": None,
        "selection_inputs": None,
        "adjudication": _ADJUDICATION_PENDING,
    }


# --------------------------------------------------------------------------- report


def _md(value: object) -> str:
    text = "null" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _tri(value: bool | None) -> str:
    return "null" if value is None else str(value).lower()


def render_report(run: RunResult, verdicts: tuple[IntegrityVerdict, ...]) -> str:
    """The deterministic raw report, from the run and the verdicts only."""
    _require_verdict_ids(verdicts)
    lines: list[str] = [
        "# 9P3 long-horizon bounded memory -- raw run report",
        "",
        f"- experiment_version: {EXPERIMENT_VERSION}",
        f"- artifact_format_version: {ARTIFACT_FORMAT_VERSION}",
        f"- status: {run.status.value}",
        f"- error: {_md(_redacted(run.error))}",
        f"- frozen_core_sha: {FROZEN_CORE_SHA}",
        f"- predecessor_raw_evidence_sha: {PREDECESSOR_RAW_EVIDENCE_SHA}",
        "",
        "## Schedule",
        "",
        "| position | T | arm | status | project_id | requests | receipts | error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cell in run.cells:
        lines.append(
            f"| {cell.position} | T{cell.t:02d} | {cell.arm} | {cell.status} | {cell.project_id} "
            f"| {len(cell.requests)} | {len(cell.receipts)} | {_md(_redacted(cell.error))} |"
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
        f"- measurement_rows: {len(run.measurements)}",
        "",
        "## Roots",
        "",
        "| arm | project_id | locus | seed | status | address_id | reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for summary in (run.f, run.a):
        if not summary.roots:
            lines.append(f"| {summary.arm} | {summary.project_id} | - | - | (none) | null | - |")
        for _locus, root in sorted(summary.roots.items()):
            lines.append(
                f"| {summary.arm} | {summary.project_id} | {root.locus} | {root.seed_evidence_id} "
                f"| {root.status} | {_md(root.address_id)} | {_md(root.reason)} |"
            )
    lines += [
        "",
        "## Authorizations",
        "",
        "| arm | T | locus | target_judgment_id | outcome | submitted_judgment_id |",
        "|---|---|---|---|---|---|",
    ]
    for summary in (run.f, run.a):
        for record in summary.authorizations:
            lines.append(
                f"| {record.arm} | T{record.t:02d} | {record.target_locus} "
                f"| {record.target_judgment_id} | {record.outcome.value} "
                f"| {_md(record.submitted_judgment_id)} |"
            )
    lines += [
        "",
        "## Deterministic integrity verdicts (I1-I15)",
        "",
        "| id | passed | applies_to | detail |",
        "|---|---|---|---|",
    ]
    for verdict in verdicts:
        lines.append(
            f"| {verdict.id} | {_tri(verdict.passed)} | {','.join(verdict.applies_to)} "
            f"| {_md(redact_secrets(verdict.detail))} |"
        )
    lines += [
        "",
        "## Architecture selection",
        "",
        "Semantic checkpoints C02..C16 (F/A/R), the material and control error totals and",
        "the architecture selection are `null` in `verdicts.json`; they are architect",
        "adjudication after the raw-evidence commit (spec §10.6, §19).",
        "",
        ADJUDICATION_PENDING_LINE,
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- adjudication


class AdjudicationRefused(RuntimeError):
    """The raw tree is not the committed, clean, byte-identical evidence the architect
    adjudicated; nothing is written."""


class Adjudication(FrozenModel):
    """The architect's semantic verdicts after the raw freeze (spec §10, §16.1).

    ``checkpoints[arm]`` maps every id ``C02``..``C16`` to PASS (``True``) / FAIL;
    ``control_errors`` and ``material_errors`` are the adjudicated counts. F and A must
    be present in all three mappings; R is optional and recorded only (never a
    selection input). This module never infers a count from the checkpoints.
    """

    checkpoints: dict[Arm, dict[str, bool]]
    control_errors: dict[Arm, int]
    material_errors: dict[Arm, int]
    notes: str

    @model_validator(mode="after")
    def _check_shape(self) -> Adjudication:
        for arm, checkpoints in self.checkpoints.items():
            if set(checkpoints) != set(_CHECKPOINT_IDS):
                raise ValueError(
                    f"checkpoints[{arm!r}] keys {sorted(checkpoints)} != exactly "
                    f"{list(_CHECKPOINT_IDS)}"
                )
        for label, counts in (
            ("control_errors", self.control_errors),
            ("material_errors", self.material_errors),
        ):
            negative = {arm: n for arm, n in counts.items() if n < 0}
            if negative:
                raise ValueError(f"{label} must be non-negative: {negative}")
        for arm in _PERSISTENT_ARMS:
            for label, mapping in (
                ("checkpoints", self.checkpoints),
                ("control_errors", self.control_errors),
                ("material_errors", self.material_errors),
            ):
                if arm not in mapping:
                    raise ValueError(f"{label} lacks persistent arm {arm!r}")
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


def _token_summary(rows: list[Any]) -> tuple[TokenSummary | None, str | None]:
    """``summarize`` over the committed rows; a run that did not complete the measured
    window has no summary and the reason is recorded, never filled."""
    try:
        parsed = tuple(CallMeasurement.model_validate(row) for row in rows)
        return summarize(parsed), None
    except MeasurementMismatch as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _selection_inputs(
    raw: Mapping[str, Any],
    preflight_document: Mapping[str, Any],
    adjudication: Adjudication,
    tokens: TokenSummary | None,
) -> SelectionInputs:
    """Spec §16.1 inputs, derived only from the committed raw documents and the
    architect's counts: ``completed`` is the raw status; ``integrity_X`` is every
    I-verdict applying to X passed; ``scientifically_valid`` is completed AND the
    preflight passed AND every experiment-wide verdict passed (rule 0);
    ``errors_X = material + control``."""
    integrity: Mapping[str, Mapping[str, Any]] = raw["integrity"]

    def arm_ok(arm: Arm) -> bool:
        return all(
            verdict["passed"] is True
            for verdict in integrity.values()
            if arm in verdict["applies_to"]
        )

    completed = raw["status"] == RunStatus.COMPLETED.value
    experiment_wide = all(
        integrity[verdict_id]["passed"] is True for verdict_id in EXPERIMENT_WIDE_VERDICT_IDS
    )
    valid = completed and preflight_document["all_passed"] is True and experiment_wide

    def errors(arm: Arm) -> int:
        return adjudication.material_errors.get(arm, 0) + adjudication.control_errors.get(arm, 0)

    return SelectionInputs(
        completed=completed,
        scientifically_valid=valid,
        errors_F=errors("F"),
        errors_A=errors("A"),
        errors_R=errors("R"),
        integrity_F=arm_ok("F"),
        integrity_A=arm_ok("A"),
        f_total=0 if tokens is None else tokens.f_total,
        a_total=0 if tokens is None else tokens.a_total,
        r_total=0 if tokens is None else tokens.r_total,
        f_early_mean="0" if tokens is None else tokens.f_early_mean,
        f_late_mean="0" if tokens is None else tokens.f_late_mean,
        a_early_mean="0" if tokens is None else tokens.a_early_mean,
        a_late_mean="0" if tokens is None else tokens.a_late_mean,
        r_early_mean="0" if tokens is None else tokens.r_early_mean,
        r_late_mean="0" if tokens is None else tokens.r_late_mean,
    )


def _adjudicated_report(
    raw_report: str,
    *,
    raw_run_commit_sha: str,
    adjudication: Adjudication,
    inputs: SelectionInputs,
    outcome: SelectionOutcome,
    errors_total: Mapping[Arm, int],
    token_summary_error: str | None,
) -> str:
    lines = raw_report.split("\n")
    if lines.count(ADJUDICATION_PENDING_LINE) != 1:
        raise AdjudicationRefused(
            "committed report.md does not carry exactly one pending adjudication line; "
            "the raw tree is not un-adjudicated raw evidence"
        )
    decision_line = (
        f"architecture_selection = {outcome.decision} (rule {outcome.matched_rule}; "
        f"architect adjudication over raw-run commit {raw_run_commit_sha})"
    )
    lines[lines.index(ADJUDICATION_PENDING_LINE)] = decision_line
    arms = [arm for arm in _ALL_ARMS if arm in adjudication.checkpoints]
    lines += [
        "## Adjudication",
        "",
        f"- raw_run_commit_sha: {raw_run_commit_sha}",
        f"- decision: {outcome.decision}",
        f"- matched_rule: {outcome.matched_rule}",
        f"- reason: {_md(outcome.reason)}",
        f"- token_summary_error: {_md(token_summary_error)}",
        "",
        "### Semantic checkpoints",
        "",
        "| checkpoint | " + " | ".join(arms) + " |",
        "|---|" + "---|" * len(arms),
    ]
    for checkpoint_id in _CHECKPOINT_IDS:
        cells = " | ".join(_tri(adjudication.checkpoints[arm][checkpoint_id]) for arm in arms)
        lines.append(f"| {checkpoint_id} | {cells} |")
    lines += [
        "",
        "### Error counts",
        "",
        "| arm | material_errors | control_errors | errors_total |",
        "|---|---|---|---|",
    ]
    for arm in _ALL_ARMS:
        if arm in errors_total:
            lines.append(
                f"| {arm} | {adjudication.material_errors.get(arm)} "
                f"| {adjudication.control_errors.get(arm)} | {errors_total[arm]} |"
            )
    lines += ["", "### Selection inputs", ""]
    lines += [f"- {key}: {_md(value)}" for key, value in inputs.model_dump(mode="json").items()]
    lines += ["", "### Predicates", ""]
    lines += [f"- {key}: {_md(value)}" for key, value in outcome.predicates.items()]
    lines += ["", "### Notes", "", _md(redact_secrets(adjudication.notes)), ""]
    return "\n".join(lines)


def write_adjudication(
    out_dir: Path,
    *,
    raw_run_commit_sha: str,
    git: GitCliLike,
    adjudication: Adjudication,
    repo_root: Path,
) -> tuple[str, ...]:
    """Record the architect's adjudication over a committed raw tree; the ONLY place
    ``select_architecture`` runs.

    ``repo_root`` is the repository the raw-run commit lives in; ``out_dir`` must be
    inside it (``ValueError`` otherwise), and every raw path is compared against
    ``git.show_bytes(raw_run_commit_sha, "<out_dir relative to repo_root>/<path>")``.
    Before any write: ``git.head()`` must equal ``raw_run_commit_sha``, ``git.dirty()``
    must be empty, and every one of the 116 raw files must exist and be byte-identical
    to the committed bytes -- any miss is an ``AdjudicationRefused`` with nothing
    written. On success exactly ``verdicts.json`` and ``report.md`` are rewritten: the
    semantic fields from the adjudication, the derived ``selection_inputs`` (audit
    trail), the token summary over the COMMITTED ``measurements.json`` and the
    ``architecture_selection``. Every other raw file is untouched.
    """
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
    preflight_document = json.loads(committed["preflight.json"].decode("utf-8"))
    rows = json.loads(committed["measurements.json"].decode("utf-8"))["rows"]
    if raw.get("phase") != "raw" or raw.get("architecture_selection") is not None:
        raise AdjudicationRefused("committed verdicts.json is not un-adjudicated raw evidence")
    tokens, token_summary_error = _token_summary(rows)
    inputs = _selection_inputs(raw, preflight_document, adjudication, tokens)
    outcome = select_architecture(inputs)
    errors_total = {
        arm: adjudication.material_errors[arm] + adjudication.control_errors[arm]
        for arm in _ALL_ARMS
        if arm in adjudication.material_errors and arm in adjudication.control_errors
    }
    document: dict[str, Any] = {
        **raw,
        "phase": "adjudicated",
        "raw_run_commit_sha": raw_run_commit_sha,
        "semantic_checkpoints": {
            arm: dict(adjudication.checkpoints[arm]) for arm in adjudication.checkpoints
        },
        "material_errors": dict(adjudication.material_errors),
        "control_errors": dict(adjudication.control_errors),
        "errors_total": errors_total,
        "selection_inputs": inputs.model_dump(mode="json"),
        "token_summary": None if tokens is None else tokens.model_dump(mode="json"),
        "token_summary_error": token_summary_error,
        "architecture_selection": outcome.model_dump(mode="json"),
        "adjudication": _ADJUDICATION_RECORDED,
        "adjudication_notes": redact_secrets(adjudication.notes),
    }
    documents = {
        "verdicts.json": pretty_json(document),
        "report.md": _adjudicated_report(
            committed["report.md"].decode("utf-8"),
            raw_run_commit_sha=raw_run_commit_sha,
            adjudication=adjudication,
            inputs=inputs,
            outcome=outcome,
            errors_total=errors_total,
            token_summary_error=token_summary_error,
        ),
    }
    _refuse_secret_shapes(documents, phase="adjudication")
    for name, text in documents.items():
        _write_atomic(out_dir / name, text)
    return tuple(documents)

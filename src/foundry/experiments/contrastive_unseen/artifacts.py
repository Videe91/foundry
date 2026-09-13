"""Sealed preregistration and write-once raw artifacts for the 9P2 unseen-lifecycle
experiment (spec §11, §16, §17; T6 brief; clarifications C3, C4, C5).

Two artifact families live under the experiment directory:

* **preregistration** (``PREREGISTRATION_FILE_NAMES``): ``manifest.json`` -- the typed
  ``ExperimentManifest`` sealing the frozen identity (core SHA, pre-artifact harness
  HEAD, spec SHA, provider/model/effort, every policy version and prompt hash, the
  output-schema hash, arm schedule, ceilings, evidence records, needle-set hash, the
  canonical ``expectations_sha256`` and the economy/decision literals) -- and
  ``expectations.json`` -- exactly ``expectations_document()``, pretty-printed. No
  self-referential seal SHA is embedded: the final seal commit is identified by the
  ``final_seal_rule`` text and checked by ``integrity`` gate 1 at run time.
* **raw live artifacts** (``RAW_ARTIFACT_PATHS``): the spec §17.2 tree, written once
  and never overwritten -- ``preflight.json``, ``verdicts.json``, ``report.md``, the
  F/A per-arm files and the R/T1..T4 per-entry files. Every schedule position is
  written, including ``FAILED`` and ``NOT_RUN`` cells (a ``NOT_RUN`` cell is a
  ``result.json`` with ``status: NOT_RUN`` and empty collections); a cell is never
  silently omitted, and a preserved failed preflight is never replaced.

Sealing. ``canonical_bytes`` is ``json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=False).encode("utf-8")`` over parsed data; ``canonical_sha256`` hashes
those bytes. On-disk JSON is ``pretty_json`` (indent 2, sorted keys, trailing newline);
seal hashes are always taken over the parsed data, never the pretty bytes.

Verdicts (C3, C5). After a COMPLETED run ``verdicts.json`` carries ONLY the exact
deterministic F1/F3/F4/F5/F6/F7/F8 structural checks defined in clarification C3.
F2, the semantic checkpoints C1/C2/C3 for F/A/R, the material-error totals and the
``scientific_decision`` are ``null`` -- always. After a non-COMPLETED run every
F verdict is ``null`` and the operational status is recorded. This module never calls
``decision_rule`` and never grades meaning: it compares opaque ids, kinds, hashes,
routes, fingerprints and counts, nothing else.

Secret hygiene (spec §17.3). No API key or auth value is accepted by any function here.
Every document is scanned for secret-shaped tokens (the frozen ``longitudinal``
patterns, imported so there is one definition) before it is written; error and gate
text is sanitized by ``redact_secrets``; a secret shape inside any exact
``rendered_user_request`` is a construction failure and refuses the whole write.

Law of this module: it records structural facts and decides nothing about meaning. It
may import ``expectations`` because it never enters the provider request path; it
constructs no reasoner and makes no network call. It never writes outside ``out_dir``
and never touches the historical 9P artifact directory, which it only names.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    SYSTEM_INSTRUCTION_SHA256,
)
from foundry.domain.common import FrozenModel
from foundry.domain.events import EventType, SemanticJudgmentPayload, StoredEvent
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentProposal,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
    proposal_signature,
)
from foundry.experiments.contrastive_unseen.authority import HUMAN_FINGERPRINT
from foundry.experiments.contrastive_unseen.expectations import expectations_document
from foundry.experiments.contrastive_unseen.integrity import (
    A_POLICY_VERSION_FROZEN,
    A_PROMPT_SHA256_FROZEN,
    FR_POLICY_VERSION_FROZEN,
    FR_PROMPT_SHA256_FROZEN,
    GRPC_DNS_RESOLVER_FROZEN,
    HISTORICAL_9P_ARTIFACT_DIR,
    OUTPUT_SCHEMA_SHA256_FROZEN,
    REQUIRED_MANIFEST_KEYS,
    V1_ABORT_EVIDENCE_SHA,
    V1_ARTIFACT_DIR,
    GateResult,
    all_passed,
)
from foundry.experiments.contrastive_unseen.leakage import LeakageResult, needle_set_sha256
from foundry.experiments.contrastive_unseen.records import RequestRecord
from foundry.experiments.contrastive_unseen.runner import (
    ArmSummary,
    RootKey,
    RunResult,
    RunStatus,
    StepRecord,
)
from foundry.experiments.contrastive_unseen.timeline import (
    ARM_SCHEDULE,
    EXPERIMENT_VERSION,
    FROZEN_CORE_SHA,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    PROJECT_ID,
    SCOPE,
    EvidenceRecord,
    evidence_records,
)
from foundry.experiments.longitudinal.artifacts import contains_secret_shape, redact_secrets

__all__ = [
    "ARTIFACT_FORMAT_VERSION",
    "DECISION_RESULTS",
    "ECONOMY_RULE",
    "FINAL_SEAL_RULE",
    "F_VERDICT_IDS",
    "MODEL",
    "PREDECESSOR_EXPERIMENT_VERSION",
    "PREREGISTRATION_FILE_NAMES",
    "PROVIDER",
    "RAW_ARTIFACT_PATHS",
    "REASONING_EFFORT",
    "SPEC_PATH",
    "Ceilings",
    "ExperimentManifest",
    "FVerdict",
    "FVerdictId",
    "build_manifest",
    "canonical_bytes",
    "canonical_sha256",
    "contains_secret_shape",
    "deterministic_f_verdicts",
    "existing_raw_artifacts",
    "expectations_json",
    "manifest_sha256",
    "pretty_json",
    "redact_secrets",
    "render_report",
    "verdicts_document",
    "write_preflight",
    "write_preregistration",
    "write_run_artifacts",
]

# --------------------------------------------------------------------------- literals

ARTIFACT_FORMAT_VERSION: Final = 1
SPEC_PATH: Final = "docs/superpowers/specs/2026-09-12-9p2-unseen-lifecycle-experiment-design.md"
FINAL_SEAL_RULE: Final = (
    "live HEAD must equal --frozen-sha; its single parent must equal harness_code_sha; "
    "parent..HEAD may add only manifest.json and expectations.json"
)
PROVIDER: Final = "xai"
MODEL: Final = "grok-4.6"
REASONING_EFFORT: Final = "high"
ECONOMY_RULE: Final = "4*F_input_tokens_T2_T4 <= 3*R_input_tokens_T2_T4"
DECISION_RESULTS: Final[tuple[str, ...]] = ("PASS", "INCONCLUSIVE", "FAIL")
PREDECESSOR_EXPERIMENT_VERSION: Final = "intent-v2-contrastive-unseen-lifecycle-v1"
"""The v1 identity this v2 revision supersedes operationally (resolver only); sealed
into the manifest so the lineage is explicit. Its artifacts are protected by gate 22."""
PREREGISTRATION_FILE_NAMES: Final[tuple[str, ...]] = ("manifest.json", "expectations.json")

_ARM_FILES: Final[tuple[str, ...]] = (
    "requests.json",
    "drafts.json",
    "receipts.json",
    "decisions.json",
    "authorizations.json",
    "ledger.json",
    "result.json",
)
_R_FILES: Final[tuple[str, ...]] = (
    "requests.json",
    "drafts.json",
    "receipts.json",
    "decisions.json",
    "ledger.json",
    "result.json",
)
_STEPS: Final[tuple[int, ...]] = (1, 2, 3, 4)
RAW_ARTIFACT_PATHS: Final[tuple[str, ...]] = (
    "preflight.json",
    "verdicts.json",
    "report.md",
    *(f"F/{name}" for name in _ARM_FILES),
    *(f"A/{name}" for name in _ARM_FILES),
    *(f"R/T{t}/{name}" for t in _STEPS for name in _R_FILES),
)
"""Spec §17.2, restated: every raw live artifact path relative to the experiment
directory. T7 refuses to start when any of them exists."""

FVerdictId = Literal["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]
F_VERDICT_IDS: Final[tuple[FVerdictId, ...]] = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")
_ROOT_KEYS: Final[tuple[RootKey, ...]] = ("A", "B", "N")
_ARMS: Final[tuple[str, ...]] = ("F", "A", "R")
_CHECKPOINTS: Final[tuple[str, ...]] = ("C1", "C2", "C3")
_ADJUDICATION_PENDING: Final = "architect adjudication pending"
_CALL1_KINDS: Final[frozenset[str]] = frozenset({"BIND_TO_ADDRESS", "CREATE_ADDRESS"})
_CALL2_KINDS: Final[frozenset[str]] = frozenset(
    {"SUPPORTS_CLAIM", "ASSERT_CLAIM", "SUPERSEDE", "CONFLICTS_WITH"}
)
_FORBIDDEN_KINDS: Final[frozenset[str]] = frozenset({"EQUIVALENT", "DISTINCT"})
_HUMAN_AUTHORITY_REASON: Final = "HUMAN_AUTHORITY"
_ECONOMICS_FIELDS: Final[tuple[str, ...]] = (
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "wall_clock_ms",
    "draft_count",
)


# --------------------------------------------------------------------------- canonical


def canonical_bytes(obj: object) -> bytes:
    """The sealing bytes of ``obj`` (a model is dumped to JSON data first)."""
    return json.dumps(
        _jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_sha256(obj: object) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def pretty_json(obj: object) -> str:
    """On-disk form: indented, sorted, UTF-8, newline-terminated. Never hashed."""
    return json.dumps(_jsonable(obj), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _jsonable(value: object) -> Any:
    """Plain JSON data for anything the runner records; unknown objects become ``repr``."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return repr(value)


# --------------------------------------------------------------------------- manifest


class Ceilings(FrozenModel):
    max_frontier_calls: int = Field(ge=0)
    max_judge_calls: int = Field(ge=0)
    max_human_authorizations: int = Field(ge=0)
    max_cost_usd: float = Field(ge=0.0)


class ExperimentManifest(FrozenModel):
    """Spec §17.1 sealed manifest. Field names of the gate-read fields are exactly the
    ``integrity.MANIFEST_KEY_*`` names; ``REQUIRED_MANIFEST_KEYS`` is checked at import.

    v2 revision adds four operational fields -- the preregistered ``grpc_dns_resolver``,
    the preserved ``v1_abort_evidence_sha`` / ``v1_artifact_dir`` and the
    ``predecessor_experiment_version`` -- all frozen literals, never read from the
    environment, and covered by the seal hash like every other field."""

    experiment_version: str = Field(min_length=1)
    artifact_format_version: int = ARTIFACT_FORMAT_VERSION
    frozen_core_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    harness_code_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    final_seal_rule: str = Field(min_length=1)
    spec_path: str = Field(min_length=1)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)
    fr_policy_version: str = Field(min_length=1)
    fr_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    a_policy_version: str = Field(min_length=1)
    a_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    arm_schedule: tuple[tuple[int, str], ...]
    ceilings: Ceilings
    evidence: tuple[EvidenceRecord, ...]
    economy_rule: str = Field(min_length=1)
    decision_results: tuple[str, ...]
    leakage_needle_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_9p_artifact_dir: str = Field(min_length=1)
    lifecycle_project_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    grpc_dns_resolver: str = Field(min_length=1)
    v1_abort_evidence_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    v1_artifact_dir: str = Field(min_length=1)
    predecessor_experiment_version: str = Field(min_length=1)


def _require_manifest_keys() -> None:
    missing = [key for key in REQUIRED_MANIFEST_KEYS if key not in ExperimentManifest.model_fields]
    if missing:
        raise RuntimeError(f"ExperimentManifest lacks gate-read manifest keys {missing}")


_require_manifest_keys()


def _require_frozen_identity() -> None:
    """The in-process adapter identity must equal the frozen literals before anything is
    sealed; a drift here is a preflight failure waiting to happen, not a manifest."""
    pairs = (
        ("F/R policy", CONTRASTIVE_POLICY_VERSION, FR_POLICY_VERSION_FROZEN),
        ("F/R prompt sha256", CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256, FR_PROMPT_SHA256_FROZEN),
        ("A policy", POLICY_VERSION, A_POLICY_VERSION_FROZEN),
        ("A prompt sha256", SYSTEM_INSTRUCTION_SHA256, A_PROMPT_SHA256_FROZEN),
        ("output schema sha256", SEMANTIC_OUTPUT_SCHEMA_SHA256, OUTPUT_SCHEMA_SHA256_FROZEN),
    )
    drift = [
        f"{label}: adapter {actual!r} != frozen {frozen!r}"
        for label, actual, frozen in pairs
        if actual != frozen
    ]
    if drift:
        raise RuntimeError(
            "frozen identity drift; refusing to build a manifest: " + "; ".join(drift)
        )


def build_manifest(*, harness_code_sha: str, spec_sha256: str) -> ExperimentManifest:
    """The sealed manifest for ``harness_code_sha`` (the clean pre-artifact HEAD) and the
    exact spec bytes' SHA256. Everything else is a frozen literal or a timeline,
    expectations, leakage or adapter constant."""
    _require_frozen_identity()
    return ExperimentManifest(
        experiment_version=EXPERIMENT_VERSION,
        artifact_format_version=ARTIFACT_FORMAT_VERSION,
        frozen_core_sha=FROZEN_CORE_SHA,
        harness_code_sha=harness_code_sha,
        final_seal_rule=FINAL_SEAL_RULE,
        spec_path=SPEC_PATH,
        spec_sha256=spec_sha256,
        provider=PROVIDER,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        fr_policy_version=CONTRASTIVE_POLICY_VERSION,
        fr_prompt_sha256=CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
        a_policy_version=POLICY_VERSION,
        a_prompt_sha256=SYSTEM_INSTRUCTION_SHA256,
        output_schema_sha256=SEMANTIC_OUTPUT_SCHEMA_SHA256,
        arm_schedule=ARM_SCHEDULE,
        ceilings=Ceilings(
            max_frontier_calls=MAX_FRONTIER_CALLS,
            max_judge_calls=MAX_JUDGE_CALLS,
            max_human_authorizations=MAX_HUMAN_AUTHORIZATIONS,
            max_cost_usd=MAX_COST_USD,
        ),
        evidence=evidence_records(),
        economy_rule=ECONOMY_RULE,
        decision_results=DECISION_RESULTS,
        leakage_needle_set_sha256=needle_set_sha256(),
        expectations_sha256=canonical_sha256(expectations_document()),
        historical_9p_artifact_dir=HISTORICAL_9P_ARTIFACT_DIR,
        lifecycle_project_id=PROJECT_ID,
        scope=SCOPE,
        grpc_dns_resolver=GRPC_DNS_RESOLVER_FROZEN,
        v1_abort_evidence_sha=V1_ABORT_EVIDENCE_SHA,
        v1_artifact_dir=V1_ARTIFACT_DIR,
        predecessor_experiment_version=PREDECESSOR_EXPERIMENT_VERSION,
    )


def manifest_sha256(manifest: ExperimentManifest) -> str:
    return canonical_sha256(manifest)


def expectations_json() -> str:
    """The on-disk ``expectations.json`` text: exactly ``expectations_document()``."""
    return pretty_json(expectations_document())


# --------------------------------------------------------------------------- writing


def _refuse_existing(out_dir: Path, names: Iterable[str]) -> None:
    """Check EVERY target before writing ANY, so a recorded artifact is never partially
    replaced (spec §17.4)."""
    existing = [name for name in names if (out_dir / name).exists()]
    if existing:
        raise FileExistsError(
            f"refusing to overwrite existing artifact(s) under {out_dir}: {existing}"
        )


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".9p2-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_all(out_dir: Path, documents: Mapping[str, str]) -> tuple[str, ...]:
    """Redact every document, refuse if any target exists, then write each atomically."""
    safe = {name: redact_secrets(text) for name, text in documents.items()}
    _refuse_existing(out_dir, safe)
    for name, text in safe.items():
        _write_atomic(out_dir / name, text)
    return tuple(safe)


def write_preregistration(out_dir: Path, manifest: ExperimentManifest) -> dict[str, str]:
    """Write exactly ``manifest.json`` and ``expectations.json``; refuse if either exists.

    The manifest's ``expectations_sha256`` must equal the canonical hash of the document
    being written next to it. Preregistration text is secret-free by construction, so a
    secret shape here is refused rather than redacted. Returns the canonical hashes.
    """
    expected = canonical_sha256(expectations_document())
    if manifest.expectations_sha256 != expected:
        raise ValueError(
            f"manifest expectations_sha256 {manifest.expectations_sha256} != canonical "
            f"expectations document {expected}; refusing to seal"
        )
    documents = {
        "manifest.json": pretty_json(manifest),
        "expectations.json": expectations_json(),
    }
    for name, text in documents.items():
        if contains_secret_shape(text):
            raise ValueError(f"secret-shaped token in preregistration {name}; refusing to seal")
    _refuse_existing(out_dir, PREREGISTRATION_FILE_NAMES)
    for name in PREREGISTRATION_FILE_NAMES:
        _write_atomic(out_dir / name, documents[name])
    return {
        name: canonical_sha256(json.loads(documents[name])) for name in PREREGISTRATION_FILE_NAMES
    }


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

    Spec §14.1: a failed preflight is ``run_status = ABORTED_PREFLIGHT`` with
    ``frontier_calls = 0``, stated explicitly; a passed one has no run status of its own
    (``null``) and, being pre-construction, still zero calls. v2 records the observed
    ``GRPC_DNS_RESOLVER`` verbatim (``None`` when unset) so gate 21 is auditable."""
    passed = all_passed(gates)
    document = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "frozen_sha": frozen_sha,
        "all_passed": passed,
        "run_status": None if passed else RunStatus.ABORTED_PREFLIGHT.value,
        "frontier_calls": 0,
        "gates": [gate.model_dump(mode="json") for gate in gates],
        "leakage": leakage.model_dump(mode="json"),
        "observed_grpc_dns_resolver": observed_grpc_dns_resolver,
    }
    _write_all(out_dir, {"preflight.json": pretty_json(document)})
    return out_dir / "preflight.json"


def write_run_artifacts(out_dir: Path, run: RunResult) -> tuple[str, ...]:
    """Write the whole §17.2 run tree (everything but ``preflight.json``) at once.

    Refuses -- writing nothing -- if any of those paths exists or if any exact
    ``rendered_user_request`` carries a secret shape. Error text is redacted.
    """
    _require_secret_free_requests(run)
    return _write_all(out_dir, _run_documents(run))


# --------------------------------------------------------------------------- documents


def _steps_for(run: RunResult, arm: str) -> tuple[StepRecord, ...]:
    return tuple(sorted((s for s in run.steps if s.arm == arm), key=lambda s: s.t))


def _all_request_records(run: RunResult) -> Iterable[RequestRecord]:
    yield from run.f.requests
    yield from run.a.requests
    for step in run.steps:
        yield from step.requests
    for step in run.r_steps.values():
        yield from step.requests


def _require_secret_free_requests(run: RunResult) -> None:
    for record in _all_request_records(run):
        if contains_secret_shape(record.rendered_user_request):
            raise ValueError(
                f"secret-shaped token inside rendered_user_request (arm {record.arm} "
                f"T{record.t} call {record.call_number}); refusing to write raw artifacts"
            )


def _ledger_document(project_id: str, ledger: tuple[StoredEvent, ...]) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "event_count": len(ledger),
        "events": [stored.model_dump(mode="json") for stored in ledger],
    }


def _economics(receipt: object) -> dict[str, Any] | None:
    if receipt is None:
        return None
    return {name: _jsonable(getattr(receipt, name, None)) for name in _ECONOMICS_FIELDS}


def _calls(step: StepRecord) -> list[dict[str, Any]]:
    """Per-call economics aligned by call order: receipts and drafts are appended in
    call order and a call that fails leaves none, so index ``i`` belongs to call ``i``."""
    calls: list[dict[str, Any]] = []
    for index, record in enumerate(step.requests):
        receipt = step.receipts[index] if index < len(step.receipts) else None
        calls.append(
            {
                "t": record.t,
                "call_number": record.call_number,
                "request_sha256": record.request_sha256,
                "receipt": _jsonable(receipt),
                "economics": _economics(receipt),
                "draft_recorded": index < len(step.draft_payloads),
            }
        )
    return calls


def _step_result(step: StepRecord) -> dict[str, Any]:
    return {
        "arm": step.arm,
        "t": step.t,
        "position": step.position,
        "status": step.status,
        "error": step.error,
        "project_id": step.project_id,
        "evidence_ids_shown": list(step.evidence_ids_shown),
        "neighborhood": list(step.neighborhood),
        "claim_neighborhood": list(step.claim_neighborhood),
        "pending_supersede_judgment_ids": list(step.pending_supersede_judgment_ids),
        "root_designations": [r.model_dump(mode="json") for r in step.root_designations],
        "authorizations": [a.model_dump(mode="json") for a in step.authorizations],
        "calls": _calls(step),
        "request_count": len(step.requests),
        "ledger_event_count": len(step.ledger),
        "state_revision": None if step.state_snapshot is None else step.state_snapshot.revision,
    }


def _drafts_document(arm: str, project_id: str, steps: Iterable[StepRecord]) -> dict[str, Any]:
    return {
        "arm": arm,
        "project_id": project_id,
        "drafts": [
            {"t": step.t, "index": index, "payload": _jsonable(payload)}
            for step in steps
            for index, payload in enumerate(step.draft_payloads)
        ],
    }


def _receipts_document(arm: str, project_id: str, steps: Iterable[StepRecord]) -> dict[str, Any]:
    return {
        "arm": arm,
        "project_id": project_id,
        "receipts": [
            {"t": step.t, "index": index, "receipt": _jsonable(receipt)}
            for step in steps
            for index, receipt in enumerate(step.receipts)
        ],
    }


def _decisions_document(arm: str, project_id: str, steps: Iterable[StepRecord]) -> dict[str, Any]:
    return {
        "arm": arm,
        "project_id": project_id,
        "steps": [
            {
                "t": step.t,
                "position": step.position,
                "status": step.status,
                "stage_decisions": [
                    [d.model_dump(mode="json") for d in stage] for stage in step.stage_decisions
                ],
            }
            for step in steps
        ],
    }


def _requests_document(
    arm: str, project_id: str, requests: Iterable[RequestRecord]
) -> dict[str, Any]:
    return {
        "arm": arm,
        "project_id": project_id,
        "requests": [record.model_dump(mode="json") for record in requests],
    }


def _arm_documents(run: RunResult, summary: ArmSummary) -> dict[str, str]:
    arm = summary.arm
    steps = _steps_for(run, arm)
    result = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "arm": arm,
        "project_id": summary.project_id,
        "run_status": run.status.value,
        "run_error": run.error,
        "steps": [_step_result(step) for step in steps],
        "roots": {key: root.model_dump(mode="json") for key, root in summary.roots.items()},
        "replay": None if summary.replay is None else summary.replay.model_dump(mode="json"),
        "authorization_count": len(summary.authorizations),
        "request_count": len(summary.requests),
        "ledger_event_count": len(summary.ledger),
        "budget": run.budget.model_dump(mode="json"),
        "final_state": summary.final_state.model_dump(mode="json"),
        "final_view": summary.final_view.model_dump(mode="json"),
    }
    authorizations = {
        "arm": arm,
        "project_id": summary.project_id,
        "records": [a.model_dump(mode="json") for a in summary.authorizations],
    }
    return {
        f"{arm}/requests.json": pretty_json(
            _requests_document(arm, summary.project_id, summary.requests)
        ),
        f"{arm}/drafts.json": pretty_json(_drafts_document(arm, summary.project_id, steps)),
        f"{arm}/receipts.json": pretty_json(_receipts_document(arm, summary.project_id, steps)),
        f"{arm}/decisions.json": pretty_json(_decisions_document(arm, summary.project_id, steps)),
        f"{arm}/authorizations.json": pretty_json(authorizations),
        f"{arm}/ledger.json": pretty_json(_ledger_document(summary.project_id, summary.ledger)),
        f"{arm}/result.json": pretty_json(result),
    }


def _r_documents(run: RunResult, step: StepRecord) -> dict[str, str]:
    prefix = f"R/T{step.t}"
    result = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "run_status": run.status.value,
        **_step_result(step),
        "budget": run.budget.model_dump(mode="json"),
        "state_snapshot": _jsonable(step.state_snapshot),
        "view_snapshot": _jsonable(step.view_snapshot),
    }
    return {
        f"{prefix}/requests.json": pretty_json(
            _requests_document("R", step.project_id, step.requests)
        ),
        f"{prefix}/drafts.json": pretty_json(_drafts_document("R", step.project_id, (step,))),
        f"{prefix}/receipts.json": pretty_json(_receipts_document("R", step.project_id, (step,))),
        f"{prefix}/decisions.json": pretty_json(_decisions_document("R", step.project_id, (step,))),
        f"{prefix}/ledger.json": pretty_json(_ledger_document(step.project_id, step.ledger)),
        f"{prefix}/result.json": pretty_json(result),
    }


def _run_documents(run: RunResult) -> dict[str, str]:
    documents: dict[str, str] = {}
    documents.update(_arm_documents(run, run.f))
    documents.update(_arm_documents(run, run.a))
    for t in _STEPS:
        step = run.r_steps.get(t)
        if step is None:
            raise ValueError(f"run carries no R record for T{t}; every cell must be recorded")
        documents.update(_r_documents(run, step))
    documents["verdicts.json"] = pretty_json(verdicts_document(run))
    documents["report.md"] = render_report(run)
    ordered = {name: documents[name] for name in RAW_ARTIFACT_PATHS if name in documents}
    if set(ordered) != set(RAW_ARTIFACT_PATHS) - {"preflight.json"}:
        raise RuntimeError("run documents do not cover the §17.2 tree exactly")
    return ordered


# --------------------------------------------------------------------------- verdicts (C3)


class FVerdict(FrozenModel):
    """One deterministic F check. ``passed`` is ``None`` when it is not computable or is
    an architect field (F2, always)."""

    id: FVerdictId
    passed: bool | None
    detail: str


_Check = tuple[bool, str]


def _f_step_records(run: RunResult) -> tuple[RequestRecord, ...]:
    return tuple(record for step in _steps_for(run, "F") for record in step.requests)


def _records_consistent(run: RunResult) -> str | None:
    """The arm's request records and the per-step slices must be the same records."""
    if _f_step_records(run) != run.f.requests:
        return "F step request records differ from the arm's request records"
    return None


def _f1(run: RunResult) -> _Check:
    roots = run.f.roots
    missing = [key for key in _ROOT_KEYS if key not in roots]
    if missing:
        return False, f"roots missing: {missing}"
    undesignated = [
        f"{key}:{roots[key].reason}" for key in _ROOT_KEYS if roots[key].status != "DESIGNATED"
    ]
    if undesignated:
        return False, f"roots not DESIGNATED: {undesignated}"
    ids = [roots[key].address_id for key in _ROOT_KEYS]
    if len(set(ids)) != 3:
        return False, f"root address ids are not pairwise distinct: {ids}"
    return True, f"A/B/N DESIGNATED at pairwise-distinct address ids {ids}"


def _f3(run: RunResult) -> _Check:
    problems: list[str] = []
    inconsistent = _records_consistent(run)
    if inconsistent:
        problems.append(inconsistent)
    for step in _steps_for(run, "F"):
        if step.status == "COMPLETED" and len(step.requests) != 2:
            problems.append(f"T{step.t}: {len(step.requests)} requests (expected 2)")
    for record in run.f.requests:
        kinds = frozenset(record.allowed_judgment_kinds)
        expected = _CALL1_KINDS if record.call_number == 1 else _CALL2_KINDS
        if kinds != expected:
            problems.append(
                f"T{record.t} call {record.call_number}: allowed kinds {sorted(kinds)} != "
                f"{sorted(expected)}"
            )
        if kinds & _FORBIDDEN_KINDS:
            problems.append(
                f"T{record.t} call {record.call_number}: {sorted(kinds & _FORBIDDEN_KINDS)} offered"
            )
    for t, n in sorted(Counter(record.t for record in run.f.requests).items()):
        if n > 2:
            problems.append(f"T{t}: {n} requests (a third F request exists)")
    if problems:
        return False, "; ".join(problems)
    return (
        True,
        "every F request offered exactly the locked call-1/call-2 kind sets; no third request",
    )


def _proposal_evidence_ids(proposal: JudgmentProposal) -> tuple[str, ...]:
    match proposal:
        case CreateAddressProposal() | BindToAddressProposal():
            return tuple(proposal.candidate.evidence_ids)
        case AssertClaimProposal() | SupportsClaimProposal():
            return tuple(proposal.evidence_ids)
        case _:
            return ()


def _ledger_judgments(ledger: tuple[StoredEvent, ...]) -> dict[str, tuple[int, SemanticJudgment]]:
    """``judgment_id -> (ledger sequence, judgment)`` for every recorded judgment."""
    found: dict[str, tuple[int, SemanticJudgment]] = {}
    for stored in ledger:
        payload = stored.event.payload
        if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED and isinstance(
            payload, SemanticJudgmentPayload
        ):
            found.setdefault(payload.judgment.judgment_id, (stored.sequence, payload.judgment))
    return found


def _f4(run: RunResult) -> _Check:
    problems: list[str] = []
    inconsistent = _records_consistent(run)
    if inconsistent:
        problems.append(inconsistent)
    judgments = _ledger_judgments(run.f.ledger)
    checked = 0
    for step in _steps_for(run, "F"):
        if len(step.stage_decisions) != len(step.requests):
            problems.append(
                f"T{step.t}: {len(step.requests)} requests but {len(step.stage_decisions)} "
                "decision stages; cannot map proposals to calls"
            )
            continue
        for record, decisions in zip(step.requests, step.stage_decisions, strict=True):
            citable = frozenset(record.citable_evidence_ids)
            for decision in decisions:
                entry = judgments.get(decision.judgment_id)
                if entry is None:
                    problems.append(
                        f"T{step.t} call {record.call_number}: judgment "
                        f"{decision.judgment_id} not in F ledger"
                    )
                    continue
                judgment = entry[1]
                if judgment.reasoner.is_human:
                    continue
                checked += 1
                referenced = {
                    *_proposal_evidence_ids(judgment.proposal),
                    *judgment.visible_evidence_ids,
                }
                outside = sorted(referenced - citable)
                if outside:
                    problems.append(
                        f"T{step.t} call {record.call_number}: {judgment.judgment_id} "
                        f"({judgment.proposal.kind.value}) references non-citable {outside}"
                    )
    if problems:
        return False, "; ".join(problems)
    return True, f"{checked} model-originated proposals cite only that call's evidence ids"


def _f5(run: RunResult) -> _Check:
    problems: list[str] = []
    inconsistent = _records_consistent(run)
    if inconsistent:
        problems.append(inconsistent)
    for record in run.f.requests:
        label = f"T{record.t} call {record.call_number}"
        try:
            payload = json.loads(record.rendered_user_request)
        except json.JSONDecodeError as exc:
            problems.append(f"{label}: rendered request is not JSON ({exc.msg})")
            continue
        addresses = payload.get("known_addresses", [])
        known_ids = {address["address_id"] for address in addresses}
        if known_ids != set(record.known_address_ids):
            problems.append(f"{label}: rendered known addresses != recorded known_address_ids")
        for address in addresses:
            scope = tuple(address.get("scope", []))
            if not (scope == () or SCOPE in scope):
                problems.append(
                    f"{label}: known address {address['address_id']} scope {list(scope)} "
                    "is not eligible"
                )
        for claim in payload.get("known_claims", []):
            if claim["address_id"] not in known_ids:
                problems.append(
                    f"{label}: known claim {claim['claim_id']} at unknown address "
                    f"{claim['address_id']}"
                )
        context = payload.get("comparison_context") or {}
        for transition in context.get("transitions", []):
            for address_id in transition.get("touched_address_ids", []):
                if address_id not in known_ids:
                    problems.append(
                        f"{label}: transition touched address {address_id} is not a known address"
                    )
    if problems:
        return False, "; ".join(problems)
    return True, (
        f"every known address in {len(run.f.requests)} F requests is scope-eligible; known "
        "claims and touched addresses stay within each request's known addresses"
    )


def _f6(run: RunResult) -> _Check:
    problems: list[str] = []
    inconsistent = _records_consistent(run)
    if inconsistent:
        problems.append(inconsistent)
    statuses = {step.t: step.status for step in _steps_for(run, "F")}
    incomplete = [t for t in _STEPS if statuses.get(t) != "COMPLETED"]
    if incomplete:
        problems.append(f"F did not complete T{incomplete}")
    records = run.f.requests
    if len(records) != 8:
        problems.append(f"{len(records)} F request records (expected 8)")
    for t in _STEPS:
        calls = [record.call_number for record in records if record.t == t]
        if calls != [1, 2]:
            problems.append(f"T{t}: call numbers {calls} != [1, 2]")
    identities = Counter((record.t, record.call_number) for record in records)
    duplicates = sorted(identity for identity, n in identities.items() if n > 1)
    if duplicates:
        problems.append(f"duplicate request identities {duplicates}")
    hashes = Counter(record.request_sha256 for record in records)
    repeated = sorted(sha for sha, n in hashes.items() if n > 1)
    if repeated:
        problems.append(f"repeated request sha256 (retry/fallback shape): {repeated}")
    if problems:
        return False, "; ".join(problems)
    return (
        True,
        "F completed T1-T4 with exactly 8 requests, two per T (1, 2), no duplicate identity",
    )


def _f7(run: RunResult) -> _Check:
    replay = run.f.replay
    if replay is None:
        return False, "no replay result recorded for F"
    if replay.status != "REPLAY_MATCH":
        return False, (
            f"replay {replay.status}: state_matches={replay.state_matches} "
            f"view_matches={replay.view_matches} over {replay.event_count} events"
        )
    return True, f"replay of {replay.event_count} F events reproduces final state and view"


def _f8(run: RunResult) -> _Check:
    state = run.f.final_state.semantic
    order = {
        judgment_id: sequence
        for judgment_id, (sequence, _) in _ledger_judgments(run.f.ledger).items()
    }
    applied = tuple(state.applied_judgment_ids)
    applied_set = frozenset(applied)
    problems: list[str] = []
    checked = 0
    for judgment_id in applied:
        judgment = state.judgments.get(judgment_id)
        if judgment is None:
            problems.append(f"applied judgment {judgment_id} is not in state")
            continue
        if not isinstance(judgment.proposal, SupersedeProposal):
            continue
        checked += 1
        if judgment.reasoner != HUMAN_FINGERPRINT:
            problems.append(
                f"applied SUPERSEDE {judgment_id} authored by "
                f"{judgment.reasoner.provider}:{judgment.reasoner.model}@"
                f"{judgment.reasoner.policy_version}, not the frozen human fingerprint"
            )
            continue
        admission = state.admissions.get(judgment_id)
        if (
            admission is None
            or admission.route is not AdmissionRoute.APPLY
            or _HUMAN_AUTHORITY_REASON not in admission.reasons
        ):
            routed = None if admission is None else (admission.route.value, list(admission.reasons))
            problems.append(
                f"applied SUPERSEDE {judgment_id} admission {routed} is not APPLY under "
                f"{_HUMAN_AUTHORITY_REASON}"
            )
        signature = proposal_signature(judgment.proposal)
        human_sequence = order.get(judgment_id)
        pending_model = [
            other.judgment_id
            for other in state.judgments.values()
            if isinstance(other.proposal, SupersedeProposal)
            and not other.reasoner.is_human
            and other.judgment_id not in applied_set
            and proposal_signature(other.proposal) == signature
            and human_sequence is not None
            and order.get(other.judgment_id, human_sequence) < human_sequence
        ]
        if not pending_model:
            problems.append(
                f"applied SUPERSEDE {judgment_id} has no earlier pending model-originated "
                f"proposal with signature {list(signature)}"
            )
    for record in state.supersessions:
        if record.superseding_judgment_id not in applied_set:
            problems.append(
                f"supersession by {record.superseding_judgment_id} is not an applied judgment"
            )
    if problems:
        return False, "; ".join(problems)
    return True, (
        f"{checked} applied SUPERSEDE judgment(s), each a human AGREE "
        f"(APPLY/{_HUMAN_AUTHORITY_REASON}) of an earlier pending model proposal; no model "
        "SUPERSEDE applied"
    )


_F_CHECKS: Final[dict[str, Any]] = {
    "F1": _f1,
    "F3": _f3,
    "F4": _f4,
    "F5": _f5,
    "F6": _f6,
    "F7": _f7,
    "F8": _f8,
}


def deterministic_f_verdicts(run: RunResult) -> tuple[FVerdict, ...]:
    """C3's exact deterministic F verdicts for a COMPLETED run; every one ``None`` for
    any other status; F2 ``None`` always. Never a semantic grade."""
    verdicts: list[FVerdict] = []
    for fid in F_VERDICT_IDS:
        if fid == "F2":
            verdicts.append(FVerdict(id="F2", passed=None, detail=_ADJUDICATION_PENDING))
            continue
        if run.status is not RunStatus.COMPLETED:
            verdicts.append(
                FVerdict(id=fid, passed=None, detail=f"not computed: run {run.status.value}")
            )
            continue
        passed, detail = _F_CHECKS[fid](run)
        verdicts.append(FVerdict(id=fid, passed=passed, detail=detail))
    return tuple(verdicts)


def verdicts_document(run: RunResult) -> dict[str, Any]:
    """Raw ``verdicts.json`` data (C5): deterministic F checks only; every architect
    field ``null``; ``scientific_decision`` ``null``; ``decision_rule`` never called."""
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "operational_status": run.status.value,
        "operational_error": run.error,
        "integrity": {
            verdict.id: {"passed": verdict.passed, "detail": verdict.detail}
            for verdict in deterministic_f_verdicts(run)
        },
        "semantic_checkpoints": {
            arm: {checkpoint: None for checkpoint in _CHECKPOINTS} for arm in _ARMS
        },
        "material_errors": {arm: None for arm in _ARMS},
        "scientific_decision": None,
        "adjudication": _ADJUDICATION_PENDING,
    }


# --------------------------------------------------------------------------- report


def _md(value: object) -> str:
    text = "null" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_report(run: RunResult) -> str:
    lines: list[str] = [
        "# 9P2 unseen lifecycle -- raw run report",
        "",
        f"- experiment_version: {EXPERIMENT_VERSION}",
        f"- artifact_format_version: {ARTIFACT_FORMAT_VERSION}",
        f"- operational_status: {run.status.value}",
        f"- operational_error: {_md(run.error)}",
        f"- frozen_core_sha: {FROZEN_CORE_SHA}",
        "",
        "## Schedule",
        "",
        "| position | T | arm | status | project_id | requests | error |",
        "|---|---|---|---|---|---|---|",
    ]
    for step in run.steps:
        lines.append(
            f"| {step.position} | T{step.t} | {step.arm} | {step.status} | {step.project_id} "
            f"| {len(step.requests)} | {_md(step.error)} |"
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
        "## Roots",
        "",
        "| arm | project_id | key | seed | status | address_id | reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for summary in (run.f, run.a):
        if not summary.roots:
            lines.append(f"| {summary.arm} | {summary.project_id} | - | - | (none) | null | - |")
        for _key, root in sorted(summary.roots.items()):
            lines.append(
                f"| {summary.arm} | {summary.project_id} | {root.key} | {root.seed_evidence_id} "
                f"| {root.status} | {_md(root.address_id)} | {root.reason} |"
            )
    lines += [
        "",
        "## Authorizations",
        "",
        "| arm | T | root | target_judgment_id | outcome | submitted_judgment_id |",
        "|---|---|---|---|---|---|",
    ]
    for summary in (run.f, run.a):
        for record in summary.authorizations:
            lines.append(
                f"| {record.arm} | T{record.t} | {record.root_key} | {record.target_judgment_id} "
                f"| {record.outcome.value} | {_md(record.submitted_judgment_id)} |"
            )
    lines += [
        "",
        "## Deterministic integrity verdicts (C3)",
        "",
        "| id | passed | detail |",
        "|---|---|---|",
    ]
    for verdict in deterministic_f_verdicts(run):
        passed = "null" if verdict.passed is None else str(verdict.passed).lower()
        lines.append(f"| {verdict.id} | {passed} | {_md(verdict.detail)} |")
    lines += [
        "",
        "## Scientific decision",
        "",
        "Semantic checkpoints C1/C2/C3 (F/A/R), F2 and the material-error totals are",
        "`null` in `verdicts.json`; they are architect adjudication after the raw freeze.",
        "",
        "scientific_decision = null (architect adjudication pending)",
        "",
    ]
    return "\n".join(lines)

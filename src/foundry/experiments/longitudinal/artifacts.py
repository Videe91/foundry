"""Immutable artifact schema for the 9P longitudinal dogfood (plan Task 16; spec §31, §32).

The experiment directory holds exactly two kinds of file:

* **pre-run** (``PRE_RUN_FILES``) — ``manifest.json`` (experiment config, frozen code
  sha, timeline hashes, prompt sha, ceilings, model/effort/provider, policy version and
  the sealed expectations hash) and ``expectations.json`` (E1–E12, the tracked loci and
  the ``t1_locus_designation`` slot, ``null`` until filled). Both are written before the
  first live call and committed (plan Task 18).
* **post-run** (``POST_RUN_FILES``) — both arms' results and ledgers, every
  authorization with the verbatim proposal, the verdict table (deterministic verdicts
  filled, architect verdicts ``null``) and ``report.md``.

Discipline, as in 9O: canonical JSON (sorted keys), atomic writes, and a refusal to
overwrite — ``write_pre_run_artifacts`` / ``write_post_run_artifacts`` check every target
before writing any, so a recorded run is never partially replaced. ``expectations.json``
is the one file updated after it is sealed: ``fill_t1_designation`` fills its designation
slot exactly once; ``seal`` excludes that slot, so the sealed hash is unchanged by it.

Sealing. The sealed expectations hash is ``expectations.seal(...)`` — the sha256 of the
canonical (compact, sorted) JSON of the parsed ``ExpectationManifest`` **minus** the
``t1_locus_designation`` slot. It is therefore *not* the sha256 of the file bytes (which
are indented) nor of the whole document (which carries the slot). At run time the script
re-parses ``expectations.json`` and re-seals it; the ``manifest_hash_frozen`` gate
compares that to ``manifest.json["expectations_sha256"]``.

Designation slot timing (ruling R16-a). Plan Task 16 requires the slot to be filled
"after T1 and before T2 during the live run" — a preregistration property of the *file*.
``run_arm_f`` therefore takes an ``on_t1_designations`` hook, invoked inside T1 after the
A/B/CONTROL designations and the chains are recorded and before any T2 ingest; the entry
point passes a hook that calls ``fill_t1_designation`` live. The slot holds exactly the
three T1 designations (A, B, CONTROL). Track C is designated after T3 and is **not**
written to ``expectations.json``; it stays in ``persistent/result.json`` via
``ArmFResult.designations`` with its own ``ledger_sequence_at_designation``. Every
designation record's ledger sequence precedes the first T2 (or, for C, T4)
``EVIDENCE_INGESTED`` event in ``persistent/ledger.json``.

Secrets. No function here reads the API key. Every artifact text is scanned for a
secret-shaped token (``xai-…``) before it is written and any occurrence is redacted, so
a preserved failure never carries one; the entry point additionally never prints the key.

Nothing here originates a semantic conclusion, constructs a reasoner, or calls a model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from foundry.adapters.semantics.xai_reasoner import (
    DEFAULT_MODEL,
    POLICY_VERSION,
    PROVIDER,
    SYSTEM_INSTRUCTION,
)
from foundry.application.assimilation_context import (
    ASSIMILATION_JUDGMENT_KINDS,
    CLAIM_ASSIMILATION_JUDGMENT_KINDS,
)
from foundry.application.incremental_assimilation import CALLS_PER_DELTA
from foundry.domain.common import FrozenModel
from foundry.domain.events import EventType, SemanticJudgmentPayload, StoredEvent
from foundry.experiments.longitudinal.arm_f import (
    MAX_F_CALLS,
    PROJECT_ID,
    ArmFResult,
    StepRecord,
)
from foundry.experiments.longitudinal.arm_r import MAX_R_CALLS, ArmRStep, project_id_for
from foundry.experiments.longitudinal.authority import (
    AuthorizationBudget,
    AuthorizationDecision,
    AuthorizationRecord,
)
from foundry.experiments.longitudinal.derivations import RootDesignation
from foundry.experiments.longitudinal.expectations import (
    EXPECTATIONS,
    EXPERIMENT_VERSION,
    LOCKED_CEILINGS,
    TRACKED_LOCI,
    ExpectationManifest,
    ExpectationVerdict,
    seal,
)
from foundry.experiments.longitudinal.integrity import RunConfig
from foundry.experiments.longitudinal.scoring import StructuralMetrics
from foundry.experiments.longitudinal.timeline import TIMELINE

__all__ = [
    "ASSIMILATION_SCOPE",
    "EXPERIMENT_DIR_NAME",
    "POST_RUN_FILES",
    "PRE_RUN_FILES",
    "READINESS_SCOPES",
    "T1_TRACKS",
    "TIMELINE_PROJECT_ID",
    "AuthorizationArtifact",
    "LongitudinalRun",
    "RunStatus",
    "assemble_run",
    "build_expectation_manifest",
    "build_expectations_document",
    "build_pre_run_manifest",
    "default_run_config",
    "expectation_config",
    "fill_t1_designation",
    "contains_secret_shape",
    "redact_secrets",
    "render_report",
    "system_instruction_sha256",
    "write_post_run_artifacts",
    "write_pre_run_artifacts",
]

EXPERIMENT_DIR_NAME: Final[str] = "2026-09-11-incremental-semantic-assimilation-longitudinal"
"""Under ``docs/superpowers/experiments/``; never the 9O directory."""

PRE_RUN_FILES: Final[tuple[str, ...]] = ("manifest.json", "expectations.json")

_STEPS: Final[tuple[int, ...]] = tuple(step.t for step in TIMELINE)

POST_RUN_FILES: Final[tuple[str, ...]] = (
    "persistent/result.json",
    "persistent/ledger.json",
    *(
        name
        for t in _STEPS
        for name in (f"reconstruction/T{t}-result.json", f"reconstruction/T{t}-ledger.json")
    ),
    "authorizations.json",
    "verdicts.json",
    "report.md",
)

ASSIMILATION_SCOPE: Final[str] = "intent-engine"
"""The scope handed to ``assimilate_delta`` in both arms (which addresses Call 1 shows)."""

READINESS_SCOPES: Final[tuple[str, ...]] = ("intent-engine", "constitution")
"""Scopes whose readiness Arm F reports per T (spec §24: affected and unaffected)."""

TIMELINE_PROJECT_ID: Final[str] = "PROJ-9P-TIMELINE"
"""Project id the timeline is loaded under; each arm re-projects to its own ledger."""

_SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(r"\bxai-[A-Za-z0-9_\-]{6,}")
"""Shape of an xAI API key. Checked without ever reading the key itself."""

type RunStatus = Literal["COMPLETED", "FAILED", "REPLAY_MISMATCH"]


# --------------------------------------------------------------------------- pre-run


def system_instruction_sha256() -> str:
    """The digest of the system instruction bytes actually in the adapter, recomputed."""
    return hashlib.sha256(SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest()


def default_run_config() -> RunConfig:
    """The preregistered run configuration: locked ceilings, one provider, one model."""
    return RunConfig(
        max_frontier_calls=int(LOCKED_CEILINGS["max_frontier_calls"]),
        max_cost_usd=float(LOCKED_CEILINGS["max_cost_usd"]),
        max_human_authorizations=int(LOCKED_CEILINGS["max_human_authorizations"]),
        max_judge_calls=int(LOCKED_CEILINGS["max_judge_calls"]),
        provider=PROVIDER,
        model=DEFAULT_MODEL,
        reasoning_effort="high",
    )


def expectation_config(config: RunConfig) -> dict[str, Any]:
    """The ``ExpectationManifest.config`` mapping for ``config``; validated against the ceilings."""
    return {
        "max_frontier_calls": config.max_frontier_calls,
        "max_judge_calls": config.max_judge_calls,
        "max_human_authorizations": config.max_human_authorizations,
        "per_track_authorizations": AuthorizationBudget().per_track,
        "max_cost_usd": config.max_cost_usd,
        "provider": config.provider,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "policy_version": POLICY_VERSION,
    }


def build_expectation_manifest(
    *,
    frozen_code_sha: str,
    timeline_hashes: tuple[dict[str, str], ...],
    prompt_sha: str,
    config: RunConfig,
) -> ExpectationManifest:
    """The sealed expectation manifest (E1–E12, tracked loci, empty designation slot)."""
    return ExpectationManifest(
        experiment_version=EXPERIMENT_VERSION,
        frozen_code_sha=frozen_code_sha,
        timeline_hashes=timeline_hashes,
        prompt_sha256=prompt_sha,
        config=expectation_config(config),
        expectations=EXPECTATIONS,
        tracked_loci=TRACKED_LOCI,
        t1_locus_designation=None,
    )


def build_expectations_document(manifest: ExpectationManifest) -> dict[str, Any]:
    """``expectations.json`` as a JSON document; ``seal(manifest)`` is its sealed hash."""
    document: dict[str, Any] = manifest.model_dump(mode="json")
    return document


def build_pre_run_manifest(
    *,
    frozen_code_sha: str,
    timeline_hashes: tuple[dict[str, str], ...],
    prompt_sha: str,
    config: RunConfig,
    expectations_sha: str,
    scope: str,
    scopes: tuple[str, ...],
) -> dict[str, Any]:
    """``manifest.json``: everything fixed before the first live call, as a JSON document.

    Carries no tracked-locus description and no expectation text — only the sealed
    expectations hash — so the manifest can be quoted freely.
    """
    call_1 = sorted(k.value for k in ASSIMILATION_JUDGMENT_KINDS)
    call_2 = sorted(k.value for k in CLAIM_ASSIMILATION_JUDGMENT_KINDS)
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "experiment_dir": EXPERIMENT_DIR_NAME,
        "frozen_code_sha": frozen_code_sha,
        "timeline": [
            {
                "t": step.t,
                "commit": step.commit,
                "paths": [
                    {
                        "repo_path": path.repo_path,
                        "source_kind": path.source_kind.value,
                        "scope": list(path.scope),
                    }
                    for path in step.paths
                ],
            }
            for step in TIMELINE
        ],
        "timeline_hashes": [dict(entry) for entry in timeline_hashes],
        "prompt_sha256": prompt_sha,
        "policy_version": POLICY_VERSION,
        "expectations_sha256": expectations_sha,
        "expectations_seal": (
            "sha256 of the canonical compact JSON of expectations.json parsed as "
            "ExpectationManifest, excluding t1_locus_designation"
        ),
        "ceilings": dict(LOCKED_CEILINGS),
        "config": config.model_dump(mode="json"),
        "scope": scope,
        "scopes": list(scopes),
        "project_ids": {
            "timeline": TIMELINE_PROJECT_ID,
            "persistent": PROJECT_ID,
            "reconstruction": [project_id_for(t) for t in _STEPS],
        },
        "arms": {
            "F": {
                "max_calls": MAX_F_CALLS,
                "calls_per_t": CALLS_PER_DELTA,
                "input_at_t": "delta only (persistent_delta) + descriptors + neighborhood",
            },
            "R": {
                "max_calls": MAX_R_CALLS,
                "calls_per_t": CALLS_PER_DELTA,
                "input_at_t": "every evidence version <= T (reconstruction_corpus)",
            },
        },
        "prompts": {
            "system_instruction_sha256": prompt_sha,
            "policy_version": POLICY_VERSION,
            "call_1_allowed_kinds": call_1,
            "call_2_allowed_kinds": call_2,
            "retrieval": "all active in-scope address descriptors; no lexical top-K, no embeddings",
            "tools_enabled": False,
            "search_enabled": False,
            "store_messages": False,
            "retry_configuration": "grpc.enable_retries=0; no runner retries; no repair; no reroll",
        },
        "pre_run_files": list(PRE_RUN_FILES),
        "post_run_files": list(POST_RUN_FILES),
    }


# --------------------------------------------------------------------------- run bundle


class AuthorizationArtifact(FrozenModel):
    """One authorization log line with the verbatim proposal the human saw (or was withheld)."""

    t: int
    record: AuthorizationRecord
    proposal: dict[str, Any] | None
    """``model_dump`` of the pending judgment as recorded in the ledger."""


class LongitudinalRun(FrozenModel):
    """Everything the post-run artifacts are rendered from. Architect verdicts are absent."""

    experiment_version: str
    frozen_code_sha: str
    run_head_sha: str
    status: RunStatus
    failure: str | None
    f: ArmFResult | None
    r: tuple[ArmRStep, ...]
    metrics: StructuralMetrics | None
    deterministic_verdicts: tuple[ExpectationVerdict, ...]
    authorizations: tuple[AuthorizationArtifact, ...]


def _judgment_dumps(ledger: tuple[StoredEvent, ...]) -> dict[str, dict[str, Any]]:
    dumps: dict[str, dict[str, Any]] = {}
    for stored in ledger:
        payload = stored.event.payload
        if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED and isinstance(
            payload, SemanticJudgmentPayload
        ):
            dumps[payload.judgment.judgment_id] = payload.judgment.model_dump(mode="json")
    return dumps


def _authorizations(f: ArmFResult | None) -> tuple[AuthorizationArtifact, ...]:
    if f is None:
        return ()
    judgments = _judgment_dumps(f.ledger)
    return tuple(
        AuthorizationArtifact(
            t=step.t, record=record, proposal=judgments.get(record.pending_judgment_id)
        )
        for step in f.steps
        for record in step.authorizations
    )


def _status(
    f: ArmFResult | None,
    r: tuple[ArmRStep, ...],
    metrics: StructuralMetrics | None,
    failure: str | None,
) -> RunStatus:
    if failure is not None or f is None or metrics is None:
        return "FAILED"
    if len(r) != len(f.steps):
        return "FAILED"
    statuses = [step.status for step in f.steps] + [step.status for step in r]
    if any(status != "COMPLETED" for status in statuses):
        return "FAILED"
    if not metrics.e11_replay.holds:
        return "REPLAY_MISMATCH"
    return "COMPLETED"


def assemble_run(
    *,
    frozen_code_sha: str,
    run_head_sha: str,
    f: ArmFResult | None,
    r: tuple[ArmRStep, ...],
    metrics: StructuralMetrics | None,
    verdicts: tuple[ExpectationVerdict, ...],
    failure: str | None,
) -> LongitudinalRun:
    """Bundle both arms, the metrics and the deterministic verdicts; derive the status.

    ``COMPLETED`` iff nothing raised, every T of both arms completed and the F ledger
    replays; ``REPLAY_MISMATCH`` if only the replay failed; ``FAILED`` otherwise.
    """
    return LongitudinalRun(
        experiment_version=EXPERIMENT_VERSION,
        frozen_code_sha=frozen_code_sha,
        run_head_sha=run_head_sha,
        status=_status(f, r, metrics, failure),
        failure=failure,
        f=f,
        r=r,
        metrics=metrics,
        deterministic_verdicts=verdicts,
        authorizations=_authorizations(f),
    )


# --------------------------------------------------------------------------- documents


def _ledger_document(project_id: str, ledger: tuple[StoredEvent, ...]) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "event_count": len(ledger),
        "events": [stored.model_dump(mode="json") for stored in ledger],
    }


def _declined_any(run: LongitudinalRun) -> bool:
    return any(a.record.decision is AuthorizationDecision.DECLINE for a in run.authorizations)


def _verdicts_document(run: LongitudinalRun) -> dict[str, Any]:
    by_id = {v.id: v for v in run.deterministic_verdicts}
    return {
        "experiment_version": run.experiment_version,
        "frozen_code_sha": run.frozen_code_sha,
        "run_head_sha": run.run_head_sha,
        "run_status": run.status,
        "declined_any": _declined_any(run),
        "verdicts": [
            {
                "id": e.id,
                "adjudicator": e.adjudicator,
                "conditional": e.conditional,
                "verdict": (
                    by_id[e.id].model_dump(mode="json")
                    if e.id in by_id and e.adjudicator == "deterministic"
                    else None
                ),
            }
            for e in EXPECTATIONS
        ],
        "decision": None,
        "decision_note": (
            "decision_rule is evaluated only after the architect adjudicates E1-E9 and the "
            "E10 duplicate-address half; null until then"
        ),
    }


def _authorizations_document(run: LongitudinalRun) -> dict[str, Any]:
    budget = AuthorizationBudget()
    return {
        "budget": {"per_track": budget.per_track, "total": budget.total},
        "answered": sum(1 for a in run.authorizations if a.record.decision is not None),
        "records": [a.model_dump(mode="json") for a in run.authorizations],
    }


def _post_run_documents(run: LongitudinalRun) -> dict[str, str]:
    f_result = run.f.model_dump(mode="json", exclude={"ledger"}) if run.f is not None else None
    f_ledger = run.f.ledger if run.f is not None else ()
    r_by_t = {step.t: step for step in run.r}
    documents: dict[str, str] = {
        "persistent/result.json": _canonical(
            {"arm": "F", "project_id": PROJECT_ID, "run_status": run.status, "result": f_result}
        ),
        "persistent/ledger.json": _canonical(_ledger_document(PROJECT_ID, f_ledger)),
    }
    for t in _STEPS:
        step = r_by_t.get(t)
        documents[f"reconstruction/T{t}-result.json"] = _canonical(
            {
                "arm": "R",
                "project_id": project_id_for(t),
                "run_status": run.status,
                "result": step.model_dump(mode="json", exclude={"ledger"}) if step else None,
            }
        )
        documents[f"reconstruction/T{t}-ledger.json"] = _canonical(
            _ledger_document(project_id_for(t), step.ledger if step else ())
        )
    documents["authorizations.json"] = _canonical(_authorizations_document(run))
    documents["verdicts.json"] = _canonical(_verdicts_document(run))
    documents["report.md"] = render_report(run)
    return documents


# --------------------------------------------------------------------------- writing


def _refuse_existing(out_dir: Path, names: tuple[str, ...]) -> None:
    for name in names:
        if (out_dir / name).exists():
            raise FileExistsError(f"refusing to overwrite recorded run artifact: {out_dir / name}")


def redact_secrets(text: str) -> str:
    """Replace any secret-shaped token (9O's ``_safe`` shape, without reading the key).

    A failure must still be preserved as an artifact (spec §32), so a provider error
    that echoes a key is redacted rather than refused. The entry point passes every
    console line through this too. No timeline evidence contains such a token
    (``contains_secret_shape`` is checked at seal time), so nothing legitimate is touched.
    """
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def contains_secret_shape(text: str) -> bool:
    """True iff ``text`` carries a token shaped like an xAI API key."""
    return _SECRET_PATTERN.search(text) is not None


_redacted = redact_secrets


def _write_all(out_dir: Path, documents: Mapping[str, str]) -> None:
    safe = {name: _redacted(text) for name, text in documents.items()}
    _refuse_existing(out_dir, tuple(safe))
    for name, text in safe.items():
        path = out_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, text)


def write_pre_run_artifacts(
    out_dir: Path, manifest: Mapping[str, Any], expectations: Mapping[str, Any]
) -> None:
    """Write ``manifest.json`` and ``expectations.json``. Refuses if either exists."""
    _write_all(
        out_dir,
        {"manifest.json": _canonical(manifest), "expectations.json": _canonical(expectations)},
    )


def write_post_run_artifacts(out_dir: Path, run: LongitudinalRun) -> None:
    """Write every ``POST_RUN_FILES`` entry atomically. Refuses (writing nothing) if any exists."""
    _write_all(out_dir, _post_run_documents(run))


T1_TRACKS: Final[tuple[str, ...]] = ("A", "B", "CONTROL")
"""The designations the slot may hold (ruling R16-a): the T1 three, never Track C."""


def fill_t1_designation(out_dir: Path, designations: tuple[RootDesignation, ...]) -> None:
    """Fill ``expectations.json``'s designation slot once with the T1 designations.

    Called live from ``run_arm_f``'s ``on_t1_designations`` hook — after T1, before T2
    (ruling R16-a). Refuses (``ValueError``) if the slot is already filled, if
    ``designations`` is empty, or if any designation is not one of ``T1_TRACKS`` (Track
    C is recorded in ``persistent/result.json`` only); the file is untouched in every
    refusal. The seal is unchanged by the fill (``seal`` excludes the slot) and is
    re-checked here.
    """
    if not designations:
        raise ValueError("no designations to record; the slot stays null")
    foreign = [d.track for d in designations if d.track not in T1_TRACKS]
    if foreign:
        raise ValueError(f"the slot holds T1 designations only ({T1_TRACKS}); refused {foreign}")
    path = out_dir / "expectations.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("t1_locus_designation") is not None:
        raise ValueError(f"designation slot already filled in {path}")
    before = seal(ExpectationManifest.model_validate(document))
    document["t1_locus_designation"] = {
        "filled_from": "ArmFResult.designations",
        "filled_at": _latest(designations).isoformat(),
        "note": (
            "written live after T1 and before T2 from run_arm_f's on_t1_designations hook; "
            "each ledger_sequence_at_designation precedes the first T2 EVIDENCE_INGESTED "
            "sequence in persistent/ledger.json. Holds A, B and CONTROL only; the Track C "
            "designation (after T3) is recorded in persistent/result.json under "
            "designations with its own ledger sequence and is never written here"
        ),
        "designations": [d.model_dump(mode="json") for d in designations],
    }
    after = seal(ExpectationManifest.model_validate(document))
    if after != before:
        raise ValueError("filling the designation slot changed the seal; refusing")
    _write_atomic(path, _redacted(_canonical(document)))


def _latest(designations: tuple[RootDesignation, ...]) -> datetime:
    return max(d.designated_at for d in designations)


# --------------------------------------------------------------------------- report


def _row(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


def _economics_rows(run: LongitudinalRun) -> list[str]:
    rows: list[str] = []
    arms: tuple[tuple[str, tuple[StepRecord | ArmRStep, ...]], ...] = (
        ("F", run.f.steps if run.f is not None else ()),
        ("R", run.r),
    )
    for arm, steps in arms:
        for step in steps:
            receipts = step.receipts
            rows.append(
                _row(
                    (
                        arm,
                        f"T{step.t}",
                        step.status,
                        str(len(step.allowed_kinds_per_call)),
                        str(sum(r.input_tokens for r in receipts)),
                        str(sum(r.output_tokens for r in receipts)),
                        f"{sum(r.cost_usd for r in receipts):.6f}",
                        f"`{step.error}`" if step.error else "-",
                    )
                )
            )
    return rows


def _readiness_rows(run: LongitudinalRun) -> list[str]:
    rows: list[str] = []
    if run.f is None:
        return rows
    for step in run.f.steps:
        for scope, readiness in sorted(step.readiness_by_scope.items()):
            rows.append(
                _row(
                    (
                        f"T{step.t}",
                        scope,
                        str(readiness.ready),
                        str(readiness.closure.closed),
                        str(readiness.semantic_blockers_clear),
                        str(len(readiness.stale_object_ids)),
                        str(len(readiness.pending_material_judgment_ids)),
                        str(len(readiness.disputed_locus_ids)),
                        str(len(readiness.open_locus_ids)),
                    )
                )
            )
    return rows


def render_report(run: LongitudinalRun) -> str:
    """Forensic markdown: statuses, calls/cost per arm per T, readiness per scope, verdicts."""
    by_id = {v.id: v for v in run.deterministic_verdicts}
    lines: list[str] = [
        "# Intent Intelligence v2 — Incremental Semantic Assimilation (Longitudinal Dogfood)",
        "",
        f"- experiment_version: `{run.experiment_version}`",
        f"- frozen_code_sha: `{run.frozen_code_sha}` · run_head_sha: `{run.run_head_sha}`",
        f"- run_status: **{run.status}**",
        f"- failure: `{run.failure}`" if run.failure else "- failure: none",
        "",
        "## Calls per arm per T",
        "",
        _row(("arm", "T", "status", "calls", "in tok", "out tok", "cost USD", "error")),
        "|---|---|---|---|---|---|---|---|",
        *_economics_rows(run),
    ]
    if run.metrics is not None:
        econ = run.metrics.economics
        c = run.metrics.call_counts
        lines += [
            "",
            f"- calls: F={c.f_total} R={c.r_total} total={c.total}"
            f" (ceiling {LOCKED_CEILINGS['max_frontier_calls']})",
            f"- input tokens after T1: F={econ.f.input_tokens_after_t1}"
            f" R={econ.r.input_tokens_after_t1}",
            f"- total cost: {econ.total_cost_usd:.6f} USD (ceiling {econ.max_cost_usd:.2f})"
            f" · within_ceiling={econ.within_ceiling}",
            f"- persistent_unchanged_reread_count: {run.metrics.persistent_unchanged_reread_count}",
            f"- replay: state={run.metrics.e11_replay.replay.state_matches}"
            f" view={run.metrics.e11_replay.replay.view_matches}",
        ]
    lines += [
        "",
        "## Readiness per scope per T (Arm F)",
        "",
        _row(
            (
                "T",
                "scope",
                "ready",
                "closure_closed",
                "semantic_blockers_clear",
                "stale",
                "pending material",
                "disputed",
                "open",
            )
        ),
        "|---|---|---|---|---|---|---|---|---|",
        *_readiness_rows(run),
        "",
        "## Authorizations",
        "",
        _row(("T", "track", "pending judgment", "decision", "not offered", "submitted")),
        "|---|---|---|---|---|---|",
    ]
    for a in run.authorizations:
        r = a.record
        lines.append(
            _row(
                (
                    f"T{a.t}",
                    r.track or "-",
                    f"`{r.pending_judgment_id}`",
                    r.decision.value if r.decision else "-",
                    r.not_offered.value if r.not_offered else "-",
                    f"`{r.submitted_judgment_id}`" if r.submitted_judgment_id else "-",
                )
            )
        )
    lines += [
        "",
        "## Verdicts",
        "",
        "Architect-adjudicated expectations are `null` until adjudicated in a separate commit.",
        "",
        _row(("id", "adjudicator", "verdict", "note")),
        "|---|---|---|---|",
    ]
    for e in EXPECTATIONS:
        verdict = by_id.get(e.id) if e.adjudicator == "deterministic" else None
        lines.append(
            _row(
                (
                    e.id,
                    e.adjudicator,
                    verdict.verdict.value if verdict else "null",
                    verdict.note if verdict else "-",
                )
            )
        )
    lines += ["", "_Forensic record only. Semantic quality is not assessed here._", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- helpers


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".9p-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise

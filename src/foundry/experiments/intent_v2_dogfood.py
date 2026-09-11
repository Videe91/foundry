"""Task 9O: first live Intent Intelligence v2 dogfood — Foundry analysing Foundry.

This is NOT a product CLI and NOT a benchmark. It drives exactly three bounded
reasoning calls over five evidence files frozen by Git commit, through the real
``SemanticGovernor``, and records everything needed to replay the run without a
model. The hard call budget is ``MAX_EXTERNAL_MODEL_CALLS``; the runner never loops,
retries, repairs, re-prompts, or asks for a second lens.

Discipline enforced here rather than trusted:

* Evidence is read from a specific commit (``git show <sha>:<path>``), never from the
  working tree, and each item's Git blob SHA and content SHA-256 are recorded.
* The top-level scope is fixed by the harness, never chosen by the model.
* Each stage states its ``allowed_judgment_kinds`` explicitly.
* Any failure after the first live call is preserved as a FAILED artifact; the run is
  never resumed or repaired. Zero addresses from call 1 is a legitimate terminal
  result (``NO_ADDRESSES_PROPOSED``).
* After the calls, the recorded ledger is replayed into a fresh store and compared to
  the live state and view (``REPLAY_MATCH`` / ``REPLAY_MISMATCH``), with zero calls.
* Deterministic structural checks are emitted; no semantic-quality judgement is made.
* No credential ever reaches an artifact or an error string.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, Protocol

from pydantic import Field

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import (
    DEFAULT_MODEL,
    POLICY_VERSION,
    SemanticReasoningReceipt,
)
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionDecision, AdmissionPolicy
from foundry.domain.common import Authority, FrozenModel, SourceKind
from foundry.domain.events import StoredEvent, parse_event
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    ConflictsWithProposal,
    DistinctProposal,
    EquivalentProposal,
    JudgmentKind,
)
from foundry.domain.semantic_view import active_judgment_ids, derive_view
from foundry.domain.state import IntentState
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

EXPERIMENT_VERSION: Final[str] = "intent-v2-foundry-self-dogfood-v1"
PROJECT_ID: Final[str] = "PROJ-9O-FOUNDRY-SELF"
SCOPE: Final[tuple[str, ...]] = ("intent-engine",)
MAX_EXTERNAL_MODEL_CALLS: Final[int] = 3
API_KEY_ENV: Final[str] = "XAI_API_KEY"

EVIDENCE_SOURCES: Final[tuple[tuple[str, SourceKind], ...]] = (
    ("FOUNDRY_CONSTITUTION.md", SourceKind.DOCUMENT),
    ("docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md", SourceKind.DOCUMENT),
    ("src/foundry/application/semantic_governance.py", SourceKind.CODE),
    ("src/foundry/domain/semantic_view.py", SourceKind.CODE),
    ("tests/integration/test_semantic_lifecycle.py", SourceKind.TEST),
)

MATERIAL_KINDS: Final[frozenset[JudgmentKind]] = frozenset(
    {JudgmentKind.EQUIVALENT, JudgmentKind.CONFLICTS_WITH, JudgmentKind.SUPERSEDE}
)
RELATION_KINDS: Final[tuple[JudgmentKind, ...]] = (
    JudgmentKind.EQUIVALENT,
    JudgmentKind.DISTINCT,
    JudgmentKind.CONFLICTS_WITH,
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(?:api[_-]?key|authorization|bearer|xai[_-]?api[_-]?key)\b[^,;)\]}\"']*"),
    re.compile(r"(?i)\bxai-[A-Za-z0-9_\-]{6,}"),
)

StageStatus = Literal["COMPLETED", "FAILED", "NOT_RUN", "NO_ADDRESSES_PROPOSED"]
RunStatus = Literal["COMPLETED", "FAILED", "NO_ADDRESSES_PROPOSED", "REPLAY_MISMATCH"]


# --------------------------------------------------------------------------- stages


class Stage(FrozenModel):
    name: str
    allowed_kinds: frozenset[JudgmentKind]


STAGES: Final[tuple[Stage, Stage, Stage]] = (
    Stage(name="discovery", allowed_kinds=frozenset({JudgmentKind.CREATE_ADDRESS})),
    Stage(name="claims", allowed_kinds=frozenset({JudgmentKind.ASSERT_CLAIM})),
    Stage(name="reconciliation", allowed_kinds=frozenset(RELATION_KINDS)),
)


# --------------------------------------------------------------------------- frozen evidence


class GitReader(Protocol):
    def blob(self, sha: str, path: str) -> bytes: ...

    def blob_sha(self, sha: str, path: str) -> str: ...


class FrozenEvidence(FrozenModel):
    repo_path: str
    source_kind: SourceKind
    scope: tuple[str, ...]
    git_blob_sha: str
    content_sha256: str
    item: EvidenceItem


def load_frozen_evidence(
    reader: GitReader, frozen_sha: str, *, observed_at: datetime
) -> tuple[FrozenEvidence, ...]:
    """Read the five evidence files from ``frozen_sha`` only; never the working tree."""
    frozen: list[FrozenEvidence] = []
    for index, (path, kind) in enumerate(EVIDENCE_SOURCES, start=1):
        raw = reader.blob(frozen_sha, path)
        content = raw.decode("utf-8")
        item = evidence_item(
            evidence_id=f"EV-{index:02d}",
            project_id=PROJECT_ID,
            source_kind=kind,
            source_ref=f"git://{frozen_sha}/{path}",
            content=content,
            observed_at=observed_at,
            scope=SCOPE,
        )
        frozen.append(
            FrozenEvidence(
                repo_path=path,
                source_kind=kind,
                scope=SCOPE,
                git_blob_sha=reader.blob_sha(frozen_sha, path),
                content_sha256=hashlib.sha256(raw).hexdigest(),
                item=item,
            )
        )
    return tuple(frozen)


# --------------------------------------------------------------------------- results


class AdmissionRecord(FrozenModel):
    judgment_id: str
    kind: JudgmentKind
    route: AdmissionRoute
    reasons: tuple[str, ...]
    corroborating_judgment_ids: tuple[str, ...] = ()


class StageResult(FrozenModel):
    stage: str
    status: StageStatus
    allowed_kinds: tuple[str, ...]
    invocation_id: str | None = None
    structured_model_draft_output: Any = None
    judgment_ids: tuple[str, ...] = ()
    admissions: tuple[AdmissionRecord, ...] = ()
    addresses_created: tuple[str, ...] = ()
    claims_created: tuple[str, ...] = ()
    relation_proposals: dict[str, int] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    wall_clock_ms: int = 0
    error: str | None = None


class LocusSummary(FrozenModel):
    representative_id: str
    address_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    epistemic_state: str


class SemanticOutcome(FrozenModel):
    address_count: int
    claim_count: int
    equivalent_proposal_count: int
    distinct_proposal_count: int
    conflicts_with_proposal_count: int
    route_counts: dict[str, int]
    address_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    loci: tuple[LocusSummary, ...]
    equivalence_proposal_ids: tuple[str, ...]
    conflict_proposal_ids: tuple[str, ...]
    admission_decisions: tuple[AdmissionRecord, ...]
    pending_second_lens_judgment_ids: tuple[str, ...]
    require_human_judgment_ids: tuple[str, ...]
    rejected_judgment_ids: tuple[str, ...]
    stale_ids: tuple[str, ...]


class ReplayResult(FrozenModel):
    status: Literal["REPLAY_MATCH", "REPLAY_MISMATCH"]
    event_count: int
    state_matches: bool
    view_matches: bool


class StructuralCheck(FrozenModel):
    name: str
    passed: bool
    detail: str


class DogfoodResult(FrozenModel):
    experiment_version: str
    project_id: str
    frozen_code_sha: str
    run_status: RunStatus
    stages: tuple[StageResult, StageResult, StageResult]
    actual_external_call_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    total_wall_clock_ms: int
    semantic_outcome: SemanticOutcome
    replay: ReplayResult
    structural_checks: tuple[StructuralCheck, ...]


class DogfoodManifest(FrozenModel):
    experiment_version: str
    project_id: str
    frozen_code_sha: str
    branch: str
    model: str
    reasoning_effort: str
    policy_version: str
    store_messages: bool
    tools_enabled: bool
    search_enabled: bool
    retry_configuration: str
    max_external_calls: int
    scope: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]
    allowed_kinds: dict[str, tuple[str, ...]]


class DogfoodRun(FrozenModel):
    manifest: DogfoodManifest
    result: DogfoodResult
    ledger: tuple[StoredEvent, ...]


# --------------------------------------------------------------------------- the run


def run_dogfood(
    *,
    reasoner: SemanticReasoner,
    evidence: tuple[FrozenEvidence, ...],
    policy: AdmissionPolicy,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    frozen_sha: str,
    branch: str,
) -> DogfoodRun:
    """Three bounded calls, normal governance, then replay and structural checks."""
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store, project_id=PROJECT_ID, policy=policy, clock=clock, id_factory=id_factory
    )
    items = tuple(f.item for f in evidence)
    for item in items:
        governor.ingest(item)

    stages: list[StageResult] = []
    snapshots: list[tuple[frozenset[str], frozenset[str]]] = [_id_sets(governor.state())]
    calls = 0
    run_status: RunStatus = "COMPLETED"

    for stage in STAGES:
        if run_status != "COMPLETED":
            stages.append(_not_run(stage))
            continue
        if calls >= MAX_EXTERNAL_MODEL_CALLS:  # pragma: no cover - structurally unreachable
            raise RuntimeError("external model call budget exhausted")
        before = governor.state()
        request = _request_for(stage, items, before)
        calls += 1
        try:
            decisions = governor.propose_and_submit(reasoner, request)
        except Exception as exc:  # noqa: BLE001 - every failure is preserved, never retried
            stages.append(
                _failed(
                    stage, _receipt_at(reasoner, calls - 1), _draft_at(reasoner, calls - 1), exc
                )
            )
            run_status = "FAILED"
            continue
        after = governor.state()
        stage_result = _completed(
            stage,
            decisions,
            before,
            after,
            _receipt_at(reasoner, calls - 1),
            _draft_at(reasoner, calls - 1),
        )
        if stage.name == "discovery" and not stage_result.addresses_created:
            stage_result = stage_result.model_copy(update={"status": "NO_ADDRESSES_PROPOSED"})
            run_status = "NO_ADDRESSES_PROPOSED"
        stages.append(stage_result)
        snapshots.append(_id_sets(after))

    final_state = governor.state()
    ledger = tuple(store.load(PROJECT_ID))
    replay_result = _replay_check(ledger, final_state)
    if replay_result.status == "REPLAY_MISMATCH":
        run_status = "REPLAY_MISMATCH"

    outcome = _semantic_outcome(final_state)
    stage_triple = (stages[0], stages[1], stages[2])
    checks = _structural_checks(final_state, items, snapshots, stage_triple, replay_result, calls)
    receipts = _receipts(reasoner)

    manifest = DogfoodManifest(
        experiment_version=EXPERIMENT_VERSION,
        project_id=PROJECT_ID,
        frozen_code_sha=frozen_sha,
        branch=branch,
        model=DEFAULT_MODEL,
        reasoning_effort="high",
        policy_version=POLICY_VERSION,
        store_messages=False,
        tools_enabled=False,
        search_enabled=False,
        retry_configuration="grpc.enable_retries=0; no runner retries; no repair; no reroll",
        max_external_calls=MAX_EXTERNAL_MODEL_CALLS,
        scope=SCOPE,
        evidence=tuple(
            {
                "evidence_id": f.item.evidence_id,
                "repo_path": f.repo_path,
                "source_kind": f.source_kind.value,
                "scope": list(f.scope),
                "git_blob_sha": f.git_blob_sha,
                "content_sha256": f.content_sha256,
            }
            for f in evidence
        ),
        allowed_kinds={s.name: tuple(sorted(k.value for k in s.allowed_kinds)) for s in STAGES},
    )
    result = DogfoodResult(
        experiment_version=EXPERIMENT_VERSION,
        project_id=PROJECT_ID,
        frozen_code_sha=frozen_sha,
        run_status=run_status,
        stages=stage_triple,
        actual_external_call_count=calls,
        total_input_tokens=sum(r.input_tokens for r in receipts),
        total_output_tokens=sum(r.output_tokens for r in receipts),
        total_cost_usd=sum(r.cost_usd for r in receipts),
        total_wall_clock_ms=sum(r.wall_clock_ms for r in receipts),
        semantic_outcome=outcome,
        replay=replay_result,
        structural_checks=checks,
    )
    return DogfoodRun(manifest=manifest, result=result, ledger=ledger)


def _request_for(
    stage: Stage, items: tuple[EvidenceItem, ...], state: IntentState
) -> ReasoningRequest:
    view = derive_view(state.semantic)
    active = active_judgment_ids(state.semantic)
    addresses = tuple(state.semantic.addresses[a] for a in sorted(state.semantic.addresses))
    live_claims = tuple(
        state.semantic.claims[c]
        for c in sorted(state.semantic.claims)
        if state.semantic.claims[c].created_by_judgment_id in active
    )
    if stage.name == "discovery":
        return ReasoningRequest(
            project_id=PROJECT_ID, evidence=items, allowed_judgment_kinds=stage.allowed_kinds
        )
    if stage.name == "claims":
        return ReasoningRequest(
            project_id=PROJECT_ID,
            evidence=items,
            known_addresses=addresses,
            allowed_judgment_kinds=stage.allowed_kinds,
        )
    return ReasoningRequest(
        project_id=PROJECT_ID,
        evidence=items,
        known_addresses=addresses,
        known_claims=live_claims,
        focus_object_ids=tuple(locus.representative_id for locus in view.loci),
        allowed_judgment_kinds=stage.allowed_kinds,
    )


# --------------------------------------------------------------------------- stage results


def _not_run(stage: Stage) -> StageResult:
    return StageResult(stage=stage.name, status="NOT_RUN", allowed_kinds=_kinds(stage))


def _failed(
    stage: Stage, receipt: SemanticReasoningReceipt | None, draft: Any, exc: BaseException
) -> StageResult:
    return StageResult(
        stage=stage.name,
        status="FAILED",
        allowed_kinds=_kinds(stage),
        invocation_id=receipt.invocation_id if receipt else None,
        structured_model_draft_output=_jsonable(draft),
        error=f"{type(exc).__name__}: {_safe(str(exc))}",
        **_economics(receipt),
    )


def _completed(
    stage: Stage,
    decisions: tuple[AdmissionDecision, ...],
    before: IntentState,
    after: IntentState,
    receipt: SemanticReasoningReceipt | None,
    draft: Any,
) -> StageResult:
    judgments = after.semantic.judgments
    admissions = tuple(
        AdmissionRecord(
            judgment_id=d.judgment_id,
            kind=judgments[d.judgment_id].kind,
            route=d.route,
            reasons=d.reasons,
            corroborating_judgment_ids=d.corroborating_judgment_ids,
        )
        for d in decisions
    )
    relation_counts = Counter(a.kind.value for a in admissions if a.kind in RELATION_KINDS)
    return StageResult(
        stage=stage.name,
        status="COMPLETED",
        allowed_kinds=_kinds(stage),
        invocation_id=receipt.invocation_id if receipt else None,
        structured_model_draft_output=_jsonable(draft),
        judgment_ids=tuple(d.judgment_id for d in decisions),
        admissions=admissions,
        addresses_created=tuple(
            sorted(set(after.semantic.addresses) - set(before.semantic.addresses))
        ),
        claims_created=tuple(sorted(set(after.semantic.claims) - set(before.semantic.claims))),
        relation_proposals={k.value: relation_counts.get(k.value, 0) for k in RELATION_KINDS},
        **_economics(receipt),
    )


def _kinds(stage: Stage) -> tuple[str, ...]:
    return tuple(sorted(k.value for k in stage.allowed_kinds))


def _economics(receipt: SemanticReasoningReceipt | None) -> dict[str, Any]:
    if receipt is None:
        return {}
    return {
        "input_tokens": receipt.input_tokens,
        "output_tokens": receipt.output_tokens,
        "cost_usd": receipt.cost_usd,
        "wall_clock_ms": receipt.wall_clock_ms,
    }


def _receipts(reasoner: object) -> tuple[SemanticReasoningReceipt, ...]:
    receipts = getattr(reasoner, "receipts", ())
    return tuple(r for r in receipts if isinstance(r, SemanticReasoningReceipt))


def _receipt_at(reasoner: object, index: int) -> SemanticReasoningReceipt | None:
    receipts = _receipts(reasoner)
    return receipts[index] if index < len(receipts) else None


def _draft_at(reasoner: object, index: int) -> Any:
    drafts = getattr(reasoner, "draft_payloads", ())
    return drafts[index] if index < len(drafts) else None


# --------------------------------------------------------------------------- outcome


def _semantic_outcome(state: IntentState) -> SemanticOutcome:
    semantic = state.semantic
    view = derive_view(semantic)
    admissions = tuple(
        AdmissionRecord(
            judgment_id=jid,
            kind=semantic.judgments[jid].kind,
            route=payload.route,
            reasons=payload.reasons,
            corroborating_judgment_ids=payload.corroborating_judgment_ids,
        )
        for jid, payload in sorted(semantic.admissions.items())
    )
    by_route = Counter(a.route.value for a in admissions)
    kinds = Counter(j.kind for j in semantic.judgments.values())
    return SemanticOutcome(
        address_count=len(semantic.addresses),
        claim_count=len(semantic.claims),
        equivalent_proposal_count=kinds.get(JudgmentKind.EQUIVALENT, 0),
        distinct_proposal_count=kinds.get(JudgmentKind.DISTINCT, 0),
        conflicts_with_proposal_count=kinds.get(JudgmentKind.CONFLICTS_WITH, 0),
        route_counts={r.value: by_route.get(r.value, 0) for r in AdmissionRoute},
        address_ids=tuple(sorted(semantic.addresses)),
        claim_ids=tuple(sorted(semantic.claims)),
        loci=tuple(
            LocusSummary(
                representative_id=locus.representative_id,
                address_ids=locus.address_ids,
                claim_ids=locus.claim_ids,
                epistemic_state=locus.epistemic_state.value,
            )
            for locus in view.loci
        ),
        equivalence_proposal_ids=tuple(
            sorted(j for j, jd in semantic.judgments.items() if jd.kind is JudgmentKind.EQUIVALENT)
        ),
        conflict_proposal_ids=tuple(
            sorted(
                j for j, jd in semantic.judgments.items() if jd.kind is JudgmentKind.CONFLICTS_WITH
            )
        ),
        admission_decisions=admissions,
        pending_second_lens_judgment_ids=tuple(
            a.judgment_id for a in admissions if a.route is AdmissionRoute.REQUIRE_SECOND_LENS
        ),
        require_human_judgment_ids=tuple(
            a.judgment_id for a in admissions if a.route is AdmissionRoute.REQUIRE_HUMAN
        ),
        rejected_judgment_ids=tuple(
            a.judgment_id for a in admissions if a.route is AdmissionRoute.REJECT
        ),
        stale_ids=view.stale_ids,
    )


# --------------------------------------------------------------------------- replay


def _replay_check(ledger: tuple[StoredEvent, ...], live: IntentState) -> ReplayResult:
    """Replay the recorded events through a FRESH store and reducer. Zero model calls."""
    fresh = InMemoryEventStore()
    for stored in ledger:
        document = json.loads(json.dumps(stored.event.model_dump(mode="json")))
        fresh.append(parse_event(document), expected_sequence=fresh.current_sequence(PROJECT_ID))
    replayed = replay(PROJECT_ID, fresh.load(PROJECT_ID))
    state_matches = replayed == live
    view_matches = derive_view(replayed.semantic) == derive_view(live.semantic)
    return ReplayResult(
        status="REPLAY_MATCH" if state_matches and view_matches else "REPLAY_MISMATCH",
        event_count=len(ledger),
        state_matches=state_matches,
        view_matches=view_matches,
    )


# --------------------------------------------------------------------------- structural checks


def _id_sets(state: IntentState) -> tuple[frozenset[str], frozenset[str]]:
    return frozenset(state.semantic.addresses), frozenset(state.semantic.claims)


def _structural_checks(
    state: IntentState,
    items: tuple[EvidenceItem, ...],
    snapshots: list[tuple[frozenset[str], frozenset[str]]],
    stage_results: tuple[StageResult, StageResult, StageResult],
    replay_result: ReplayResult,
    calls: int,
) -> tuple[StructuralCheck, ...]:
    semantic = state.semantic
    ingested = {i.evidence_id for i in items}
    checks: list[StructuralCheck] = []

    bad_claims = [
        c.claim_id for c in semantic.claims.values() if not set(c.evidence_ids) <= ingested
    ]
    checks.append(
        _check("every_claim_cites_ingested_evidence", not bad_claims, f"offenders={bad_claims}")
    )

    bad_relations: list[str] = []
    for jid, judgment in semantic.judgments.items():
        p = judgment.proposal
        if isinstance(p, EquivalentProposal | DistinctProposal):
            if p.address_a not in semantic.addresses or p.address_b not in semantic.addresses:
                bad_relations.append(jid)
        elif isinstance(p, ConflictsWithProposal) and (
            p.claim_a not in semantic.claims or p.claim_b not in semantic.claims
        ):
            bad_relations.append(jid)
    checks.append(
        _check(
            "every_relation_references_known_objects",
            not bad_relations,
            f"offenders={bad_relations}",
        )
    )

    canonical_ai = [
        c.claim_id
        for c in semantic.claims.values()
        if c.authority is Authority.CANONICAL
        and not semantic.judgments[c.created_by_judgment_id].reasoner.is_human
    ]
    checks.append(
        _check("no_non_human_claim_is_canonical", not canonical_ai, f"offenders={canonical_ai}")
    )

    auto_material = [
        jid
        for jid, payload in semantic.admissions.items()
        if payload.route is AdmissionRoute.APPLY
        and semantic.judgments[jid].kind in MATERIAL_KINDS
        and not semantic.judgments[jid].reasoner.is_human
    ]
    checks.append(
        _check("no_material_kind_auto_applied", not auto_material, f"offenders={auto_material}")
    )

    same_model = [
        jid
        for jid, payload in semantic.admissions.items()
        for other in payload.corroborating_judgment_ids
        if semantic.judgments[other].reasoner == semantic.judgments[jid].reasoner
    ]
    checks.append(_check("no_same_model_corroboration", not same_model, f"offenders={same_model}"))

    monotonic = all(
        earlier[0] <= later[0] and earlier[1] <= later[1]
        for earlier, later in zip(snapshots, snapshots[1:], strict=False)
    )
    checks.append(_check("no_address_or_claim_deleted", monotonic, f"snapshots={len(snapshots)}"))

    forbidden = [
        (a.judgment_id, a.kind.value)
        for stage_result, stage in zip(stage_results, STAGES, strict=True)
        for a in stage_result.admissions
        if a.kind not in stage.allowed_kinds
    ]
    checks.append(
        _check(
            "every_judgment_kind_was_allowed_for_its_stage",
            not forbidden,
            f"offenders={forbidden}",
        )
    )

    checks.append(
        _check(
            "replay_reproduced_state",
            replay_result.status == "REPLAY_MATCH",
            f"state={replay_result.state_matches} view={replay_result.view_matches}",
        )
    )
    checks.append(
        _check(
            "external_calls_within_budget",
            calls <= MAX_EXTERNAL_MODEL_CALLS,
            f"calls={calls} budget={MAX_EXTERNAL_MODEL_CALLS}",
        )
    )
    return tuple(checks)


def _check(name: str, passed: bool, detail: str) -> StructuralCheck:
    return StructuralCheck(name=name, passed=passed, detail=detail)


# --------------------------------------------------------------------------- artifacts


def write_artifacts(out_dir: Path, run: DogfoodRun) -> None:
    """Write manifest/result/ledger/report atomically. Refuses to overwrite a recorded run."""
    targets = {
        "manifest.json": _canonical(run.manifest.model_dump(mode="json")),
        "result.json": _canonical(run.result.model_dump(mode="json")),
        "ledger.json": _canonical(
            {
                "project_id": PROJECT_ID,
                "event_count": len(run.ledger),
                "events": [s.model_dump(mode="json") for s in run.ledger],
            }
        ),
        "report.md": render_report(run),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in targets:
        if (out_dir / name).exists():
            raise FileExistsError(f"refusing to overwrite recorded run artifact: {out_dir / name}")
    for name, text in targets.items():
        _write_atomic(out_dir / name, text)


def render_report(run: DogfoodRun) -> str:
    m, r = run.manifest, run.result
    lines: list[str] = [
        "# Intent Intelligence v2 — First Live Dogfood (Foundry on Foundry)",
        "",
        f"- experiment_version: `{m.experiment_version}`",
        f"- project_id: `{m.project_id}`",
        f"- frozen_code_sha: `{m.frozen_code_sha}`",
        f"- model: `{m.model}` · reasoning_effort: `{m.reasoning_effort}`",
        f"- policy_version: `{m.policy_version}`",
        f"- run_status: **{r.run_status}**",
        "",
        "## Evidence (frozen by commit)",
        "",
        "| id | path | kind | blob | sha256 |",
        "|---|---|---|---|---|",
    ]
    for e in m.evidence:
        evidence_cells: tuple[str, ...] = (
            e["evidence_id"],
            f"`{e['repo_path']}`",
            e["source_kind"],
            f"`{e['git_blob_sha'][:12]}`",
            f"`{e['content_sha256'][:12]}`",
        )
        lines.append(_row(evidence_cells))
    header = (
        "stage",
        "status",
        "allowed",
        "judgments",
        "routes",
        "addresses",
        "claims",
        "in tok",
        "out tok",
        "cost USD",
        "wall s",
    )
    lines += ["", "## Calls", "", _row(header), "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in r.stages:
        routes = Counter(a.route.value for a in s.admissions)
        route_text = ", ".join(f"{k}={v}" for k, v in sorted(routes.items())) or "-"
        stage_cells: tuple[str, ...] = (
            s.stage,
            s.status,
            ", ".join(s.allowed_kinds),
            str(len(s.judgment_ids)),
            route_text,
            str(len(s.addresses_created)),
            str(len(s.claims_created)),
            str(s.input_tokens),
            str(s.output_tokens),
            f"{s.cost_usd:.6f}",
            f"{s.wall_clock_ms / 1000:.3f}",
        )
        lines.append(_row(stage_cells))
        if s.error:
            lines.append(_row(("", "error", f"`{s.error}`", "", "", "", "", "", "", "", "")))
    o = r.semantic_outcome
    route_summary = ", ".join(f"{k}={v}" for k, v in sorted(o.route_counts.items()))
    lines += [
        "",
        f"- actual_external_call_count: **{r.actual_external_call_count}**"
        f" (budget {m.max_external_calls})",
        f"- total tokens: {r.total_input_tokens} in / {r.total_output_tokens} out",
        f"- total cost: {r.total_cost_usd:.6f} USD"
        f" · total wall clock: {r.total_wall_clock_ms / 1000:.3f} s",
        "",
        "## Semantic State",
        "",
        f"- addresses: {o.address_count} · claims: {o.claim_count}",
        f"- proposals: EQUIVALENT={o.equivalent_proposal_count}"
        f" DISTINCT={o.distinct_proposal_count}"
        f" CONFLICTS_WITH={o.conflicts_with_proposal_count}",
        f"- admission routes: {route_summary}",
        f"- pending second lens: {len(o.pending_second_lens_judgment_ids)}"
        f" · require human: {len(o.require_human_judgment_ids)}"
        f" · rejected: {len(o.rejected_judgment_ids)} · stale: {len(o.stale_ids)}",
        "",
        "| locus | addresses | claims | epistemic |",
        "|---|---|---|---|",
    ]
    for locus in o.loci:
        locus_cells: tuple[str, ...] = (
            f"`{locus.representative_id}`",
            str(len(locus.address_ids)),
            str(len(locus.claim_ids)),
            locus.epistemic_state,
        )
        lines.append(_row(locus_cells))
    lines += [
        "",
        "## Replay",
        "",
        f"- status: **{r.replay.status}** · events: {r.replay.event_count}"
        f" · state={r.replay.state_matches} view={r.replay.view_matches}",
        "",
        "## Structural Checks",
        "",
        "| check | passed | detail |",
        "|---|---|---|",
    ]
    for c in r.structural_checks:
        lines.append(_row((c.name, "PASS" if c.passed else "FAIL", c.detail)))
    lines += ["", "_Forensic record only. Semantic quality is not assessed here._", ""]
    return "\n".join(lines)


def _row(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


# --------------------------------------------------------------------------- helpers


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return json.loads(json.dumps(value, default=str))


def _canonical(payload: Mapping[str, Any] | dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".9o-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _safe(message: str) -> str:
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("[REDACTED]", message)
    key = os.environ.get(API_KEY_ENV, "")
    if key:
        message = message.replace(key, "[REDACTED]")
    return message


def utc_now() -> datetime:
    return datetime.now(tz=UTC)

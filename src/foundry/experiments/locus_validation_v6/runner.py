"""Walk the six ledgers and record everything (design §9, §10).

Per ledger: a fresh governor under ``AdmissionPolicy(canonical_facets=True,
correction_sets=True)``; T1 is a model delta (every ledger but ``conflict``, whose T1 is the
seed author's deterministic world); T2 is always a model delta. Every delta is exactly two
calls through the unchanged ``assimilate_delta``, in ``ExecutionMode.EXPERIMENT``: one attempt
per semantic call, never a re-proposal.

The dense ledger then branches. Its post-T2 store is cloned once per branch; in each clone the
scripted human (``authority``) decides every PENDING correction set the production listing
shows (AGREE in one branch, DECLINE in the other), and the same T3 delta is assimilated.

A structural refusal is a measured outcome: the ledger (or branch) is recorded ``REFUSED`` and
the walk continues. Any other failure is ``FAILED`` and stops the walk. Nothing is retried.
The runner decides nothing about meaning and never imports the answer key.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.authority_routing import list_authority_work
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.authority_work import AuthorityWorkQueue
from foundry.domain.common import FrozenModel
from foundry.domain.events import StoredEvent
from foundry.domain.state import IntentState
from foundry.experiments.locus_validation_v6.authority import (
    HumanDecision,
    decide_every_pending_set,
)
from foundry.experiments.locus_validation_v6.corpus import revision_delta, seed_delta, t3_delta
from foundry.experiments.locus_validation_v6.protocol import (
    BRANCHED,
    BRANCHES,
    EXECUTION_MODE,
    LEDGERS,
    MODEL_SEEDED,
    SCOPES,
    Branch,
    LedgerId,
)
from foundry.experiments.locus_validation_v6.recording import (
    CallRecord,
    RecordingReasoner,
    RunBudget,
)
from foundry.experiments.locus_validation_v6.world import (
    clone_governor,
    fresh_governor,
    record_architect_authority,
    seed_world,
)
from foundry.experiments.longitudinal.artifacts import redact_secrets
from foundry.experiments.longitudinal.scoring import replay_matches
from foundry.ports.semantic_reasoner import ReasonerResponseRefused, SemanticReasoner

__all__ = ["BranchRun", "DeltaRun", "LedgerRun", "RunRecord", "run_validation"]


class Decision(FrozenModel):
    judgment_id: str
    route: str
    reasons: tuple[str, ...]


class DeltaRun(FrozenModel):
    t: int
    by_model: bool
    call_1: tuple[Decision, ...]
    call_2: tuple[Decision, ...]
    state_after: IntentState


class BranchRun(FrozenModel):
    """One dense branch: the scripted human's decisions, then T3."""

    branch: Branch
    status: str
    error: str | None
    work_before: AuthorityWorkQueue
    decisions: tuple[HumanDecision, ...]
    state_after_decisions: IntentState
    t3: DeltaRun | None
    events: tuple[StoredEvent, ...]
    replay_matches: bool | None


class LedgerRun(FrozenModel):
    ledger: LedgerId
    status: str
    error: str | None
    seed_address_ids: dict[str, str]
    seed_claim_ids: dict[str, str]
    deltas: tuple[DeltaRun, ...]
    calls: tuple[CallRecord, ...]
    receipts: tuple[dict[str, Any], ...]
    events: tuple[StoredEvent, ...]
    replay_matches: bool | None
    work_after_t2: AuthorityWorkQueue | None = None
    branches: tuple[BranchRun, ...] = ()


class RunRecord(FrozenModel):
    status: str
    ledgers: tuple[LedgerRun, ...]
    frontier_calls: int
    provider_cost_usd: str


def _decisions(batch: Any) -> tuple[Decision, ...]:
    return tuple(
        Decision(judgment_id=d.judgment_id, route=d.route.value, reasons=tuple(d.reasons))
        for d in batch
    )


def _delta(
    governor: SemanticGovernor,
    reasoner: RecordingReasoner,
    t: int,
    delta: Any,
    scope: str,
    branch: Branch | None = None,
) -> DeltaRun:
    reasoner.begin_delta(t, branch)
    outcome = assimilate_delta(
        governor=governor, reasoner=reasoner, delta=delta, scope=scope, mode=EXECUTION_MODE
    )
    return DeltaRun(
        t=t,
        by_model=True,
        call_1=_decisions(outcome.stage_decisions[0]),
        call_2=_decisions(outcome.stage_decisions[1]),
        state_after=governor.state(),
    )


def _replays(store: InMemoryEventStore, governor: SemanticGovernor) -> bool:
    checked = replay_matches(tuple(store.load(governor.project_id)), governor.state())
    return checked.status == "REPLAY_MATCH" and checked.state_matches and checked.view_matches


def _run_branch(
    branch: Branch,
    store: InMemoryEventStore,
    governor: SemanticGovernor,
    inner: SemanticReasoner,
    budget: RunBudget,
    *,
    guard_identity: bool,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> tuple[BranchRun, RecordingReasoner]:
    b_store, b_governor = clone_governor(
        store, governor.project_id, clock=clock, id_factory=id_factory
    )
    reasoner = RecordingReasoner(
        inner,
        ledger=BRANCHED,
        budget=budget,
        guard_identity=guard_identity,
        state=b_governor.state,
    )
    work_before = list_authority_work(b_governor)
    decisions: tuple[HumanDecision, ...] = ()
    after = b_governor.state()
    t3: DeltaRun | None = None
    status, error = "COMPLETED", None
    try:
        decisions = decide_every_pending_set(b_governor, branch)
        after = b_governor.state()
        t3 = _delta(b_governor, reasoner, 3, t3_delta(), SCOPES[BRANCHED], branch)
    except ReasonerResponseRefused as refused:
        status, error = "REFUSED", redact_secrets("; ".join(refused.findings))
    except Exception as exc:  # noqa: BLE001 - recorded; the walk stops, nothing is retried
        status, error = "FAILED", redact_secrets(f"{type(exc).__name__}: {exc}")
    return BranchRun(
        branch=branch,
        status=status,
        error=error,
        work_before=work_before,
        decisions=decisions,
        state_after_decisions=after,
        t3=t3,
        events=tuple(b_store.load(b_governor.project_id)),
        replay_matches=_replays(b_store, b_governor) if status != "FAILED" else None,
    ), reasoner


def _run_ledger(
    ledger: LedgerId,
    inner: SemanticReasoner,
    budget: RunBudget,
    *,
    guard_identity: bool,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> LedgerRun:
    store, governor = fresh_governor(ledger, clock=clock, id_factory=id_factory)
    reasoner = RecordingReasoner(
        inner, ledger=ledger, budget=budget, guard_identity=guard_identity, state=governor.state
    )
    deltas: list[DeltaRun] = []
    addresses: dict[str, str] = {}
    claims: dict[str, str] = {}
    work_after_t2: AuthorityWorkQueue | None = None
    branches: list[BranchRun] = []
    branch_reasoners: list[RecordingReasoner] = []
    status, error = "COMPLETED", None
    try:
        if ledger == BRANCHED:
            record_architect_authority(ledger, governor)
        if ledger in MODEL_SEEDED:
            deltas.append(_delta(governor, reasoner, 1, seed_delta(ledger), SCOPES[ledger]))
        else:
            world = seed_world(ledger, governor)
            addresses, claims = dict(world.address_ids), dict(world.claim_ids)
            deltas.append(
                DeltaRun(t=1, by_model=False, call_1=(), call_2=(), state_after=governor.state())
            )
        deltas.append(_delta(governor, reasoner, 2, revision_delta(ledger), SCOPES[ledger]))
        work_after_t2 = list_authority_work(governor)
        if ledger == BRANCHED:
            for branch in BRANCHES:
                run, recorded = _run_branch(
                    branch,
                    store,
                    governor,
                    inner,
                    budget,
                    guard_identity=guard_identity,
                    clock=clock,
                    id_factory=id_factory,
                )
                branches.append(run)
                branch_reasoners.append(recorded)
                if run.status == "FAILED":
                    status, error = "FAILED", run.error
                    break
    except ReasonerResponseRefused as refused:
        status, error = "REFUSED", redact_secrets("; ".join(refused.findings))
    except Exception as exc:  # noqa: BLE001 - recorded; the walk stops, nothing is retried
        status, error = "FAILED", redact_secrets(f"{type(exc).__name__}: {exc}")
    replay = _replays(store, governor) if status in ("COMPLETED", "REFUSED") else None
    return LedgerRun(
        ledger=ledger,
        status=status,
        error=error,
        seed_address_ids=addresses,
        seed_claim_ids=claims,
        deltas=tuple(deltas),
        calls=tuple(c for r in (reasoner, *branch_reasoners) for c in r.records),
        receipts=tuple(
            x.model_dump(mode="json") if hasattr(x, "model_dump") else dict(x)
            for r in (reasoner, *branch_reasoners)
            for x in r.receipts
        ),
        events=tuple(store.load(governor.project_id)),
        replay_matches=replay,
        work_after_t2=work_after_t2,
        branches=tuple(branches),
    )


def run_validation(
    *,
    inner: SemanticReasoner,
    guard_identity: bool,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> RunRecord:
    budget = RunBudget()
    runs: list[LedgerRun] = []
    status = "COMPLETED"
    for ledger in LEDGERS:
        if status != "COMPLETED":
            break
        run = _run_ledger(
            ledger, inner, budget, guard_identity=guard_identity, clock=clock, id_factory=id_factory
        )
        runs.append(run)
        replay_ok = run.replay_matches is True and all(
            b.replay_matches is True for b in run.branches
        )
        if run.status == "FAILED" or not replay_ok:
            status = "ABORTED"
    return RunRecord(
        status=status,
        ledgers=tuple(runs),
        frontier_calls=budget.frontier_calls,
        provider_cost_usd=str(budget.provider_cost_usd),
    )

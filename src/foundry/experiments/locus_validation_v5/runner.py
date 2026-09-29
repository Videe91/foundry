"""Walk the five ledgers and record everything (design §9, §10).

Per ledger: a fresh governor; T1 is either a model delta (``core``, ``orion``, ``jobs``,
``large``) or the seed author's deterministic world (``conflict``); T2 is always a model
delta. Every delta is exactly two calls through the unchanged ``assimilate_delta``, in
``ExecutionMode.EXPERIMENT``: one attempt per semantic call, never a re-proposal.

A structural refusal (``ReasonerResponseRefused``: the model's answer broke the answer
contract, e.g. proposition accounting) is a measured outcome, not an abort: the ledger is
recorded ``REFUSED`` with the refused call, and the walk continues to the next ledger so every
case is measured. Any other failure (transport, budget, identity) is ``FAILED`` and stops the
walk, as before. Nothing is retried. The runner decides nothing about meaning and never
imports the answer key.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from foundry.application.incremental_assimilation import assimilate_delta
from foundry.domain.common import FrozenModel
from foundry.domain.events import StoredEvent
from foundry.domain.state import IntentState
from foundry.experiments.locus_validation_v5.corpus import revision_delta, seed_delta
from foundry.experiments.locus_validation_v5.protocol import (
    EXECUTION_MODE,
    LEDGERS,
    MODEL_SEEDED,
    SCOPES,
    LedgerId,
)
from foundry.experiments.locus_validation_v5.recording import (
    CallRecord,
    RecordingReasoner,
    RunBudget,
)
from foundry.experiments.locus_validation_v5.world import fresh_governor, seed_world
from foundry.experiments.longitudinal.artifacts import redact_secrets
from foundry.experiments.longitudinal.scoring import replay_matches
from foundry.ports.semantic_reasoner import ReasonerResponseRefused, SemanticReasoner

__all__ = ["DeltaRun", "LedgerRun", "RunRecord", "run_validation"]


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
        inner,
        ledger=ledger,
        budget=budget,
        guard_identity=guard_identity,
        state=governor.state,
    )
    deltas: list[DeltaRun] = []
    addresses: dict[str, str] = {}
    claims: dict[str, str] = {}
    status, error = "COMPLETED", None
    try:
        if ledger in MODEL_SEEDED:
            reasoner.begin_delta(1)
            outcome = assimilate_delta(
                governor=governor,
                reasoner=reasoner,
                delta=seed_delta(ledger),
                scope=SCOPES[ledger],
                mode=EXECUTION_MODE,
            )
            deltas.append(
                DeltaRun(
                    t=1,
                    by_model=True,
                    call_1=_decisions(outcome.stage_decisions[0]),
                    call_2=_decisions(outcome.stage_decisions[1]),
                    state_after=governor.state(),
                )
            )
        else:
            world = seed_world(ledger, governor)
            addresses, claims = dict(world.address_ids), dict(world.claim_ids)
            deltas.append(
                DeltaRun(t=1, by_model=False, call_1=(), call_2=(), state_after=governor.state())
            )
        reasoner.begin_delta(2)
        outcome = assimilate_delta(
            governor=governor,
            reasoner=reasoner,
            delta=revision_delta(ledger),
            scope=SCOPES[ledger],
            mode=EXECUTION_MODE,
        )
        deltas.append(
            DeltaRun(
                t=2,
                by_model=True,
                call_1=_decisions(outcome.stage_decisions[0]),
                call_2=_decisions(outcome.stage_decisions[1]),
                state_after=governor.state(),
            )
        )
    except ReasonerResponseRefused as refused:
        # A single-attempt structural refusal: recorded, measured, never re-proposed.
        status, error = "REFUSED", redact_secrets("; ".join(refused.findings))
    except Exception as exc:  # noqa: BLE001 - recorded; the walk stops, nothing is retried
        status, error = "FAILED", redact_secrets(f"{type(exc).__name__}: {exc}")
    events = tuple(store.load(governor.project_id))
    replay: bool | None = None
    if status in ("COMPLETED", "REFUSED"):
        checked = replay_matches(events, governor.state())
        replay = checked.status == "REPLAY_MATCH" and checked.state_matches and checked.view_matches
    return LedgerRun(
        ledger=ledger,
        status=status,
        error=error,
        seed_address_ids=addresses,
        seed_claim_ids=claims,
        deltas=tuple(deltas),
        calls=tuple(reasoner.records),
        receipts=tuple(
            r.model_dump(mode="json") if hasattr(r, "model_dump") else dict(r)
            for r in reasoner.receipts
        ),
        events=events,
        replay_matches=replay,
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
            ledger,
            inner,
            budget,
            guard_identity=guard_identity,
            clock=clock,
            id_factory=id_factory,
        )
        runs.append(run)
        if run.status == "FAILED" or run.replay_matches is not True:
            status = "ABORTED"
    return RunRecord(
        status=status,
        ledgers=tuple(runs),
        frontier_calls=budget.frontier_calls,
        provider_cost_usd=str(budget.provider_cost_usd),
    )

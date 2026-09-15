"""The single-ledger runner and the two-ledger fail-fast walk.

Spec §4 (each ledger is a fresh project, fresh event store, fresh governor; nothing is
shared between ledgers except the reasoner's budget), §10 (everything after
consumption is recorded and nothing is retried), §15 (the first operational failure
stops the walk: the failing ledger keeps what it produced, the unreached ledger is
``NOT_RUN``) and §18 (the seed delta then the revision delta per ledger, two calls
each, α then β).

Law of this module: it walks a fixed schedule and records what happened. It decides
nothing about meaning and selects no outcome: every judgment is the model's, every
admission is the governor's, and every record here is a structural capture (requests,
snapshots, decisions, ledgers, state) for later evaluation by other modules. It is a
request-path module and must never import the hidden answer key or a grading module.

Failure discipline: exactly one catch site, ``_attempt``, applied once around each
delta (and around the no-call capture and replay steps, so a failure there is named,
never allowed to discard a record). ``XAIProviderError`` -> ``ABORTED_PROVIDER``;
``SemanticOutputError`` and ``ReferenceSnapshotMismatch`` -> ``ABORTED_MODEL_CONTRACT``;
``BudgetExceeded`` -> ``ABORTED_BUDGET``; ``IdentityDrift`` -> ``ABORTED_IDENTITY``;
every other ``Exception`` -> ``ABORTED_RUNTIME``. A ``KeyboardInterrupt`` is recorded the same way
(``ABORTED_RUNTIME``, ``INTERRUPTED: KeyboardInterrupt``) and, in ``run_experiment``,
re-raised only after every ledger record has been handed to ``progress`` so the caller
can persist what exists. ``SystemExit`` is never caught. Nothing is retried; no third
call, fallback or rerun exists.

Preservation: a failed delta still yields a ``DeltaRecord`` carrying whatever the
wrapper recorded for it and the ledger's state at that point (Call-1 admissions are
already appended events and survive by construction); ``ledger_events`` and the final
state/view are always captured; the replay check runs only over a ``COMPLETED`` ledger
and a failure there degrades to ``replay=None`` with the error appended, never
discarding the record. A ``NOT_RUN`` ledger is the structural fill for a ledger the
walk never reached.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from functools import partial
from typing import Any, Final, Literal

from pydantic import Field

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import SemanticOutputError, XAIProviderError
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionDecision, AdmissionPolicy
from foundry.domain.common import FrozenModel
from foundry.domain.events import StoredEvent
from foundry.domain.semantic_view import CurrentSemanticView, derive_view
from foundry.domain.state import IntentState
from foundry.experiments.contrastive_unseen.records import RequestRecord
from foundry.experiments.intent_v2_dogfood import ReplayResult
from foundry.experiments.locus_validation.corpus import (
    LEDGERS,
    PROJECT_IDS,
    SCOPES,
    Ledger,
    delta,
)
from foundry.experiments.locus_validation.protocol import DELTAS
from foundry.experiments.locus_validation.recording import (
    BudgetExceeded,
    BudgetSnapshot,
    ExperimentBudget,
    IdentityDrift,
    LocusRecordingReasoner,
)
from foundry.experiments.long_horizon_bounded.runner import (
    ReferenceSnapshotMismatch,
    RequestReferenceSnapshot,
)
from foundry.experiments.longitudinal.artifacts import redact_secrets
from foundry.experiments.longitudinal.scoring import replay_matches
from foundry.ports.semantic_reasoner import SemanticReasoner

__all__ = [
    "DeltaRecord",
    "LedgerRecord",
    "LedgerStatus",
    "RunResult",
    "RunStatus",
    "run_experiment",
    "run_ledger",
]

_INTERRUPTED: Final = "INTERRUPTED: KeyboardInterrupt"
_LEDGER_COUNT: Final[int] = len(LEDGERS)
_DELTA_COUNT: Final[int] = len(DELTAS)


# --------------------------------------------------------------------------- status


class RunStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    ABORTED_PROVIDER = "ABORTED_PROVIDER"
    ABORTED_MODEL_CONTRACT = "ABORTED_MODEL_CONTRACT"
    ABORTED_RUNTIME = "ABORTED_RUNTIME"
    ABORTED_BUDGET = "ABORTED_BUDGET"
    ABORTED_IDENTITY = "ABORTED_IDENTITY"
    COMPLETED = "COMPLETED"


LedgerStatus = Literal["COMPLETED", "FAILED", "NOT_RUN"]


# --------------------------------------------------------------------------- records


class DeltaRecord(FrozenModel):
    """One delta of one ledger: what the model was shown, what it drafted, what the
    governor admitted, and the ledger state afterwards. Raw material only."""

    t: int = Field(ge=1, le=_DELTA_COUNT)
    requests: tuple[RequestRecord, ...]
    reference_snapshots: tuple[RequestReferenceSnapshot, ...]
    """Bound 1:1, in order, to ``requests``."""
    stage_decisions: tuple[tuple[AdmissionDecision, ...], tuple[AdmissionDecision, ...]]
    """Call 1 decisions, then Call 2 decisions; ``((), ())`` for a failed delta."""
    draft_payloads: tuple[Any, ...]
    receipts: tuple[Any, ...]
    pending_supersede_judgment_ids: tuple[str, ...]
    state_snapshot: IntentState | None
    view_snapshot: CurrentSemanticView | None


class LedgerRecord(FrozenModel):
    """One ledger's walk: its deltas in order, its full event ledger, its final state
    and view, and the replay check when it completed."""

    ledger: Ledger
    project_id: str
    scope: str
    status: LedgerStatus
    error: str | None
    deltas: tuple[DeltaRecord, ...] = Field(max_length=_DELTA_COUNT)
    ledger_events: tuple[StoredEvent, ...]
    final_state: IntentState | None
    final_view: CurrentSemanticView | None
    replay: ReplayResult | None


class RunResult(FrozenModel):
    status: RunStatus
    error: str | None
    ledgers: tuple[LedgerRecord, LedgerRecord]
    """Always ``(alpha, beta)``, in ``LEDGERS`` order."""
    budget: BudgetSnapshot


# --------------------------------------------------------------------------- failure


def _attempt[T](operation: Callable[[], T]) -> T | BaseException:
    """The one catch site: run ``operation`` once and return its result, or the
    ``KeyboardInterrupt``/``Exception`` it raised, for the caller to classify and
    record. ``SystemExit`` propagates. Nothing is re-attempted here."""
    try:
        return operation()
    except KeyboardInterrupt as interrupt:
        return interrupt
    except Exception as exc:  # noqa: BLE001 - returned for classification, never swallowed
        return exc


def _classify(exc: BaseException) -> RunStatus:
    if isinstance(exc, XAIProviderError):
        return RunStatus.ABORTED_PROVIDER
    if isinstance(exc, SemanticOutputError | ReferenceSnapshotMismatch):
        return RunStatus.ABORTED_MODEL_CONTRACT
    if isinstance(exc, BudgetExceeded):
        return RunStatus.ABORTED_BUDGET
    if isinstance(exc, IdentityDrift):
        return RunStatus.ABORTED_IDENTITY
    return RunStatus.ABORTED_RUNTIME


def _failure_text(exc: BaseException) -> str:
    if isinstance(exc, KeyboardInterrupt):
        return _INTERRUPTED
    return redact_secrets(f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- one ledger


class _Marks:
    """The wrapper's cumulative tuple lengths when a delta began, so the delta's own
    records, snapshots, receipts and payloads can be sliced out afterwards."""

    def __init__(self, reasoner: LocusRecordingReasoner) -> None:
        self.records = len(reasoner.records)
        self.snapshots = len(reasoner.snapshots)
        self.receipts = len(reasoner.receipts)
        self.payloads = len(reasoner.draft_payloads)


def _capture(governor: SemanticGovernor) -> tuple[IntentState, CurrentSemanticView]:
    state = governor.state()
    return state, derive_view(state.semantic)


def _run_delta(
    governor: SemanticGovernor,
    reasoner: LocusRecordingReasoner,
    *,
    ledger: Ledger,
    t: Literal[1, 2],
    marks: _Marks,
) -> DeltaRecord:
    """Delta ``t``: begin it on the wrapper, assimilate through the real governor, then
    capture the delta's own records and the ledger state afterwards."""
    reasoner.begin_delta(t)
    outcome = assimilate_delta(
        governor=governor, reasoner=reasoner, delta=delta(ledger, t), scope=SCOPES[ledger]
    )
    state, view = _capture(governor)
    return DeltaRecord(
        t=t,
        requests=reasoner.records[marks.records :],
        reference_snapshots=reasoner.snapshots[marks.snapshots :],
        stage_decisions=outcome.stage_decisions,
        draft_payloads=reasoner.draft_payloads[marks.payloads :],
        receipts=reasoner.receipts[marks.receipts :],
        pending_supersede_judgment_ids=outcome.pending_supersede_judgment_ids,
        state_snapshot=state,
        view_snapshot=view,
    )


def _failed_delta(
    governor: SemanticGovernor,
    reasoner: LocusRecordingReasoner,
    *,
    t: Literal[1, 2],
    marks: _Marks,
) -> tuple[DeltaRecord, str | None]:
    """The record of a delta that raised: whatever the wrapper recorded for it, no
    decisions, and the ledger state as it stands. A state capture that itself fails
    leaves the snapshots ``None`` and names the failure; the record is never lost."""
    captured = _attempt(partial(_capture, governor))
    degraded: str | None = None
    if isinstance(captured, BaseException):
        state, view = None, None
        degraded = f"STATE_CAPTURE_FAILED: {_failure_text(captured)}"
    else:
        state, view = captured
    return DeltaRecord(
        t=t,
        requests=reasoner.records[marks.records :],
        reference_snapshots=reasoner.snapshots[marks.snapshots :],
        stage_decisions=((), ()),
        draft_payloads=reasoner.draft_payloads[marks.payloads :],
        receipts=reasoner.receipts[marks.receipts :],
        pending_supersede_judgment_ids=(),
        state_snapshot=state,
        view_snapshot=view,
    ), degraded


def _append_error(error: str | None, addition: str) -> str:
    return addition if error is None else f"{error}; {addition}"


def _walk_ledger(
    ledger: Ledger,
    reasoner: LocusRecordingReasoner,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> tuple[LedgerRecord, BaseException | None]:
    """Walk ``DELTAS`` over a fresh store and governor; stop at the first failure.
    Returns the record and the failing exception (``None`` when every delta ran)."""
    if reasoner.ledger != ledger:
        raise ValueError(
            f"reasoner is recorded for ledger {reasoner.ledger!r}, asked to run {ledger!r}"
        )
    project_id = PROJECT_IDS[ledger]
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store,
        project_id=project_id,
        policy=AdmissionPolicy(),
        clock=clock,
        id_factory=id_factory,
    )

    status: LedgerStatus = "COMPLETED"
    error: str | None = None
    failure: BaseException | None = None
    deltas: list[DeltaRecord] = []
    for t in DELTAS:
        marks = _Marks(reasoner)
        outcome = _attempt(partial(_run_delta, governor, reasoner, ledger=ledger, t=t, marks=marks))
        if isinstance(outcome, BaseException):
            status, failure, error = "FAILED", outcome, _failure_text(outcome)
            record, degraded = _failed_delta(governor, reasoner, t=t, marks=marks)
            if degraded is not None:
                error = _append_error(error, degraded)
            deltas.append(record)
            break
        deltas.append(outcome)

    ledger_events = tuple(store.load(project_id))
    final_state: IntentState | None = None
    final_view: CurrentSemanticView | None = None
    captured = _attempt(partial(_capture, governor))
    if isinstance(captured, BaseException):
        error = _append_error(error, f"FINAL_CAPTURE_FAILED: {_failure_text(captured)}")
    else:
        final_state, final_view = captured

    replay: ReplayResult | None = None
    if status == "COMPLETED" and final_state is not None:
        checked = _attempt(partial(replay_matches, ledger_events, final_state))
        if isinstance(checked, BaseException):
            error = _append_error(error, f"REPLAY_FAILED: {_failure_text(checked)}")
        else:
            replay = checked

    return LedgerRecord(
        ledger=ledger,
        project_id=project_id,
        scope=SCOPES[ledger],
        status=status,
        error=error,
        deltas=tuple(deltas),
        ledger_events=ledger_events,
        final_state=final_state,
        final_view=final_view,
        replay=replay,
    ), failure


def run_ledger(
    *,
    ledger: Ledger,
    reasoner: LocusRecordingReasoner,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> LedgerRecord:
    """Run one ledger — the seed delta then the revision delta over a fresh governor —
    and return its record. A failure (an interrupt included) is recorded as a
    ``FAILED`` ledger with what was produced; nothing is retried."""
    record, _failure = _walk_ledger(ledger, reasoner, clock=clock, id_factory=id_factory)
    return record


# --------------------------------------------------------------------------- the run


def _empty_record(ledger: Ledger, *, status: LedgerStatus, error: str | None) -> LedgerRecord:
    """A ledger record with no deltas, no events and no state: the structural fill for
    a ledger the walk never reached, or one whose wrapper could not be constructed."""
    return LedgerRecord(
        ledger=ledger,
        project_id=PROJECT_IDS[ledger],
        scope=SCOPES[ledger],
        status=status,
        error=error,
        deltas=(),
        ledger_events=(),
        final_state=None,
        final_view=None,
        replay=None,
    )


def _not_run(ledger: Ledger) -> LedgerRecord:
    return _empty_record(ledger, status="NOT_RUN", error=None)


def _attempt_ledger(
    ledger: Ledger,
    inner: SemanticReasoner,
    budget: ExperimentBudget,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> tuple[LedgerRecord, BaseException | None]:
    """Guard and wrap ``inner`` for ``ledger``, then walk it. A wrapper that cannot be
    constructed (identity drift before any call) is the ledger's failure."""
    wrapper = _attempt(partial(LocusRecordingReasoner, inner, ledger=ledger, budget=budget))
    if isinstance(wrapper, BaseException):
        return _empty_record(ledger, status="FAILED", error=_failure_text(wrapper)), wrapper
    return _walk_ledger(ledger, wrapper, clock=clock, id_factory=id_factory)


def run_experiment(
    *,
    inner: SemanticReasoner,
    budget: ExperimentBudget,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    progress: list[LedgerRecord] | None = None,
) -> RunResult:
    """Walk ``LEDGERS`` in order with one guarded wrapper per ledger sharing ``budget``;
    stop at the first failed ledger (every later ledger is ``NOT_RUN``); never retry.
    ``progress``, when given, receives every ledger record as it is produced — a
    ``KeyboardInterrupt`` is re-raised only after both records are there."""
    status = RunStatus.COMPLETED
    error: str | None = None
    interrupt: KeyboardInterrupt | None = None
    walk_failed = False
    records: list[LedgerRecord] = []
    for ledger in LEDGERS:
        if walk_failed:
            record = _not_run(ledger)
        else:
            record, failure = _attempt_ledger(
                ledger, inner, budget, clock=clock, id_factory=id_factory
            )
            if failure is not None:
                # The operational failure classifies the run; an earlier degradation's
                # text is kept in front of it, never discarded.
                walk_failed = True
                status = _classify(failure)
                error = _append_error(error, _failure_text(failure))
                if isinstance(failure, KeyboardInterrupt):
                    interrupt = failure
            elif record.error is not None:
                # A degradation (replay or capture) after a completed ledger makes the
                # run ABORTED_RUNTIME; a later one is appended to the first.
                if status is RunStatus.COMPLETED:
                    status, error = RunStatus.ABORTED_RUNTIME, record.error
                else:
                    error = _append_error(error, f"LEDGER_DEGRADED ({ledger}): {record.error}")
        records.append(record)
        if progress is not None:
            progress.append(record)

    if interrupt is not None:
        raise interrupt
    if len(records) != _LEDGER_COUNT:
        raise RuntimeError(f"walked {len(records)} ledgers, expected {_LEDGER_COUNT}")
    return RunResult(
        status=status,
        error=error,
        ledgers=(records[0], records[1]),
        budget=budget.snapshot(),
    )

"""Walk T1..T16 once through the real IE2 -> authority -> IE3 pipeline (design §5, §6).

One project, one event store and one governor for the whole run; nothing is reset between
turns, so T16 sees every consequence of T1..T15. Per turn:

1. **Pre-T authority snapshot** (9P3 protocol, reused unchanged): at a correction/revert
   checkpoint, the eligible target judgments at the designated address of the target locus
   are snapshotted from the state before T's evidence is ingested.
2. **IE2.** ``assimilate_delta`` with the twelve historical items of version T, in
   ``ExecutionMode.EXPERIMENT``: Call 1 (CREATE/BIND), Call 2 (claims with proposition
   accounting). One attempt each. A structural refusal of Call 2 is recorded; the turn keeps
   what Call 1 admitted, and the walk continues.
3. **Designation** (after T1 only, reused 9P3 module): each locus's address, from its T1 seed
   evidence id, structurally.
4. **Authority** (checkpoints only): an already-pending model ``SUPERSEDE`` that targets an
   eligible judgment is relayed to the architect's AGREE; everything else is recorded and
   left pending.
5. **IE3.** ``synthesize_intent_graph`` over the scope, with the production context compiler,
   validator, router, compiler and reducer, the certified Astra synthesizer and
   ``ExecutionMode.EXPERIMENT``. One call. A refused answer is recorded and changes nothing.

Only a provider/transport, budget, identity or harness failure stops the walk; every
remaining turn is then ``NOT_RUN``. Nothing is retried or repaired. States are not stored
per turn: each boundary's event sequence is, and any state is its ledger prefix replayed.
The runner decides nothing about meaning and never imports the answer key.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.intent_graph_synthesis import synthesize_intent_graph
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import FrozenModel
from foundry.domain.events import StoredEvent
from foundry.domain.intent_graph import IntentGraphSynthesisResult
from foundry.domain.semantic_view import derive_view
from foundry.experiments.long_horizon_bounded.authority import (
    AuthorizationRecord,
    EligibleTargets,
    authorize_eligible_supersessions,
    record_architect_authority,
    snapshot_eligible_targets,
)
from foundry.experiments.long_horizon_bounded.designation import (
    RootDesignation,
    designate_t1_roots,
)
from foundry.experiments.long_horizon_bounded.protocol import AUTHORITY_CHECKPOINTS
from foundry.experiments.long_horizon_ie2_ie3 import corpus, protocol
from foundry.experiments.long_horizon_ie2_ie3.recording import (
    GraphCallRecord,
    IE2CallRecord,
    IE2Recorder,
    RunBudget,
)
from foundry.experiments.longitudinal.artifacts import redact_secrets
from foundry.experiments.longitudinal.scoring import replay_matches
from foundry.model_runtime.errors import ModelProtocolError, ModelProviderError
from foundry.ports.intent_graph_synthesizer import IntentGraphSynthesisRequest
from foundry.ports.semantic_reasoner import ReasonerResponseRefused, SemanticReasoner

__all__ = [
    "AuthorityBudget",
    "Decision",
    "IE2Turn",
    "IE3Turn",
    "RunRecord",
    "TurnRecord",
    "run_experiment",
]


class Decision(FrozenModel):
    judgment_id: str
    route: str
    reasons: tuple[str, ...]


class IE2Turn(FrozenModel):
    status: str
    """COMPLETED, REFUSED (Call 2 structurally refused; Call 1 kept) or FAILED."""
    error: str | None
    call_1: tuple[Decision, ...]
    call_2: tuple[Decision, ...]
    calls: tuple[IE2CallRecord, ...]
    eligible: EligibleTargets | None
    authority: tuple[AuthorizationRecord, ...]


class IE3Turn(FrozenModel):
    status: str
    """APPLIED (a durable decision), NO_REQUEST (nothing to show), CONTEXT_GAP, REFUSED
    (Foundry refused the answer; nothing durable) or FAILED (provider/protocol)."""
    error: str | None
    request: dict[str, Any] | None
    result: dict[str, Any] | None
    route: str | None
    reasons: tuple[str, ...]
    graph_instance_id: str | None
    calls: tuple[GraphCallRecord, ...]


class TurnRecord(FrozenModel):
    t: int
    status: str
    seq_start: int
    seq_after_ie2: int | None
    seq_after_authority: int | None
    seq_after_ie3: int | None
    ie2: IE2Turn | None
    ie3: IE3Turn | None


class RunRecord(FrozenModel):
    status: str
    error: str | None
    project_id: str
    scope: str
    turns: tuple[TurnRecord, ...]
    designations: dict[str, RootDesignation]
    events: tuple[StoredEvent, ...]
    receipts: tuple[dict[str, Any], ...]
    replay_matches: bool | None
    ie2_calls: int
    ie3_calls: int
    ie2_cost_usd: str
    human_authorizations: int


class AuthorityBudget:
    """The runner's non-durable tally for the 9P3 authority module's ceiling."""

    def __init__(self) -> None:
        self.human_authorizations = 0


def _decisions(batch: Any) -> tuple[Decision, ...]:
    return tuple(
        Decision(judgment_id=d.judgment_id, route=d.route.value, reasons=tuple(d.reasons))
        for d in batch
    )


class _Capturing:
    """Records the exact request and result around the certified synthesizer."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.request: IntentGraphSynthesisRequest | None = None
        self.result: IntentGraphSynthesisResult | None = None

    @property
    def fingerprint(self) -> Any:
        return self._inner.fingerprint

    def synthesize(self, request: IntentGraphSynthesisRequest) -> IntentGraphSynthesisResult:
        self.request = request
        produced: IntentGraphSynthesisResult = self._inner.synthesize(request)
        self.result = produced
        return produced


def run_experiment(
    *,
    ie2: SemanticReasoner,
    ie3_synthesizer: Any,
    ie3_calls: Callable[[], tuple[GraphCallRecord, ...]],
    budget: RunBudget,
    guard_identity: bool,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    turns: tuple[int, ...] = protocol.TURNS,
) -> RunRecord:
    """Run the turns once. ``ie3_calls`` returns every provider execution recorded so far."""
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store,
        project_id=protocol.PROJECT_ID,
        policy=AdmissionPolicy(canonical_facets=protocol.CANONICAL_FACETS),
        clock=clock,
        id_factory=id_factory,
    )
    recorder = IE2Recorder(ie2, budget=budget, guard_identity=guard_identity)
    authority_budget = AuthorityBudget()
    record_architect_authority(governor, clock=clock, id_factory=id_factory)
    designations: dict[str, RootDesignation] = {}
    records: list[TurnRecord] = []
    status, error = "COMPLETED", None

    for t in turns:
        if status != "COMPLETED":
            records.append(_not_run(t, store))
            continue
        seq_start = store.current_sequence(protocol.PROJECT_ID)
        ie2_turn: IE2Turn | None = None
        ie3_turn: IE3Turn | None = None
        seq_ie2 = seq_auth = seq_ie3 = None
        try:
            eligible = _snapshot(governor, t, designations, seq_start)
            ie2_turn = _run_ie2(governor, recorder, t, eligible)
            seq_ie2 = store.current_sequence(protocol.PROJECT_ID)
            if ie2_turn.status == "FAILED":
                raise RuntimeError(ie2_turn.error or "IE2 failed")
            if t == 1:
                designations = {k: v for k, v in designate_t1_roots(governor.state()).items()}
            authority: tuple[AuthorizationRecord, ...] = ()
            if eligible is not None:
                pending = tuple(derive_view(governor.state().semantic).pending_judgment_ids)
                authority = authorize_eligible_supersessions(
                    governor=governor,
                    eligible=eligible,
                    pending_judgment_ids=pending,
                    budget=authority_budget,
                    clock=clock,
                    id_factory=id_factory,
                )
            ie2_turn = ie2_turn.model_copy(update={"authority": authority})
            seq_auth = store.current_sequence(protocol.PROJECT_ID)
            calls_before = len(ie3_calls())
            ie3_turn = _run_ie3(store, ie3_synthesizer, t, clock)
            ie3_turn = ie3_turn.model_copy(update={"calls": ie3_calls()[calls_before:]})
            seq_ie3 = store.current_sequence(protocol.PROJECT_ID)
            if ie3_turn.status == "FAILED":
                raise RuntimeError(ie3_turn.error or "IE3 failed")
            turn_status = "COMPLETED"
        except Exception as exc:  # noqa: BLE001 - recorded; the walk stops, nothing is retried
            turn_status = "FAILED"
            status, error = "ABORTED", redact_secrets(f"T{t}: {type(exc).__name__}: {exc}")
        records.append(
            TurnRecord(
                t=t,
                status=turn_status,
                seq_start=seq_start,
                seq_after_ie2=seq_ie2,
                seq_after_authority=seq_auth,
                seq_after_ie3=seq_ie3,
                ie2=ie2_turn,
                ie3=ie3_turn,
            )
        )

    events = tuple(store.load(protocol.PROJECT_ID))
    checked = replay_matches(events, governor.state())
    replay_ok = checked.status == "REPLAY_MATCH" and checked.state_matches and checked.view_matches
    if status == "COMPLETED" and not replay_ok:
        status, error = "ABORTED", "REPLAY_MISMATCH"
    return RunRecord(
        status=status,
        error=error,
        project_id=protocol.PROJECT_ID,
        scope=corpus.SCOPE,
        turns=tuple(records),
        designations=designations,
        events=events,
        receipts=tuple(
            r.model_dump(mode="json") if hasattr(r, "model_dump") else dict(r)
            for r in recorder.receipts
        ),
        replay_matches=replay_ok,
        ie2_calls=budget.ie2_calls,
        ie3_calls=budget.ie3_calls,
        ie2_cost_usd=str(budget.ie2_cost_usd),
        human_authorizations=authority_budget.human_authorizations,
    )


def _not_run(t: int, store: InMemoryEventStore) -> TurnRecord:
    seq = store.current_sequence(protocol.PROJECT_ID)
    return TurnRecord(
        t=t,
        status="NOT_RUN",
        seq_start=seq,
        seq_after_ie2=None,
        seq_after_authority=None,
        seq_after_ie3=None,
        ie2=None,
        ie3=None,
    )


def _snapshot(
    governor: SemanticGovernor, t: int, designations: dict[str, RootDesignation], seq: int
) -> EligibleTargets | None:
    locus = AUTHORITY_CHECKPOINTS.get(t)
    if locus is None:
        return None
    designation = designations.get(locus)
    return snapshot_eligible_targets(
        governor.state(),
        arm="F",
        t=t,
        target_locus=locus,
        designated_address_id=designation.address_id if designation is not None else None,
        ledger_length=seq,
    )


def _run_ie2(
    governor: SemanticGovernor, recorder: IE2Recorder, t: int, eligible: EligibleTargets | None
) -> IE2Turn:
    recorder.begin_turn(t)
    before = len(recorder.records)
    status, error = "COMPLETED", None
    call_1: tuple[Decision, ...] = ()
    call_2: tuple[Decision, ...] = ()
    try:
        outcome = assimilate_delta(
            governor=governor,
            reasoner=recorder,
            delta=corpus.delta(t),
            scope=corpus.SCOPE,
            mode=protocol.EXECUTION_MODE,
        )
        call_1 = _decisions(outcome.stage_decisions[0])
        call_2 = _decisions(outcome.stage_decisions[1])
    except ReasonerResponseRefused as refused:
        status, error = "REFUSED", redact_secrets("; ".join(refused.findings))
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        status, error = "FAILED", redact_secrets(f"{type(exc).__name__}: {exc}")
    return IE2Turn(
        status=status,
        error=error,
        call_1=call_1,
        call_2=call_2,
        calls=tuple(recorder.records[before:]),
        eligible=eligible,
        authority=(),
    )


def _run_ie3(
    store: InMemoryEventStore, synthesizer: Any, t: int, clock: Callable[[], datetime]
) -> IE3Turn:
    capturing = _Capturing(synthesizer)
    run_id = f"RUN-LH23-T{t:02d}"
    try:
        outcome = synthesize_intent_graph(
            store,
            project_id=protocol.PROJECT_ID,
            scope=corpus.SCOPE,
            synthesizer=capturing,
            clock=clock,
            synthesis_run_id_factory=lambda: run_id,
            mode=protocol.EXECUTION_MODE,
        )
    except (ModelProviderError, ModelProtocolError) as exc:
        return _ie3(capturing, "FAILED", redact_secrets(f"{type(exc).__name__}: {exc}"))
    except Exception as exc:  # noqa: BLE001 - a Foundry refusal of the answer is evidence
        return _ie3(capturing, "REFUSED", redact_secrets(f"{type(exc).__name__}: {exc}"))
    if outcome.deterministic_runtime_gap_ids:
        return _ie3(capturing, "CONTEXT_GAP", ",".join(outcome.deterministic_runtime_gap_ids))
    if outcome.decision is None:
        return _ie3(capturing, "NO_REQUEST", None)
    return _ie3(
        capturing,
        "APPLIED",
        None,
        route=outcome.decision.route.value,
        reasons=tuple(outcome.decision.reasons),
        graph_instance_id=outcome.graph_instance_id,
    )


def _ie3(
    capturing: _Capturing,
    status: str,
    error: str | None,
    *,
    route: str | None = None,
    reasons: tuple[str, ...] = (),
    graph_instance_id: str | None = None,
) -> IE3Turn:
    return IE3Turn(
        status=status,
        error=error,
        request=capturing.request.model_dump(mode="json") if capturing.request else None,
        result=capturing.result.model_dump(mode="json") if capturing.result else None,
        route=route,
        reasons=reasons,
        graph_instance_id=graph_instance_id,
        calls=(),
    )

"""Walk the sealed Larkspur sequence once through the frozen Intent Engine, then judge it.

Phases, strictly in order, each recorded:

1. **IE2.** One governed project. For each sealed step, in order: the founder's document enters
   as evidence, the writer proposes (Call 1, Call 2), the semantic admission verifier judges, the
   runtime admits, holds or resolves, and the preregistered founder decision is applied. The
   canonical state digest is recorded after every step.
2. **IE3.** One graph synthesis on the settled IE2 state.
3. **Evaluation.** Only now is the hidden oracle loaded (``oracle``), and only the adjudicator
   sees it, through ``outcome.evaluate``. Nothing of this phase is written to the ledger.

The writer, verifier, IE3 synthesizer and adjudicator are passed in: scripted offline, the live
ones only through ``live_ports`` after the founder's role binding. Every failure is recorded as
it happened; nothing is retried or repaired.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.intent_graph_synthesis import synthesize_intent_graph
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, FrozenModel, Provenance, SourceKind
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.state import IntentState
from foundry.experiments.intent_engine_e2e.expectations import ExpectedOutcome
from foundry.experiments.intent_engine_e2e.harness import StepRecord, run_scenario
from foundry.experiments.intent_engine_e2e.outcome import (
    OutcomeAdjudicator,
    OutcomeReport,
    evaluate,
    final_outcome,
)
from foundry.experiments.intent_engine_e2e.scenario import SCENARIO
from foundry.experiments.intent_engine_live_v1 import protocol
from foundry.experiments.intent_engine_live_v1.recording import (
    RecordingIE3,
    RecordingVerifier,
    RecordingWriter,
)

__all__ = ["LiveRunRecord", "StepDigest", "run_live", "state_sha256"]


class StepDigest(FrozenModel):
    step_id: str
    status: str
    decision_status: str | None
    detail: str
    last_sequence: int
    state_sha256: str


class LiveRunRecord(FrozenModel):
    experiment_version: str
    project_id: str
    scenario_id: str
    steps: tuple[StepDigest, ...]
    writer_calls: tuple[dict[str, Any], ...]
    verifier_calls: tuple[dict[str, Any], ...]
    ie3_calls: tuple[dict[str, Any], ...]
    ie3_status: str
    ie3_detail: str | None
    events: tuple[dict[str, Any], ...]
    final_state_sha256: str
    final_outcome: dict[str, Any]
    report: OutcomeReport


def state_sha256(state: IntentState) -> str:
    canonical = json.dumps(state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _founder_authority() -> AuthorityRecord:
    return AuthorityRecord(
        id="AUTH-larkspur-founder",
        project_id=protocol.PROJECT_ID,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref=protocol.FOUNDER),
        created_at=protocol.OBSERVED_AT,
        scope=(),
        subject_id="larkspur",
        authorized_by=protocol.FOUNDER,
        rationale="The founder owns the Larkspur Tool Library's intent.",
    )


def run_live(
    *,
    writer: Any,
    verifier: Any,
    ie3_synthesizer: Any,
    adjudicator: OutcomeAdjudicator,
    oracle: Callable[[], ExpectedOutcome],
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> LiveRunRecord:
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store,
        project_id=protocol.PROJECT_ID,
        policy=AdmissionPolicy(
            canonical_facets=protocol.ADMISSION_POLICY["canonical_facets"],
            correction_sets=protocol.ADMISSION_POLICY["correction_sets"],
        ),
        clock=clock,
        id_factory=id_factory,
    )
    governor.record_authority(_founder_authority())
    recorded_writer = RecordingWriter(writer)
    recorded_verifier = RecordingVerifier(verifier)
    digests: list[StepDigest] = []

    def on_step(step: StepRecord) -> None:
        state = governor.state()
        digests.append(
            StepDigest(
                step_id=step.step_id,
                status=step.status,
                decision_status=step.decision_status,
                detail=step.detail,
                last_sequence=state.last_sequence,
                state_sha256=state_sha256(state),
            )
        )

    run = run_scenario(
        scenario=SCENARIO,
        governor=governor,
        reasoner=recorded_writer,
        verifier=recorded_verifier,
        human_actor_id=protocol.FOUNDER,
        observed_at=protocol.OBSERVED_AT,
        on_step=on_step,
    )

    recorded_ie3 = RecordingIE3(ie3_synthesizer)
    ie3_status, ie3_detail = "APPLIED", None
    try:
        outcome = synthesize_intent_graph(
            store,
            project_id=protocol.PROJECT_ID,
            scope=SCENARIO.scope,
            synthesizer=recorded_ie3,
            clock=clock,
            synthesis_run_id_factory=lambda: "RUN-LARKSPUR-IE3",
            mode=protocol.EXECUTION_MODE,
        )
        if outcome.deterministic_runtime_gap_ids:
            ie3_status = "CONTEXT_GAP"
            ie3_detail = ",".join(outcome.deterministic_runtime_gap_ids)
        elif outcome.decision is None:
            ie3_status = "NO_REQUEST"
        else:
            ie3_detail = f"{outcome.decision.route.value}: {', '.join(outcome.decision.reasons)}"
    except Exception as error:  # recorded, never retried
        ie3_status, ie3_detail = "FAILED", f"{type(error).__name__}: {error}"

    state = replay(protocol.PROJECT_ID, store.load(protocol.PROJECT_ID))
    final = final_outcome(
        state,
        scenario_id=SCENARIO.scenario_id,
        scope=SCENARIO.scope,
        ie3_evaluated=ie3_status == "APPLIED",
        refused_steps=run.refused_steps,
    )
    report = evaluate(final, oracle(), adjudicator)  # the oracle exists only from here on
    return LiveRunRecord(
        experiment_version=protocol.EXPERIMENT_VERSION,
        project_id=protocol.PROJECT_ID,
        scenario_id=SCENARIO.scenario_id,
        steps=tuple(digests),
        writer_calls=tuple(recorded_writer.log.records),
        verifier_calls=tuple(recorded_verifier.log.records),
        ie3_calls=tuple(recorded_ie3.log.records),
        ie3_status=ie3_status,
        ie3_detail=ie3_detail,
        events=tuple(e.model_dump(mode="json") for e in store.load(protocol.PROJECT_ID)),
        final_state_sha256=state_sha256(state),
        final_outcome=final.model_dump(mode="json"),
        report=report,
    )

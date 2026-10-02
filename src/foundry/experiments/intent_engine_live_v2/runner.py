"""Walk the sealed Larkspur sequence once through the Intent Engine, then judge it (live e2e v2).

Phases, strictly in order, each recorded:

1. **IE2.** One governed project; each sealed step in order; founder decisions routed by runtime
   provenance (``harness``, ``provenance-v1``). If routing is ambiguous or unexplained, the run
   STOPS there: no IE3, no oracle, no adjudication, verdict NOT_VALIDATED (an experiment
   infrastructure outcome, never scored as the engine's).
2. **IE3.** One graph synthesis on the settled IE2 state.
3. **Evaluation.** Only now is the hidden oracle loaded, and only the adjudicator sees it.

Scoring is the sealed final-state scorer (``intent_engine_e2e.outcome``, unchanged from v1) plus
one structural rule it predates: a v5 completeness record that FAILED must name recorded gaps
(``SILENT_GAP`` otherwise), exactly as the scorer already requires of v3 and v4 records.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
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
from foundry.domain.semantic_completeness import SEMANTIC_ADMISSION_POLICY_VERSION_V5
from foundry.domain.state import IntentState
from foundry.experiments.intent_engine_e2e.expectations import ExpectedOutcome
from foundry.experiments.intent_engine_e2e.outcome import (
    Defect,
    DefectCategory,
    FinalOutcome,
    OutcomeAdjudicator,
    OutcomeReport,
    evaluate,
    final_outcome,
)
from foundry.experiments.intent_engine_e2e.scenario import SCENARIO
from foundry.experiments.intent_engine_live_v1.recording import (
    RecordingIE3,
    RecordingVerifier,
    RecordingWriter,
)
from foundry.experiments.intent_engine_live_v2 import protocol
from foundry.experiments.intent_engine_live_v2.harness import (
    RoutingAmbiguous,
    RoutingUnexplained,
    StepRecord,
    run_scenario,
)

__all__ = ["LiveRunRecord", "StepDigest", "evaluate_v2", "run_live", "state_sha256"]


class StepDigest(FrozenModel):
    step_id: str
    status: str
    decision_status: str | None
    decided_work_ids: tuple[str, ...]
    window: tuple[int, int]
    detail: str
    last_sequence: int
    state_sha256: str


class LiveRunRecord(FrozenModel):
    experiment_version: str
    project_id: str
    scenario_id: str
    steps: tuple[StepDigest, ...]
    routing_stop: str | None
    """Set when routing stopped the run (ambiguous or unexplained): the run is NOT_VALIDATED."""
    writer_calls: tuple[dict[str, Any], ...]
    verifier_calls: tuple[dict[str, Any], ...]
    ie3_calls: tuple[dict[str, Any], ...]
    ie3_status: str
    ie3_detail: str | None
    events: tuple[dict[str, Any], ...]
    final_state_sha256: str
    final_outcome: dict[str, Any] | None
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


def evaluate_v2(
    final: FinalOutcome, expected: ExpectedOutcome, adjudicator: OutcomeAdjudicator
) -> OutcomeReport:
    """The sealed scorer, plus the v5 silent-gap rule (structural: FAIL whatever else)."""
    report = evaluate(final, expected, adjudicator)
    gap_ids = {g.gap_id for g in final.gaps}
    extra = tuple(
        Defect(category=DefectCategory.SILENT_GAP, subject=(r.verification_id,), adjudicated=False)
        for r in final.completeness
        if r.policy_version == SEMANTIC_ADMISSION_POLICY_VERSION_V5
        and r.outcome == "FAIL"
        and (not r.gap_ids or any(g not in gap_ids for g in r.gap_ids))
    )
    if not extra:
        return report
    defects = (*report.defects, *extra)
    return report.model_copy(
        update={"defects": defects, "verdict": "FAIL", "counts": _counts(defects)}
    )


def _counts(defects: tuple[Defect, ...]) -> dict[str, int]:
    counts = Counter(d.category.value for d in defects)
    return {c.value: counts.get(c.value, 0) for c in DefectCategory}


def _not_validated(reason: str) -> OutcomeReport:
    return OutcomeReport(
        scenario_id=SCENARIO.scenario_id,
        verdict="NOT_VALIDATED",
        defects=(),
        counts={c.value: 0 for c in DefectCategory},
        ie3_evaluated=False,
        adjudication_issues=(f"ROUTING_STOP: {reason}",),
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
    recorded_ie3 = RecordingIE3(ie3_synthesizer)
    digests: list[StepDigest] = []

    def on_step(step: StepRecord) -> None:
        state = governor.state()
        digests.append(
            StepDigest(
                step_id=step.step_id,
                status=step.status,
                decision_status=step.decision_status,
                decided_work_ids=step.decided_work_ids,
                window=step.window,
                detail=step.detail,
                last_sequence=state.last_sequence,
                state_sha256=state_sha256(state),
            )
        )

    routing_stop: str | None = None
    refused: tuple[str, ...] = ()
    try:
        run = run_scenario(
            scenario=SCENARIO,
            store=store,
            governor=governor,
            reasoner=recorded_writer,
            verifier=recorded_verifier,
            human_actor_id=protocol.FOUNDER,
            observed_at=protocol.OBSERVED_AT,
            on_step=on_step,
        )
        refused = run.refused_steps
    except (RoutingAmbiguous, RoutingUnexplained) as error:  # the run stops here
        routing_stop = f"{type(error).__name__}: {error}"

    ie3_status, ie3_detail = "NOT_RUN", None
    if routing_stop is None:
        ie3_status = "APPLIED"
        try:
            outcome = synthesize_intent_graph(
                store,
                project_id=protocol.PROJECT_ID,
                scope=SCENARIO.scope,
                synthesizer=recorded_ie3,
                clock=clock,
                synthesis_run_id_factory=lambda: "RUN-LARKSPUR-V2-IE3",
                mode=protocol.EXECUTION_MODE,
            )
            if outcome.deterministic_runtime_gap_ids:
                ie3_status = "CONTEXT_GAP"
                ie3_detail = ",".join(outcome.deterministic_runtime_gap_ids)
            elif outcome.decision is None:
                ie3_status = "NO_REQUEST"
            else:
                ie3_detail = (
                    f"{outcome.decision.route.value}: {', '.join(outcome.decision.reasons)}"
                )
        except Exception as error:  # recorded, never retried
            ie3_status, ie3_detail = "FAILED", f"{type(error).__name__}: {error}"

    state = replay(protocol.PROJECT_ID, store.load(protocol.PROJECT_ID))
    final: FinalOutcome | None = None
    if routing_stop is None:
        final = final_outcome(
            state,
            scenario_id=SCENARIO.scenario_id,
            scope=SCENARIO.scope,
            ie3_evaluated=ie3_status == "APPLIED",
            refused_steps=refused,
        )
        report = evaluate_v2(final, oracle(), adjudicator)  # the oracle exists only from here
    else:
        report = _not_validated(routing_stop)
    return LiveRunRecord(
        experiment_version=protocol.EXPERIMENT_VERSION,
        project_id=protocol.PROJECT_ID,
        scenario_id=SCENARIO.scenario_id,
        steps=tuple(digests),
        routing_stop=routing_stop,
        writer_calls=tuple(recorded_writer.log.records),
        verifier_calls=tuple(recorded_verifier.log.records),
        ie3_calls=tuple(recorded_ie3.log.records),
        ie3_status=ie3_status,
        ie3_detail=ie3_detail,
        events=tuple(e.model_dump(mode="json") for e in store.load(protocol.PROJECT_ID)),
        final_state_sha256=state_sha256(state),
        final_outcome=final.model_dump(mode="json") if final is not None else None,
        report=report,
    )

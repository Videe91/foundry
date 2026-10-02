"""Walk a scenario through the real IE2 pipeline once, routing founder decisions by provenance.

Live e2e v1 routed each preregistered founder decision to "the PENDING correction set at this
concern", by the address SUBJECT the writer chose. Grok's lawful labels ("Tool loan") differed
from the scenario's ("Loan period"), so six of seven decisions were never delivered. A label is
model wording; it can never be a routing key.

**Routing law (``provenance-v1``).** A step's work is identified by runtime provenance only:

* the **ledger window** of the step -- every event appended from the step's evidence ingestion
  to the end of its assimilation (the harness alone draws these boundaries, from the immutable
  scenario order); and
* the **evidence identity** -- every member judgment of the step's correction work saw exactly
  the step's immutable evidence item (``visible_evidence_ids == (EV-<step>,)``).

A preregistered decision binds to the PENDING correction sets *proposed in that window*:

* exactly one -> the decision is delivered to it;
* none -> nothing to decide, with the runtime's recorded reason: the step's work was HELD (a
  runtime hold), REFUSED by admission (e.g. ``CORRECTION_DECLINED`` for a repeated declined
  change), or NO_CORRECTION_PROPOSED; anything else is ``RoutingUnexplained``;
* more than one, or a set whose members' provenance is not exactly the step's evidence ->
  ``RoutingAmbiguous``. The harness never guesses which correction the founder meant.

``RoutingAmbiguous`` and ``RoutingUnexplained`` stop the run: the experiment is NOT_VALIDATED.
Nothing here reads a subject, facet, predicate, value or proposition statement.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final, Literal

from foundry.application.authority_routing import decide_correction_set
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.events import (
    CorrectionSetProposedPayload,
    GapPayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
)
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_holds import SemanticHoldGap
from foundry.domain.semantic_judgment import AdmissionRoute, JudgmentKind
from foundry.domain.structural_refusal import ExecutionMode
from foundry.experiments.intent_engine_e2e.scenario import Scenario, Step
from foundry.ports.event_store import EventStore
from foundry.ports.semantic_completeness import SemanticCompletenessVerifier
from foundry.ports.semantic_reasoner import SemanticReasoner

__all__ = [
    "EXECUTION_MODE",
    "ROUTING_LAW",
    "RoutingAmbiguous",
    "RoutingUnexplained",
    "ScenarioRun",
    "StepRecord",
    "evidence_id",
    "route_decision",
    "run_scenario",
]

EXECUTION_MODE: Final = ExecutionMode.EXPERIMENT
ROUTING_LAW: Final = "provenance-v1"


class RoutingAmbiguous(RuntimeError):
    """More than one candidate, or a candidate of mixed provenance: the harness never guesses."""


class RoutingUnexplained(RuntimeError):
    """No work to decide and no recorded runtime reason why: an infrastructure fault."""


class StepRecord(FrozenModel):
    step_id: str
    status: Literal["APPLIED", "HELD", "REFUSED"]
    detail: str = ""
    window: tuple[int, int] = (0, 0)
    """The step's ledger window: (first sequence, last sequence) appended by its assimilation."""
    decision_status: str | None = None
    decided_work_ids: tuple[str, ...] = ()


class ScenarioRun(FrozenModel):
    scenario_id: str
    steps: tuple[StepRecord, ...]

    @property
    def refused_steps(self) -> tuple[str, ...]:
        return tuple(s.step_id for s in self.steps if s.status == "REFUSED")


def evidence_id(step: Step) -> str:
    return f"EV-{step.step_id}"


def route_decision(
    governor: SemanticGovernor,
    window: tuple[StoredEvent, ...],
    step: Step,
    outcome: Literal["AGREE", "DECLINE"],
    human_actor_id: str,
) -> tuple[str, tuple[str, ...]]:
    """Deliver ``outcome`` to the one correction set the step's evidence produced, or record
    why there is none. Returns (status, decided correction-set ids)."""
    semantic = governor.state().semantic
    proposed = [
        e.event.payload.correction_set.correction_set_id
        for e in window
        if isinstance(e.event.payload, CorrectionSetProposedPayload)
    ]
    for set_id in proposed:
        record = semantic.correction_sets[set_id]
        sources = {semantic.judgments[j].visible_evidence_ids for j in record.member_judgment_ids}
        if sources != {(evidence_id(step),)}:
            raise RoutingAmbiguous(
                f"{step.step_id}: correction set {set_id} has members of provenance {sources}"
            )
    pending = [i for i in proposed if semantic.correction_sets[i].status == "PENDING"]
    if len(pending) > 1:
        raise RoutingAmbiguous(f"{step.step_id}: {len(pending)} pending correction sets {pending}")
    if len(pending) == 1:
        resolution = decide_correction_set(
            governor,
            work_id=pending[0],
            outcome=outcome,
            human_actor_id=human_actor_id,
            expected_sequence=governor.state().last_sequence,
            rationale=f"founder decision preregistered for {step.step_id}",
        )
        return resolution.status, (pending[0],)
    return _nothing_to_decide(window, step), ()


def _nothing_to_decide(window: tuple[StoredEvent, ...], step: Step) -> str:
    holds = sorted(
        {
            e.event.payload.gap.cause
            for e in window
            if isinstance(e.event.payload, GapPayload)
            and isinstance(e.event.payload.gap, SemanticHoldGap)
        }
    )
    if holds:
        return f"NO_WORK: HELD ({', '.join(holds)})"
    refused = sorted(
        {
            e.event.payload.reasons[0]
            for e in window
            if isinstance(e.event.payload, SemanticAdmissionPayload)
            and e.event.payload.route is AdmissionRoute.REJECT
        }
    )
    if refused:
        return f"NO_WORK: REFUSED ({', '.join(refused)})"
    supersedes = [
        e
        for e in window
        if isinstance(e.event.payload, SemanticJudgmentPayload)
        and e.event.payload.judgment.proposal.kind is JudgmentKind.SUPERSEDE
    ]
    if not supersedes:
        return "NO_WORK: NO_CORRECTION_PROPOSED"
    raise RoutingUnexplained(
        f"{step.step_id}: correction judgments recorded, no correction set, no hold, no refusal"
    )


def _holds(governor: SemanticGovernor) -> frozenset[str]:
    return frozenset(g.id for g in governor.state().gaps.values() if isinstance(g, SemanticHoldGap))


def run_scenario(
    *,
    scenario: Scenario,
    store: EventStore,
    governor: SemanticGovernor,
    reasoner: SemanticReasoner,
    verifier: SemanticCompletenessVerifier,
    human_actor_id: str,
    observed_at: datetime,
    on_step: Callable[[StepRecord], None] | None = None,
) -> ScenarioRun:
    """``on_step`` (optional) observes each step's record once the step is over; it decides
    nothing. ``RoutingAmbiguous`` / ``RoutingUnexplained`` propagate: the run stops."""
    records: list[StepRecord] = []
    for step in scenario.steps:
        item = evidence_item(
            evidence_id=evidence_id(step),
            project_id=governor.project_id,
            source_kind=SourceKind.HUMAN,
            source_ref=human_actor_id,
            content=step.text,
            observed_at=observed_at,
            scope=(scenario.scope,),
            artifact_ref=step.artifact,
            supersedes_evidence_id=(
                f"EV-{step.supersedes_step}" if step.supersedes_step is not None else None
            ),
        )
        start = governor.state().last_sequence
        before = _holds(governor)
        status: Literal["APPLIED", "HELD", "REFUSED"]
        detail = ""
        try:
            assimilate_delta(
                governor=governor,
                reasoner=reasoner,
                delta=(item,),
                scope=scenario.scope,
                mode=EXECUTION_MODE,
                verifier=verifier,
            )
            status = "HELD" if _holds(governor) - before else "APPLIED"
        except Exception as error:  # recorded, never retried
            status, detail = "REFUSED", type(error).__name__
        window = tuple(store.load(governor.project_id, after_sequence=start))
        end = window[-1].sequence if window else start
        decision: str | None = None
        decided: tuple[str, ...] = ()
        if step.decision is not None:
            decision, decided = route_decision(
                governor, window, step, step.decision, human_actor_id
            )
        records.append(
            StepRecord(
                step_id=step.step_id,
                status=status,
                detail=detail,
                window=(start + 1, end),
                decision_status=decision,
                decided_work_ids=decided,
            )
        )
        if on_step is not None:
            on_step(records[-1])
    return ScenarioRun(scenario_id=scenario.scenario_id, steps=tuple(records))

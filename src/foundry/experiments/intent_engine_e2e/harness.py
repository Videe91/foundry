"""Walk a scenario through the real IE2 pipeline once. Provider-neutral; never retries.

Per step: the step's document enters as founder evidence (revising the earlier step's document
when it says so), ``assimilate_delta`` runs Call 1, Call 2 and the independent completeness
verifier under the caller's governor, and, when the step carries a founder decision, the one
PENDING correction set at that concern is decided through ``decide_correction_set``. Whatever
happens is recorded, including an exception (``REFUSED``); nothing is repaired or re-run. The
harness never sees expectations and never scores: it returns what ran, and the final state is
the governor's ledger.

The writer, verifier and governor are the caller's, so the same harness runs scripted
(offline tests) or live (a later, separately approved run).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal

from foundry.application.authority_routing import decide_correction_set
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_holds import SemanticHoldGap
from foundry.domain.structural_refusal import ExecutionMode
from foundry.experiments.intent_engine_e2e.scenario import Scenario, Step
from foundry.ports.semantic_completeness import SemanticCompletenessVerifier
from foundry.ports.semantic_reasoner import SemanticReasoner

__all__ = ["EXECUTION_MODE", "ScenarioRun", "StepRecord", "evidence_id", "run_scenario"]

EXECUTION_MODE: Final = ExecutionMode.EXPERIMENT
"""Never PRODUCTION: this harness activates nothing."""


class StepRecord(FrozenModel):
    step_id: str
    status: Literal["APPLIED", "HELD", "REFUSED"]
    """HELD: part or all of the response was held as a runtime hold gap (incomplete, conflict,
    invalid or unavailable verification). REFUSED: the run raised; ``detail`` names it."""
    detail: str = ""
    decision_status: str | None = None
    """For a step with a founder decision: the decided set's status, or why none was decided."""


class ScenarioRun(FrozenModel):
    scenario_id: str
    steps: tuple[StepRecord, ...]

    @property
    def refused_steps(self) -> tuple[str, ...]:
        return tuple(s.step_id for s in self.steps if s.status == "REFUSED")


def evidence_id(step: Step) -> str:
    return f"EV-{step.step_id}"


def _holds(governor: SemanticGovernor) -> frozenset[str]:
    return frozenset(g.id for g in governor.state().gaps.values() if isinstance(g, SemanticHoldGap))


def _decide(
    governor: SemanticGovernor,
    step: Step,
    outcome: Literal["AGREE", "DECLINE"],
    human_actor_id: str,
) -> str:
    state = governor.state()
    semantic = state.semantic
    pending = [
        r
        for r in semantic.correction_sets.values()
        if r.status == "PENDING" and semantic.addresses[r.address_id].subject == step.concern
    ]
    if len(pending) != 1:
        return f"NOT_DECIDED: {len(pending)} pending correction sets at {step.concern}"
    resolution = decide_correction_set(
        governor,
        work_id=pending[0].correction_set_id,
        outcome=outcome,
        human_actor_id=human_actor_id,
        expected_sequence=state.last_sequence,
        rationale=f"founder decision at {step.step_id}",
    )
    return resolution.status


def run_scenario(
    *,
    scenario: Scenario,
    governor: SemanticGovernor,
    reasoner: SemanticReasoner,
    verifier: SemanticCompletenessVerifier,
    human_actor_id: str,
    observed_at: datetime,
) -> ScenarioRun:
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
        before = _holds(governor)
        try:
            assimilate_delta(
                governor=governor,
                reasoner=reasoner,
                delta=(item,),
                scope=scenario.scope,
                mode=EXECUTION_MODE,
                verifier=verifier,
            )
        except Exception as error:  # recorded, never retried
            records.append(
                StepRecord(step_id=step.step_id, status="REFUSED", detail=type(error).__name__)
            )
            continue
        status: Literal["APPLIED", "HELD"] = "HELD" if _holds(governor) - before else "APPLIED"
        decision = (
            _decide(governor, step, step.decision, human_actor_id)
            if step.decision is not None
            else None
        )
        records.append(StepRecord(step_id=step.step_id, status=status, decision_status=decision))
    return ScenarioRun(scenario_id=scenario.scenario_id, steps=tuple(records))

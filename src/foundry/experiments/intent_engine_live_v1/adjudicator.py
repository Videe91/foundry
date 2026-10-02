"""The outcome adjudicator: experiment evaluation only, through the Model Runtime.

It is shown one ``AdjudicationPacket`` -- the hidden final truths (statements only, never an
expected status) and the final IE2/IE3 state -- after the run is over, and maps the state onto
the truths: per claim, per current IE3 object, per open IE3 gap, plus contradictory current
claim pairs. It has no production authority: its answer is never written to any ledger, and
nothing it says can change runtime state. Its optional note is never read.

The wire answer (``OutcomeAdjudicationAnswer``) is the provider-compilable form of
``Adjudication`` (pairs as objects, not tuples); ``to_adjudication`` maps it one to one. Any
failure -- no certified model, a provider error, an answer that breaks the schema -- raises, and
``outcome.evaluate`` records the run as NOT_VALIDATED. Nothing is retried.
"""

from __future__ import annotations

import json
from typing import Final

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.experiments.intent_engine_e2e.outcome import (
    Adjudication,
    AdjudicationPacket,
    ClaimReading,
    GapReading,
    GraphReading,
)
from foundry.experiments.intent_engine_live_v1 import protocol
from foundry.model_runtime.domain import (
    MessageRole,
    ModelCapability,
    ModelExecutionConstraints,
    ModelMessage,
    ModelRequest,
    ModelTask,
    ModelTier,
    ModelTraceContext,
    output_schema_sha256,
)
from foundry.model_runtime.runtime import ModelRuntime

__all__ = [
    "ADJUDICATOR_INSTRUCTION",
    "ADJUDICATOR_INSTRUCTION_SHA256",
    "ModelRuntimeOutcomeAdjudicator",
    "OutcomeAdjudicationAnswer",
    "adjudicator_output_schema_sha256",
    "to_adjudication",
]


class WireClaimReading(FrozenModel):
    claim_id: str = Field(min_length=1)
    truth_id: str | None
    faithful: bool
    certain: bool


class WireContradiction(FrozenModel):
    claim_a: str = Field(min_length=1)
    claim_b: str = Field(min_length=1)


class WireGraphReading(FrozenModel):
    object_id: str = Field(min_length=1)
    truth_ids: tuple[str, ...]
    faithful: bool
    certain: bool


class WireGapReading(FrozenModel):
    gap_id: str = Field(min_length=1)
    truth_ids: tuple[str, ...]
    certain: bool


class OutcomeAdjudicationAnswer(FrozenModel):
    readings: tuple[WireClaimReading, ...]
    contradictions: tuple[WireContradiction, ...]
    graph_readings: tuple[WireGraphReading, ...]
    gap_readings: tuple[WireGapReading, ...]
    note: str | None
    """For a human reader only; never read by any rule."""


def to_adjudication(answer: OutcomeAdjudicationAnswer) -> Adjudication:
    return Adjudication(
        readings=tuple(
            ClaimReading(
                claim_id=r.claim_id, truth_id=r.truth_id, faithful=r.faithful, certain=r.certain
            )
            for r in answer.readings
        ),
        contradictions=tuple((c.claim_a, c.claim_b) for c in answer.contradictions),
        graph_readings=tuple(
            GraphReading(
                object_id=r.object_id,
                truth_ids=r.truth_ids,
                faithful=r.faithful,
                certain=r.certain,
            )
            for r in answer.graph_readings
        ),
        gap_readings=tuple(
            GapReading(gap_id=r.gap_id, truth_ids=r.truth_ids, certain=r.certain)
            for r in answer.gap_readings
        ),
    )


ADJUDICATOR_INSTRUCTION: Final[str] = (
    "You are the outcome adjudicator of a sealed experiment. You decide nothing about what is\n"
    "true in the system; you only map its final state onto a list of expected truths.\n"
    "\n"
    "You receive one AdjudicationPacket: truths (each a truth_id, a concern and a statement of\n"
    "meaning), the system's claims (each current or retired), its current graph_objects and its\n"
    "open ie3_gaps. Judge meaning, never wording: a paraphrase, a different predicate name, a\n"
    "different concern label or a different split into several claims is the same meaning.\n"
    "\n"
    "readings: for EVERY claim, current or retired, give the truth_id whose meaning it states,\n"
    "or null when it states none of them; faithful is false when it states that truth with a\n"
    "materially different meaning (another value, actor, condition or consequence).\n"
    "contradictions: every pair of CURRENT claims that cannot both be true at once.\n"
    "graph_readings: for EVERY graph object, the truth_ids it states (empty when none), and\n"
    "whether it states them faithfully and adds nothing material.\n"
    "gap_readings: for EVERY ie3 gap, the truth_ids it is about (empty when none).\n"
    "certain is false whenever you cannot map an item with confidence; never guess.\n"
    "\n"
    "note is optional free text for a human reader. It is never read by any rule.\n"
    "Return only the OutcomeAdjudicationAnswer, covering every item exactly once.\n"
)

ADJUDICATOR_INSTRUCTION_SHA256: Final[str] = (
    "f1865f4b645c1f377d568e6176d1a21b3d5e66ff143dff7010f641a780b386cf"
)
"""A PASTED LITERAL, checked by ``tests/unit/test_intent_engine_live_v1.py``."""


def adjudicator_output_schema_sha256() -> str:
    return output_schema_sha256(OutcomeAdjudicationAnswer)


class ModelRuntimeOutcomeAdjudicator:
    """One adjudication through the Model Runtime (task EVALUATION, tier REASONER). It names
    no provider: the registry built from the founder's role binding selects the model."""

    def __init__(
        self,
        *,
        runtime: ModelRuntime,
        run_id: str,
        constraints: ModelExecutionConstraints | None = None,
    ) -> None:
        self._runtime = runtime
        self._run_id = run_id
        self._constraints = constraints
        self.calls = 0

    def adjudicate(self, packet: AdjudicationPacket) -> Adjudication:
        if self.calls >= protocol.MAX_ADJUDICATOR_CALLS:
            raise RuntimeError("the adjudicator budget is spent: one adjudication per run")
        self.calls += 1
        request = ModelRequest(
            task=ModelTask.EVALUATION,
            tier=ModelTier.REASONER,
            messages=(
                ModelMessage(role=MessageRole.SYSTEM, content=ADJUDICATOR_INSTRUCTION),
                ModelMessage(
                    role=MessageRole.USER,
                    content=json.dumps(packet.model_dump(mode="json"), sort_keys=True),
                ),
            ),
            required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
            policy_id=protocol.ADJUDICATOR_POLICY_ID,
            policy_version=protocol.ADJUDICATOR_POLICY_VERSION,
            trace=ModelTraceContext(run_id=self._run_id, call_id="ADJUDICATION-1"),
            constraints=self._constraints or ModelExecutionConstraints(),
        )
        result = self._runtime.execute(request, output_type=OutcomeAdjudicationAnswer)
        return to_adjudication(result.output)

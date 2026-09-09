from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel, RiskLevel
from foundry.domain.gaps import GapKind
from foundry.intelligence.kinds import IntelligenceSemanticKind


class SemanticProposalBase(FrozenModel):
    proposal_id: str = Field(min_length=1)
    kind: IntelligenceSemanticKind
    confidence: float = Field(ge=0.0, le=1.0)
    source_event_ids: tuple[str, ...] = ()


class IntentProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.INTENT] = IntelligenceSemanticKind.INTENT
    mission: str = Field(min_length=1)


class GoalProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.GOAL] = IntelligenceSemanticKind.GOAL
    statement: str = Field(min_length=1)


class OutcomeProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.OUTCOME] = IntelligenceSemanticKind.OUTCOME
    statement: str = Field(min_length=1)


class RequirementProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.REQUIREMENT] = IntelligenceSemanticKind.REQUIREMENT
    statement: str = Field(min_length=1)


class ConstraintProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.CONSTRAINT] = IntelligenceSemanticKind.CONSTRAINT
    statement: str = Field(min_length=1)


class NonGoalProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.NON_GOAL] = IntelligenceSemanticKind.NON_GOAL
    statement: str = Field(min_length=1)


class PreferenceProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.PREFERENCE] = IntelligenceSemanticKind.PREFERENCE
    statement: str = Field(min_length=1)


class AssumptionProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.ASSUMPTION] = IntelligenceSemanticKind.ASSUMPTION
    statement: str = Field(min_length=1)
    risk_level: RiskLevel


class ClaimProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.CLAIM] = IntelligenceSemanticKind.CLAIM
    statement: str = Field(min_length=1)


class UnknownProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.UNKNOWN] = IntelligenceSemanticKind.UNKNOWN
    question: str = Field(min_length=1)
    blocking: bool


class QuestionProposal(SemanticProposalBase):
    kind: Literal[IntelligenceSemanticKind.QUESTION] = IntelligenceSemanticKind.QUESTION
    prompt: str = Field(min_length=1)


type SemanticProposal = Annotated[
    IntentProposal
    | GoalProposal
    | OutcomeProposal
    | RequirementProposal
    | ConstraintProposal
    | NonGoalProposal
    | PreferenceProposal
    | AssumptionProposal
    | ClaimProposal
    | UnknownProposal
    | QuestionProposal,
    Field(discriminator="kind"),
]


class GapProposal(FrozenModel):
    proposal_id: str = Field(min_length=1)
    kind: GapKind
    subject_key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    affected_proposal_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    blocking: bool
    confidence: float = Field(ge=0.0, le=1.0)


class IntentIntelligencePayload(FrozenModel):
    semantic_proposals: tuple[SemanticProposal, ...] = ()
    gap_proposals: tuple[GapProposal, ...] = ()


class IntelligenceUsage(FrozenModel):
    deterministic_jobs: int = Field(default=0, ge=0)
    cheap_model_jobs: int = Field(default=0, ge=0)
    standard_model_jobs: int = Field(default=0, ge=0)
    strong_model_jobs: int = Field(default=0, ge=0)
    frontier_model_jobs: int = Field(default=0, ge=0)
    human_escalations: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    wall_clock_ms: int = Field(default=0, ge=0)


class IntentIntelligenceResult(FrozenModel):
    payload: IntentIntelligencePayload
    usage: IntelligenceUsage

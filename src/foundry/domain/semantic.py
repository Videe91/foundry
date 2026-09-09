from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from foundry.domain.common import (
    Authority,
    FrozenModel,
    LifecycleStatus,
    Materiality,
    Provenance,
    Relation,
    RiskLevel,
    SourceKind,
)


class SemanticKind(StrEnum):
    INTENT = "INTENT"
    GOAL = "GOAL"
    ACTOR = "ACTOR"
    OUTCOME = "OUTCOME"
    REQUIREMENT = "REQUIREMENT"
    CONSTRAINT = "CONSTRAINT"
    NON_GOAL = "NON_GOAL"
    DECISION = "DECISION"
    PREFERENCE = "PREFERENCE"
    ASSUMPTION = "ASSUMPTION"
    CLAIM = "CLAIM"
    EVIDENCE = "EVIDENCE"
    UNKNOWN = "UNKNOWN"
    QUESTION = "QUESTION"
    CONFLICT = "CONFLICT"
    RISK = "RISK"
    METRIC = "METRIC"
    CONTRACT = "CONTRACT"
    VERIFICATION_OBLIGATION = "VERIFICATION_OBLIGATION"
    AUTHORITY_RECORD = "AUTHORITY_RECORD"
    AMENDMENT = "AMENDMENT"


class SemanticBase(FrozenModel):
    id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    kind: SemanticKind
    revision: int = Field(default=1, ge=1)
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE
    authority: Authority
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance
    created_at: datetime
    scope: tuple[str, ...] = ()
    relations: tuple[Relation, ...] = ()


class Intent(SemanticBase):
    kind: Literal[SemanticKind.INTENT] = SemanticKind.INTENT
    mission: str = Field(min_length=1)


class Goal(SemanticBase):
    kind: Literal[SemanticKind.GOAL] = SemanticKind.GOAL
    statement: str = Field(min_length=1)


class Actor(SemanticBase):
    kind: Literal[SemanticKind.ACTOR] = SemanticKind.ACTOR
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class Outcome(SemanticBase):
    kind: Literal[SemanticKind.OUTCOME] = SemanticKind.OUTCOME
    statement: str = Field(min_length=1)


class Requirement(SemanticBase):
    kind: Literal[SemanticKind.REQUIREMENT] = SemanticKind.REQUIREMENT
    statement: str = Field(min_length=1)
    materiality: Materiality = Materiality.MEDIUM
    requires_metric: bool = False
    metric_exempt_reason: str | None = None
    requires_verification: bool = False
    verification_exempt_reason: str | None = None


class Constraint(SemanticBase):
    kind: Literal[SemanticKind.CONSTRAINT] = SemanticKind.CONSTRAINT
    statement: str = Field(min_length=1)


class NonGoal(SemanticBase):
    kind: Literal[SemanticKind.NON_GOAL] = SemanticKind.NON_GOAL
    statement: str = Field(min_length=1)


class Decision(SemanticBase):
    kind: Literal[SemanticKind.DECISION] = SemanticKind.DECISION
    statement: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class Preference(SemanticBase):
    kind: Literal[SemanticKind.PREFERENCE] = SemanticKind.PREFERENCE
    statement: str = Field(min_length=1)


class Assumption(SemanticBase):
    kind: Literal[SemanticKind.ASSUMPTION] = SemanticKind.ASSUMPTION
    statement: str = Field(min_length=1)
    risk_level: RiskLevel = RiskLevel.MEDIUM


class Claim(SemanticBase):
    kind: Literal[SemanticKind.CLAIM] = SemanticKind.CLAIM
    statement: str = Field(min_length=1)


class Evidence(SemanticBase):
    kind: Literal[SemanticKind.EVIDENCE] = SemanticKind.EVIDENCE
    statement: str = Field(min_length=1)
    supported_claim_ids: tuple[str, ...] = ()
    challenged_claim_ids: tuple[str, ...] = ()
    source_type: SourceKind
    retrieved_at: datetime | None = None
    freshness_note: str | None = None
    limitations: tuple[str, ...] = ()


class Unknown(SemanticBase):
    kind: Literal[SemanticKind.UNKNOWN] = SemanticKind.UNKNOWN
    question: str = Field(min_length=1)
    blocking: bool = False


class Question(SemanticBase):
    kind: Literal[SemanticKind.QUESTION] = SemanticKind.QUESTION
    prompt: str = Field(min_length=1)
    target_object_ids: tuple[str, ...] = ()


class Conflict(SemanticBase):
    kind: Literal[SemanticKind.CONFLICT] = SemanticKind.CONFLICT
    statement: str = Field(min_length=1)
    object_ids: tuple[str, ...] = ()
    resolved: bool = False


class Risk(SemanticBase):
    kind: Literal[SemanticKind.RISK] = SemanticKind.RISK
    statement: str = Field(min_length=1)
    risk_level: RiskLevel
    likelihood: float = Field(ge=0.0, le=1.0)


class Metric(SemanticBase):
    kind: Literal[SemanticKind.METRIC] = SemanticKind.METRIC
    name: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    target: str = Field(min_length=1)


class Contract(SemanticBase):
    kind: Literal[SemanticKind.CONTRACT] = SemanticKind.CONTRACT
    statement: str = Field(min_length=1)
    observable: bool


class VerificationObligation(SemanticBase):
    kind: Literal[SemanticKind.VERIFICATION_OBLIGATION] = SemanticKind.VERIFICATION_OBLIGATION
    statement: str = Field(min_length=1)
    target_object_ids: tuple[str, ...] = ()
    method_class: str = Field(min_length=1)


class AuthorityRecord(SemanticBase):
    kind: Literal[SemanticKind.AUTHORITY_RECORD] = SemanticKind.AUTHORITY_RECORD
    subject_id: str = Field(min_length=1)
    authorized_by: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class Amendment(SemanticBase):
    kind: Literal[SemanticKind.AMENDMENT] = SemanticKind.AMENDMENT
    subject_id: str = Field(min_length=1)
    change_statement: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


SemanticObject: TypeAlias = Annotated[
    Intent
    | Goal
    | Actor
    | Outcome
    | Requirement
    | Constraint
    | NonGoal
    | Decision
    | Preference
    | Assumption
    | Claim
    | Evidence
    | Unknown
    | Question
    | Conflict
    | Risk
    | Metric
    | Contract
    | VerificationObligation
    | AuthorityRecord
    | Amendment,
    Field(discriminator="kind"),
]

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

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
    id: str
    project_id: str
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
    mission: str


class Goal(SemanticBase):
    kind: Literal[SemanticKind.GOAL] = SemanticKind.GOAL
    statement: str


class Actor(SemanticBase):
    kind: Literal[SemanticKind.ACTOR] = SemanticKind.ACTOR
    name: str
    description: str


class Outcome(SemanticBase):
    kind: Literal[SemanticKind.OUTCOME] = SemanticKind.OUTCOME
    statement: str


class Requirement(SemanticBase):
    kind: Literal[SemanticKind.REQUIREMENT] = SemanticKind.REQUIREMENT
    statement: str
    materiality: Materiality | None = None
    requires_metric: bool
    metric_exempt_reason: str | None = None
    requires_verification: bool
    verification_exempt_reason: str | None = None


class Constraint(SemanticBase):
    kind: Literal[SemanticKind.CONSTRAINT] = SemanticKind.CONSTRAINT
    statement: str


class NonGoal(SemanticBase):
    kind: Literal[SemanticKind.NON_GOAL] = SemanticKind.NON_GOAL
    statement: str


class Decision(SemanticBase):
    kind: Literal[SemanticKind.DECISION] = SemanticKind.DECISION
    statement: str
    rationale: str


class Preference(SemanticBase):
    kind: Literal[SemanticKind.PREFERENCE] = SemanticKind.PREFERENCE
    statement: str


class Assumption(SemanticBase):
    kind: Literal[SemanticKind.ASSUMPTION] = SemanticKind.ASSUMPTION
    statement: str
    risk_level: RiskLevel


class Claim(SemanticBase):
    kind: Literal[SemanticKind.CLAIM] = SemanticKind.CLAIM
    statement: str


class Evidence(SemanticBase):
    kind: Literal[SemanticKind.EVIDENCE] = SemanticKind.EVIDENCE
    statement: str
    supported_claim_ids: tuple[str, ...]
    challenged_claim_ids: tuple[str, ...]
    source_type: SourceKind
    retrieved_at: datetime
    freshness_note: str
    limitations: str


class Unknown(SemanticBase):
    kind: Literal[SemanticKind.UNKNOWN] = SemanticKind.UNKNOWN
    question: str
    blocking: bool


class Question(SemanticBase):
    kind: Literal[SemanticKind.QUESTION] = SemanticKind.QUESTION
    prompt: str
    target_object_ids: tuple[str, ...]


class Conflict(SemanticBase):
    kind: Literal[SemanticKind.CONFLICT] = SemanticKind.CONFLICT
    statement: str
    object_ids: tuple[str, ...]
    resolved: bool


class Risk(SemanticBase):
    kind: Literal[SemanticKind.RISK] = SemanticKind.RISK
    statement: str
    risk_level: RiskLevel
    likelihood: float


class Metric(SemanticBase):
    kind: Literal[SemanticKind.METRIC] = SemanticKind.METRIC
    name: str
    definition: str
    target: str


class Contract(SemanticBase):
    kind: Literal[SemanticKind.CONTRACT] = SemanticKind.CONTRACT
    statement: str
    observable: bool


class VerificationObligation(SemanticBase):
    kind: Literal[SemanticKind.VERIFICATION_OBLIGATION] = SemanticKind.VERIFICATION_OBLIGATION
    statement: str
    target_object_ids: tuple[str, ...]
    method_class: str


class AuthorityRecord(SemanticBase):
    kind: Literal[SemanticKind.AUTHORITY_RECORD] = SemanticKind.AUTHORITY_RECORD
    subject_id: str
    authorized_by: str
    rationale: str


class Amendment(SemanticBase):
    kind: Literal[SemanticKind.AMENDMENT] = SemanticKind.AMENDMENT
    subject_id: str
    change_statement: str
    rationale: str


type SemanticObject = Annotated[
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

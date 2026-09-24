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


class ConstraintFacet(StrEnum):
    """What can legitimately change a Constraint (IE2.1, spec §5).

    Classified by *relaxation behaviour*, never by topic. A topic label such as
    "technical" would hold both a platform limit that dies when re-measured and a vendor
    obligation no engineer may waive — different rules under one name, which is how a junk
    drawer starts.
    """

    EXTERNAL_MANDATE = "EXTERNAL_MANDATE"
    """Imposed from outside; no project actor may waive it. Law, regulation, standards and
    external contractual obligation share this one rule."""

    PROJECT_BOUNDARY = "PROJECT_BOUNDARY"
    """The project imposed it and an authorized human may lift it through a governed
    authority act. Budget, resource and policy limits share this relaxation authority."""

    EVIDENCE_BOUND = "EVIDENCE_BOUND"
    """A factual limitation. Cannot be waived by preference, decision or authority, but does
    die when its evidentiary basis changes."""


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
    # Widening a base field is a Liskov violation in general, and mypy is right to say
    # so: a reader typed against ``SemanticBase.confidence`` could receive ``None``. It
    # is narrowed deliberately and verified safe — NOTHING in ``src/foundry`` reads
    # object confidence (the only ``.confidence`` reads are on ``GapProposal``), routing
    # is confidence-blind by test, and closure and the package never consult it. The
    # ruled alternative, making the field optional on ``SemanticBase``, would broaden
    # the whole semantic domain to solve one Slice-1 construction mismatch.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)  # type: ignore[assignment]
    """Optional, unlike every other ``SemanticBase`` subclass (D12).

    A synthesized Requirement carries forward the proposal's confidence exactly, and a
    ``RequirementSynthesisProposal`` may legitimately supply none. ``None`` means **no
    numeric confidence was supplied** — it is not zero confidence, and the two are
    distinguishable.

    Inventing a value instead would fabricate an epistemic statement: ``0.0`` asserts no
    confidence, ``1.0`` asserts certainty, ``0.5`` asserts a coin flip. Each would be
    attributed to the model, become durable, and be unreviewable, so none is used.

    This widening is deliberately narrow. ``SemanticBase.confidence`` stays required for
    every other kind; a future synthesized intent kind must make its own explicit
    decision rather than inheriting this one. Nothing reads object confidence — routing
    is confidence-blind by test, and closure and the package never consult it — so the
    field remains pure metadata.
    """

    statement: str
    materiality: Materiality
    requires_metric: bool
    metric_exempt_reason: str | None = None
    requires_verification: bool
    verification_exempt_reason: str | None = None


class Constraint(SemanticBase):
    kind: Literal[SemanticKind.CONSTRAINT] = SemanticKind.CONSTRAINT
    statement: str
    facet: ConstraintFacet | None = None
    """Optional and defaulted so historical events, which carry no facet, replay unchanged.

    Required only when canonicalizing a new Constraint; never retroactively demanded.
    """


class NonGoal(SemanticBase):
    kind: Literal[SemanticKind.NON_GOAL] = SemanticKind.NON_GOAL
    statement: str


class ProjectDecision(SemanticBase):
    """An authoritative recorded choice among alternatives, with rationale (IE2.1, §6).

    Not ``SemanticJudgment``, not ``IntentSynthesisDecision``, not a governance routing
    decision — those are machinery; this is project content.

    **A ProjectDecision is not an obligation.** "We chose PostgreSQL" constrains nothing by
    itself. Consequence is expressed by a separate object naming the decision as basis, so a
    Decision may never be the source of ``CONSTRAINS``: letting it constrain would hand it
    Constraint semantics through the back door, which is what this narrowed definition
    exists to prevent.
    """

    kind: Literal[SemanticKind.DECISION] = SemanticKind.DECISION
    statement: str
    rationale: str


Decision = ProjectDecision
"""Deprecated alias. The serialized ``kind`` is what round-trips, so the class rename is
invisible to history; this keeps existing imports and the ``SemanticObject`` union working."""


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
    supported_claim_ids: tuple[str, ...] = ()
    challenged_claim_ids: tuple[str, ...] = ()
    retrieved_at: datetime
    freshness_note: str | None = None
    limitations: tuple[str, ...] = ()


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
    likelihood: float | None = Field(default=None, ge=0.0, le=1.0)


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

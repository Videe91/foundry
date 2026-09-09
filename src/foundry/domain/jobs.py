from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from foundry.domain.common import FrozenModel, RiskLevel


class ExecutorClass(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    CHEAP_MODEL = "CHEAP_MODEL"
    STANDARD_MODEL = "STANDARD_MODEL"
    STRONG_MODEL = "STRONG_MODEL"
    FRONTIER_MODEL = "FRONTIER_MODEL"
    HUMAN = "HUMAN"


class JobType(StrEnum):
    DETERMINISTIC_EXTRACTION = "DETERMINISTIC_EXTRACTION"
    SEMANTIC_CLASSIFICATION = "SEMANTIC_CLASSIFICATION"
    AMBIGUITY_ANALYSIS = "AMBIGUITY_ANALYSIS"
    CONTRADICTION_ANALYSIS = "CONTRADICTION_ANALYSIS"
    RESEARCH_PLANNING = "RESEARCH_PLANNING"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    EVIDENCE_RECONCILIATION = "EVIDENCE_RECONCILIATION"
    REQUIREMENT_REFINEMENT = "REQUIREMENT_REFINEMENT"
    METRIC_DESIGN = "METRIC_DESIGN"
    VERIFICATION_OBLIGATION_DESIGN = "VERIFICATION_OBLIGATION_DESIGN"
    TRADE_OFF_ANALYSIS = "TRADE_OFF_ANALYSIS"
    STRONG_REASONING_RESOLUTION = "STRONG_REASONING_RESOLUTION"
    HUMAN_CLARIFICATION = "HUMAN_CLARIFICATION"
    HUMAN_AUTHORIZATION = "HUMAN_AUTHORIZATION"
    CONTEXT_RECOMPILE = "CONTEXT_RECOMPILE"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class Job(FrozenModel):
    id: str
    project_id: str
    gap_id: str
    job_type: JobType
    target_object_ids: tuple[str, ...]
    output_schema_ref: str = Field(min_length=1)
    risk: RiskLevel
    max_context_tokens: int = Field(gt=0)
    permitted_executors: tuple[ExecutorClass, ...] = Field(min_length=1)
    budget_usd: float = Field(ge=0.0)
    verification_requirement: str = Field(min_length=1)
    status: JobStatus = JobStatus.PENDING
    attempt: int = Field(default=0, ge=0)

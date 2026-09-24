from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Authority(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    PROPOSED = "PROPOSED"
    CANONICAL = "CANONICAL"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LifecycleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SourceKind(StrEnum):
    HUMAN = "HUMAN"
    DOCUMENT = "DOCUMENT"
    CODE = "CODE"
    TEST = "TEST"
    RUNTIME = "RUNTIME"
    RESEARCH = "RESEARCH"
    SYSTEM = "SYSTEM"
    TICKET = "TICKET"
    PULL_REQUEST = "PULL_REQUEST"
    AGENT_CONVERSATION = "AGENT_CONVERSATION"


class Materiality(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RelationType(StrEnum):
    SUPPORTS = "SUPPORTS"
    CHALLENGES = "CHALLENGES"
    DERIVED_FROM = "DERIVED_FROM"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    REQUIRES = "REQUIRES"
    CONSTRAINS = "CONSTRAINS"
    MEASURED_BY = "MEASURED_BY"
    VERIFIED_BY = "VERIFIED_BY"
    SUPERSEDES = "SUPERSEDES"
    AFFECTS = "AFFECTS"
    RELATES_TO = "RELATES_TO"
    SERVES = "SERVES"
    """Relevance: why this object belongs to this project (IE2, R2/R3).

    Deliberately distinct from ``DERIVED_FROM``, which answers why an object is *true*.
    Collapsing the two would force a fabricated human derivation for obligations the world
    imposes — a regulation grounds a Constraint, but it is the Intent that makes it relevant.
    """
    EXCLUDES = "EXCLUDES"
    """Explicit exclusion, recorded by a ``NonGoal`` against what it rules out (IE2, R3)."""


class Provenance(FrozenModel):
    source_kind: SourceKind
    source_ref: str = Field(min_length=1)
    source_event_ids: tuple[str, ...] = ()


class Relation(FrozenModel):
    relation_type: RelationType
    target_id: str = Field(min_length=1)


class TemporalMetadata(FrozenModel):
    created_at: datetime

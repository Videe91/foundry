from __future__ import annotations

from enum import StrEnum

from foundry.domain.common import FrozenModel, Materiality, RiskLevel


class GapKind(StrEnum):
    MISSING_INFORMATION = "MISSING_INFORMATION"
    AMBIGUITY = "AMBIGUITY"
    CONTRADICTION = "CONTRADICTION"
    UNSUPPORTED_ASSUMPTION = "UNSUPPORTED_ASSUMPTION"
    MISSING_AUTHORITY = "MISSING_AUTHORITY"
    MISSING_SUCCESS_METRIC = "MISSING_SUCCESS_METRIC"
    MISSING_VERIFICATION_OBLIGATION = "MISSING_VERIFICATION_OBLIGATION"
    UNRESOLVED_RISK = "UNRESOLVED_RISK"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNDERSPECIFIED_SCOPE = "UNDERSPECIFIED_SCOPE"
    UNRESOLVED_DEPENDENCY = "UNRESOLVED_DEPENDENCY"
    WORKER_DIVERGENCE = "WORKER_DIVERGENCE"
    CONTEXT_FAILURE = "CONTEXT_FAILURE"


class GapStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class Gap(FrozenModel):
    id: str
    project_id: str
    kind: GapKind
    description: str
    materiality: Materiality
    risk: RiskLevel
    affected_object_ids: tuple[str, ...]
    blocking: bool
    status: GapStatus = GapStatus.OPEN
    resolution_event_id: str | None = None

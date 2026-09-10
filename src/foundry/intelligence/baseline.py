from __future__ import annotations

from typing import Protocol

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.domain.gaps import GapKind
from foundry.intelligence.input import IntelligenceInput
from foundry.intelligence.proposals import IntelligenceUsage


class BaselineGap(FrozenModel):
    gap_id: str = Field(min_length=1)
    kind: GapKind
    subject_key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source_event_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)


class BaselinePayload(FrozenModel):
    gaps: tuple[BaselineGap, ...] = ()


class BaselineResult(FrozenModel):
    payload: BaselinePayload
    usage: IntelligenceUsage


class BaselineIntelligence(Protocol):
    def analyze(self, request: IntelligenceInput) -> BaselineResult: ...

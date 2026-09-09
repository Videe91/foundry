from __future__ import annotations

from typing import Literal

from pydantic import Field

from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.events import EventType

type SupportedIntelligenceEventType = Literal[
    EventType.USER_STATED_INTENT,
    EventType.CLAIM_INFERRED,
]


class IntelligenceSource(FrozenModel):
    event_id: str = Field(min_length=1)
    event_type: SupportedIntelligenceEventType
    content: str = Field(min_length=1)
    source_kind: SourceKind
    source_ref: str = Field(min_length=1)


class IntelligenceInput(FrozenModel):
    fixture_id: str | None
    project_id: str = Field(min_length=1)
    source_event_ids: tuple[str, ...]
    inputs: tuple[IntelligenceSource, ...]

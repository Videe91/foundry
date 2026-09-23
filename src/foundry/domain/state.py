from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from pydantic import Field, field_serializer, field_validator

from foundry.domain.common import FrozenModel
from foundry.domain.gaps import Gap
from foundry.domain.intent_synthesis_state import IntentSynthesisState
from foundry.domain.jobs import Job
from foundry.domain.semantic import SemanticObject
from foundry.domain.semantic_state import SemanticState


def _freeze_mapping[T](value: Mapping[str, T]) -> Mapping[str, T]:
    return MappingProxyType(dict(value))


class IntentState(FrozenModel):
    project_id: str
    revision: int = Field(default=0, ge=0)
    last_sequence: int = Field(default=0, ge=0)
    source_events: tuple[str, ...] = ()
    objects: Mapping[str, SemanticObject] = Field(default_factory=dict)
    gaps: Mapping[str, Gap] = Field(default_factory=dict)
    jobs: Mapping[str, Job] = Field(default_factory=dict)
    closed_scopes: Mapping[str, int] = Field(default_factory=dict)
    semantic: SemanticState = Field(default_factory=SemanticState)
    intent_synthesis: IntentSynthesisState = Field(default_factory=IntentSynthesisState)
    """The Intent Synthesis lifecycle projection (T4).

    Additive and defaulted empty, exactly as ``semantic`` was added, so every historical
    event stream replays unchanged.
    """

    @field_validator("objects", mode="after")
    @classmethod
    def freeze_objects(cls, value: Mapping[str, SemanticObject]) -> Mapping[str, SemanticObject]:
        return _freeze_mapping(value)

    @field_validator("gaps", mode="after")
    @classmethod
    def freeze_gaps(cls, value: Mapping[str, Gap]) -> Mapping[str, Gap]:
        return _freeze_mapping(value)

    @field_validator("jobs", mode="after")
    @classmethod
    def freeze_jobs(cls, value: Mapping[str, Job]) -> Mapping[str, Job]:
        return _freeze_mapping(value)

    @field_validator("closed_scopes", mode="after")
    @classmethod
    def freeze_closed_scopes(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        return _freeze_mapping(value)

    @field_serializer("objects", "gaps", "jobs", "closed_scopes")
    def serialize_mappings(self, value: Mapping[str, object]) -> dict[str, object]:
        return dict(value)

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.domain.gaps import Gap
from foundry.domain.jobs import Job
from foundry.domain.semantic import SemanticObject


class IntentState(FrozenModel):
    project_id: str = Field(min_length=1)
    revision: int = Field(default=0, ge=0)
    last_sequence: int = Field(default=0, ge=0)
    source_events: tuple[str, ...] = ()
    objects: dict[str, SemanticObject] = Field(default_factory=dict)
    gaps: dict[str, Gap] = Field(default_factory=dict)
    jobs: dict[str, Job] = Field(default_factory=dict)
    closed_scopes: dict[str, int] = Field(default_factory=dict)

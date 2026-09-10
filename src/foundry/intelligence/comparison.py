from __future__ import annotations

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.domain.gaps import GapKind
from foundry.intelligence.baseline import BaselineGap, BaselineResult
from foundry.intelligence.proposals import GapProposal, IntentIntelligenceResult


class BlindPrediction(FrozenModel):
    prediction_id: str = Field(min_length=1)
    kind: GapKind
    subject_key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source_event_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)


def neutralize_foundry(result: IntentIntelligenceResult) -> tuple[BlindPrediction, ...]:
    return tuple(
        _blind(index, gap) for index, gap in enumerate(result.payload.gap_proposals, start=1)
    )


def neutralize_baseline(result: BaselineResult) -> tuple[BlindPrediction, ...]:
    return tuple(_blind(index, gap) for index, gap in enumerate(result.payload.gaps, start=1))


def _blind(index: int, gap: GapProposal | BaselineGap) -> BlindPrediction:
    return BlindPrediction(
        prediction_id=f"P-{index:03d}",
        kind=gap.kind,
        subject_key=gap.subject_key,
        description=gap.description,
        source_event_ids=gap.source_event_ids,
        confidence=gap.confidence,
    )

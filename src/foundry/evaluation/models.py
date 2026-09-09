from __future__ import annotations

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.events import EventEnvelope
from foundry.domain.gaps import GapKind


class EvalInput(FrozenModel):
    fixture_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    events: tuple[EventEnvelope, ...]
    artifact_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def events_must_match_project(self) -> EvalInput:
        mismatched = [
            event.event_id for event in self.events if event.project_id != self.project_id
        ]
        if mismatched:
            raise ValueError(f"events {tuple(mismatched)} do not match project {self.project_id}")
        return self


class ExpectedGap(FrozenModel):
    fingerprint: str = Field(min_length=1)
    kind: GapKind
    critical: bool


class EvalExpectation(FrozenModel):
    expected_gaps: tuple[ExpectedGap, ...]
    forbidden_gap_fingerprints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def fingerprints_must_be_unique_and_disjoint(self) -> EvalExpectation:
        expected = tuple(gap.fingerprint for gap in self.expected_gaps)
        forbidden = self.forbidden_gap_fingerprints
        _reject_duplicates("expected_gaps", expected)
        _reject_duplicates("forbidden_gap_fingerprints", forbidden)
        overlap = set(expected) & set(forbidden)
        if overlap:
            raise ValueError(
                f"expected and forbidden fingerprints overlap: {tuple(sorted(overlap))}"
            )
        return self


class PredictedGap(FrozenModel):
    fingerprint: str = Field(min_length=1)
    kind: GapKind


class EvalCost(FrozenModel):
    deterministic_jobs: int = Field(default=0, ge=0)
    cheap_model_jobs: int = Field(default=0, ge=0)
    standard_model_jobs: int = Field(default=0, ge=0)
    strong_model_jobs: int = Field(default=0, ge=0)
    frontier_model_jobs: int = Field(default=0, ge=0)
    human_escalations: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    wall_clock_ms: int = Field(default=0, ge=0)


class EvalPrediction(FrozenModel):
    gaps: tuple[PredictedGap, ...]
    cost: EvalCost = Field(default_factory=EvalCost)

    @model_validator(mode="after")
    def predicted_fingerprints_must_be_unique(self) -> EvalPrediction:
        _reject_duplicates("gaps", tuple(gap.fingerprint for gap in self.gaps))
        return self


class EvalScore(FrozenModel):
    critical_gaps_detected: int = Field(ge=0)
    critical_gaps_missed: int = Field(ge=0)
    noncritical_gaps_detected: int = Field(ge=0)
    noncritical_gaps_missed: int = Field(ge=0)
    false_gaps: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    cost: EvalCost


def _reject_duplicates(label: str, fingerprints: tuple[str, ...]) -> None:
    if len(fingerprints) != len(set(fingerprints)):
        raise ValueError(f"{label} fingerprints must be unique")

from __future__ import annotations

from foundry.domain.common import SourceKind
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    SemanticObjectPayload,
    UserStatedIntentPayload,
)
from foundry.domain.semantic import Claim
from foundry.evaluation.models import EvalInput
from foundry.intelligence.input import IntelligenceInput, IntelligenceSource


def compile_intelligence_input(eval_input: EvalInput) -> IntelligenceInput:
    sources = tuple(_compile_source(event) for event in eval_input.events)
    return IntelligenceInput(
        fixture_id=eval_input.fixture_id,
        project_id=eval_input.project_id,
        source_event_ids=tuple(event.event_id for event in eval_input.events),
        inputs=sources,
    )


def _compile_source(event: EventEnvelope) -> IntelligenceSource:
    if event.event_type is EventType.USER_STATED_INTENT:
        payload = event.payload
        if not isinstance(payload, UserStatedIntentPayload):
            raise ValueError("USER_STATED_INTENT requires UserStatedIntentPayload")
        return IntelligenceSource(
            event_id=event.event_id,
            event_type=EventType.USER_STATED_INTENT,
            content=payload.text,
            source_kind=SourceKind.HUMAN,
            source_ref=payload.actor_id,
        )
    if event.event_type is EventType.CLAIM_INFERRED:
        payload = event.payload
        if not isinstance(payload, SemanticObjectPayload) or not isinstance(payload.object, Claim):
            raise ValueError("CLAIM_INFERRED requires a Claim")
        claim = payload.object
        return IntelligenceSource(
            event_id=event.event_id,
            event_type=EventType.CLAIM_INFERRED,
            content=claim.statement,
            source_kind=claim.provenance.source_kind,
            source_ref=claim.provenance.source_ref,
        )
    raise ValueError(f"Unsupported intelligence event type: {event.event_type}")

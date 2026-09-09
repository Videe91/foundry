from datetime import UTC, datetime

import pytest

from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.events import EventEnvelope, EventType, SemanticObjectPayload, parse_event
from foundry.domain.semantic import Claim


def make_claim() -> Claim:
    return Claim(
        id="CLAIM-1",
        project_id="PROJ-1",
        statement="Retries are three.",
        authority=Authority.INFERRED,
        confidence=0.9,
        provenance=Provenance(
            source_kind=SourceKind.CODE,
            source_ref="repo://svc/retry.py#L1-L5",
            source_event_ids=("EVT-1",),
        ),
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
    )


def test_event_round_trip_preserves_typed_semantic_payload() -> None:
    event = EventEnvelope(
        event_id="EVT-2",
        project_id="PROJ-1",
        event_type=EventType.CLAIM_INFERRED,
        occurred_at=datetime(2026, 9, 9, tzinfo=UTC),
        payload=SemanticObjectPayload(object=make_claim()),
    )

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert isinstance(restored.payload, SemanticObjectPayload)
    assert isinstance(restored.payload.object, Claim)


def test_parse_event_rejects_payload_that_does_not_match_event_type() -> None:
    raw = {
        "event_id": "EVT-3",
        "project_id": "PROJ-1",
        "event_type": "CLAIM_INFERRED",
        "occurred_at": "2026-09-09T00:00:00Z",
        "payload": {"text": "raw user intent", "actor_id": "OWNER"},
    }

    with pytest.raises(ValueError, match="payload"):
        parse_event(raw)

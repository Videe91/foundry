from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from foundry.domain.events import EventEnvelope, StoredEvent, parse_event
from foundry.ports.event_store import ConcurrencyError, DuplicateEventError


class PostgresEventStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent:
        document = json.dumps(event.model_dump(mode="json"))
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO intent_event_streams (project_id, current_sequence)
                    VALUES (:project_id, 0)
                    ON CONFLICT (project_id) DO NOTHING
                    """
                ),
                {"project_id": event.project_id},
            )
            current_sequence = connection.execute(
                text(
                    """
                    SELECT current_sequence
                    FROM intent_event_streams
                    WHERE project_id = :project_id
                    FOR UPDATE
                    """
                ),
                {"project_id": event.project_id},
            ).scalar_one()
            existing = connection.execute(
                text("SELECT 1 FROM intent_events WHERE event_id = :event_id"),
                {"event_id": event.event_id},
            ).first()
            if existing is not None:
                raise DuplicateEventError(f"event_id {event.event_id} already exists")
            if current_sequence != expected_sequence:
                raise ConcurrencyError(
                    "project "
                    f"{event.project_id} expected {expected_sequence} actual {current_sequence}"
                )
            next_sequence = expected_sequence + 1
            try:
                connection.execute(
                    text(
                        """
                        INSERT INTO intent_events (
                            project_id,
                            sequence,
                            event_id,
                            event_type,
                            occurred_at,
                            event_document
                        )
                        VALUES (
                            :project_id,
                            :sequence,
                            :event_id,
                            :event_type,
                            :occurred_at,
                            CAST(:event_document AS jsonb)
                        )
                        """
                    ),
                    {
                        "project_id": event.project_id,
                        "sequence": next_sequence,
                        "event_id": event.event_id,
                        "event_type": event.event_type.value,
                        "occurred_at": event.occurred_at,
                        "event_document": document,
                    },
                )
            except IntegrityError as exc:
                if _is_duplicate_event_id(exc):
                    raise DuplicateEventError(f"event_id {event.event_id} already exists") from exc
                raise
            connection.execute(
                text(
                    """
                    UPDATE intent_event_streams
                    SET current_sequence = :sequence
                    WHERE project_id = :project_id
                    """
                ),
                {"project_id": event.project_id, "sequence": next_sequence},
            )
            return StoredEvent(sequence=next_sequence, event=event)

    def load(self, project_id: str, after_sequence: int = 0) -> Sequence[StoredEvent]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT sequence, event_document
                    FROM intent_events
                    WHERE project_id = :project_id AND sequence > :after_sequence
                    ORDER BY sequence ASC
                    """
                ),
                {"project_id": project_id, "after_sequence": after_sequence},
            ).all()
        return tuple(
            StoredEvent(
                sequence=int(row.sequence),
                event=parse_event(_as_mapping(row.event_document)),
            )
            for row in rows
        )

    def current_sequence(self, project_id: str) -> int:
        with self._engine.connect() as connection:
            value = connection.execute(
                text(
                    """
                    SELECT current_sequence
                    FROM intent_event_streams
                    WHERE project_id = :project_id
                    """
                ),
                {"project_id": project_id},
            ).scalar_one_or_none()
        return 0 if value is None else int(value)


def _as_mapping(document: object) -> Mapping[str, object]:
    if isinstance(document, str):
        loaded = json.loads(document)
        if isinstance(loaded, dict):
            return loaded
        raise TypeError("event_document JSON must be an object")
    if isinstance(document, Mapping):
        return document
    raise TypeError(f"unsupported event_document type: {type(document).__name__}")


def _is_duplicate_event_id(exc: IntegrityError) -> bool:
    orig = exc.orig
    constraint_name = getattr(getattr(orig, "diag", None), "constraint_name", None)
    return constraint_name == "uq_intent_events_event_id"

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from foundry.domain.events import EventEnvelope, StoredEvent, parse_event
from foundry.ports.event_store import ConcurrencyError, DuplicateEventError


class PostgresEventStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent:
        if expected_sequence < 0:
            raise ValueError("expected_sequence must be non-negative")

        try:
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

                if int(current_sequence) != expected_sequence:
                    raise ConcurrencyError(
                        f"expected sequence {expected_sequence}, found {current_sequence}"
                    )

                next_sequence = expected_sequence + 1
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
                        ) VALUES (
                            :project_id,
                            :sequence,
                            :event_id,
                            :event_type,
                            :occurred_at,
                            CAST(:event_document AS JSONB)
                        )
                        """
                    ),
                    {
                        "project_id": event.project_id,
                        "sequence": next_sequence,
                        "event_id": event.event_id,
                        "event_type": event.event_type.value,
                        "occurred_at": event.occurred_at,
                        "event_document": json.dumps(event.model_dump(mode="json")),
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE intent_event_streams
                        SET current_sequence = :next_sequence
                        WHERE project_id = :project_id
                        """
                    ),
                    {"next_sequence": next_sequence, "project_id": event.project_id},
                )
        except IntegrityError as exc:
            raise DuplicateEventError(f"event ID already exists: {event.event_id}") from exc

        return StoredEvent(sequence=next_sequence, event=event)

    def load(self, project_id: str, after_sequence: int = 0) -> Sequence[StoredEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")

        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT sequence, event_document
                    FROM intent_events
                    WHERE project_id = :project_id
                      AND sequence > :after_sequence
                    ORDER BY sequence ASC
                    """
                ),
                {"project_id": project_id, "after_sequence": after_sequence},
            ).mappings()
            return tuple(
                StoredEvent(
                    sequence=int(row["sequence"]),
                    event=parse_event(self._document(row["event_document"])),
                )
                for row in rows
            )

    def current_sequence(self, project_id: str) -> int:
        with self._engine.connect() as connection:
            sequence = connection.execute(
                text(
                    """
                    SELECT current_sequence
                    FROM intent_event_streams
                    WHERE project_id = :project_id
                    """
                ),
                {"project_id": project_id},
            ).scalar_one_or_none()
        return 0 if sequence is None else int(sequence)

    @staticmethod
    def _document(value: Any) -> dict[str, object]:
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError("stored event document must be an object")
            return parsed
        if isinstance(value, dict):
            return value
        raise ValueError("stored event document must be a JSON object")

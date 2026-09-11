"""In-memory ``EventStore`` adapter.

Architectural role: a persistence adapter with the same contract and semantics
as ``foundry.adapters.postgres.event_store.PostgresEventStore``, held entirely
in process memory. It exists so application-layer orchestration and lifecycle
tests can run the real event-sourced story (append -> load -> replay) with zero
external services. It is not a second ledger: the same ``EventEnvelope`` and
``StoredEvent`` types flow through it, and the same reducer consumes its output.

Semantics mirrored from the Postgres adapter:

* Sequences are per project and start at 0; ``current_sequence`` of an unknown
  project is 0.
* ``event_id`` is unique across *all* projects; a repeat raises
  ``DuplicateEventError``.
* ``append`` checks for a duplicate ``event_id`` before checking
  ``expected_sequence``; a mismatch raises ``ConcurrencyError``.
* ``load`` returns events with ``sequence > after_sequence`` in ascending order
  as an immutable snapshot.
* Every stored event is round-tripped through its JSON document
  (``model_dump(mode="json")`` -> ``parse_event``) exactly as Postgres does, so a
  payload that cannot survive serialization fails here too, never only in
  production.

Storage technology is replaceable; the semantic contract is not.
"""

from __future__ import annotations

from collections.abc import Sequence

from foundry.domain.events import EventEnvelope, StoredEvent, parse_event
from foundry.ports.event_store import ConcurrencyError, DuplicateEventError


class InMemoryEventStore:
    def __init__(self) -> None:
        self._streams: dict[str, list[StoredEvent]] = {}
        self._event_ids: set[str] = set()

    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent:
        stream = self._streams.setdefault(event.project_id, [])
        current_sequence = len(stream)
        if event.event_id in self._event_ids:
            raise DuplicateEventError(f"event_id {event.event_id} already exists")
        if current_sequence != expected_sequence:
            raise ConcurrencyError(
                f"project {event.project_id} expected {expected_sequence} actual {current_sequence}"
            )
        document = event.model_dump(mode="json")
        stored = StoredEvent(sequence=expected_sequence + 1, event=parse_event(document))
        stream.append(stored)
        self._event_ids.add(event.event_id)
        return stored

    def load(self, project_id: str, after_sequence: int = 0) -> Sequence[StoredEvent]:
        stream = self._streams.get(project_id, [])
        return tuple(stored for stored in stream if stored.sequence > after_sequence)

    def current_sequence(self, project_id: str) -> int:
        return len(self._streams.get(project_id, []))

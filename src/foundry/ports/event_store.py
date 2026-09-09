from collections.abc import Sequence
from typing import Protocol

from foundry.domain.events import EventEnvelope, StoredEvent


class ConcurrencyError(RuntimeError):
    pass


class DuplicateEventError(RuntimeError):
    pass


class EventStore(Protocol):
    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent: ...

    def load(self, project_id: str, after_sequence: int = 0) -> Sequence[StoredEvent]: ...

    def current_sequence(self, project_id: str) -> int: ...

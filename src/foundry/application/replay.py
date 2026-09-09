from __future__ import annotations

from collections.abc import Iterable

from foundry.application.reducer import reduce_event
from foundry.domain.events import StoredEvent
from foundry.domain.state import IntentState


def replay(project_id: str, events: Iterable[StoredEvent]) -> IntentState:
    state = IntentState(project_id=project_id)
    for stored_event in events:
        state = reduce_event(state, stored_event)
    return state

from datetime import UTC, datetime

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.domain.events import EventEnvelope, EventType, StoredEvent, UserStatedIntentPayload
from foundry.ports.event_store import ConcurrencyError, DuplicateEventError, EventStore

OCCURRED_AT = datetime(2026, 9, 9, tzinfo=UTC)


def _event(*, event_id: str, project_id: str = "PROJ-1", text: str = "Fast.") -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        project_id=project_id,
        event_type=EventType.USER_STATED_INTENT,
        occurred_at=OCCURRED_AT,
        payload=UserStatedIntentPayload(text=text, actor_id="human://alice"),
    )


def test_satisfies_event_store_protocol() -> None:
    store: EventStore = InMemoryEventStore()
    assert store.current_sequence("PROJ-1") == 0


def test_unknown_project_has_sequence_zero_and_no_events() -> None:
    store = InMemoryEventStore()
    assert store.current_sequence("PROJ-NONE") == 0
    assert tuple(store.load("PROJ-NONE")) == ()


def test_append_returns_stored_event_with_next_sequence() -> None:
    store = InMemoryEventStore()
    first = _event(event_id="EVT-1")
    stored = store.append(first, expected_sequence=0)
    assert stored == StoredEvent(sequence=1, event=first)
    assert store.current_sequence("PROJ-1") == 1


def test_append_load_round_trip_preserves_order() -> None:
    store = InMemoryEventStore()
    first = _event(event_id="EVT-1", text="one")
    second = _event(event_id="EVT-2", text="two")
    third = _event(event_id="EVT-3", text="three")
    store.append(first, expected_sequence=0)
    store.append(second, expected_sequence=1)
    store.append(third, expected_sequence=2)

    loaded = tuple(store.load("PROJ-1"))

    assert loaded == (
        StoredEvent(sequence=1, event=first),
        StoredEvent(sequence=2, event=second),
        StoredEvent(sequence=3, event=third),
    )
    assert store.current_sequence("PROJ-1") == 3


def test_load_after_sequence_skips_earlier_events() -> None:
    store = InMemoryEventStore()
    first = _event(event_id="EVT-1", text="one")
    second = _event(event_id="EVT-2", text="two")
    third = _event(event_id="EVT-3", text="three")
    store.append(first, expected_sequence=0)
    store.append(second, expected_sequence=1)
    store.append(third, expected_sequence=2)

    assert tuple(store.load("PROJ-1", after_sequence=1)) == (
        StoredEvent(sequence=2, event=second),
        StoredEvent(sequence=3, event=third),
    )
    assert tuple(store.load("PROJ-1", after_sequence=3)) == ()


def test_wrong_expected_sequence_raises_concurrency_error() -> None:
    store = InMemoryEventStore()
    store.append(_event(event_id="EVT-1"), expected_sequence=0)

    with pytest.raises(ConcurrencyError, match="expected 0 actual 1"):
        store.append(_event(event_id="EVT-2"), expected_sequence=0)

    with pytest.raises(ConcurrencyError, match="expected 5 actual 1"):
        store.append(_event(event_id="EVT-3"), expected_sequence=5)

    assert store.current_sequence("PROJ-1") == 1
    assert len(store.load("PROJ-1")) == 1


def test_wrong_expected_sequence_on_unknown_project_raises_concurrency_error() -> None:
    store = InMemoryEventStore()
    with pytest.raises(ConcurrencyError):
        store.append(_event(event_id="EVT-1"), expected_sequence=1)
    assert store.current_sequence("PROJ-1") == 0
    assert tuple(store.load("PROJ-1")) == ()


def test_duplicate_event_id_raises_duplicate_error() -> None:
    store = InMemoryEventStore()
    store.append(_event(event_id="EVT-1"), expected_sequence=0)

    with pytest.raises(DuplicateEventError, match="EVT-1"):
        store.append(_event(event_id="EVT-1", text="again"), expected_sequence=1)

    assert store.current_sequence("PROJ-1") == 1
    assert len(store.load("PROJ-1")) == 1


def test_duplicate_event_id_is_rejected_across_projects() -> None:
    store = InMemoryEventStore()
    store.append(_event(event_id="EVT-1", project_id="PROJ-A"), expected_sequence=0)

    with pytest.raises(DuplicateEventError):
        store.append(_event(event_id="EVT-1", project_id="PROJ-B"), expected_sequence=0)

    assert store.current_sequence("PROJ-B") == 0
    assert tuple(store.load("PROJ-B")) == ()


def test_duplicate_check_precedes_concurrency_check() -> None:
    store = InMemoryEventStore()
    store.append(_event(event_id="EVT-1"), expected_sequence=0)

    with pytest.raises(DuplicateEventError):
        store.append(_event(event_id="EVT-1"), expected_sequence=99)


def test_projects_have_independent_sequences() -> None:
    store = InMemoryEventStore()
    a1 = _event(event_id="EVT-A1", project_id="PROJ-A")
    b1 = _event(event_id="EVT-B1", project_id="PROJ-B")
    a2 = _event(event_id="EVT-A2", project_id="PROJ-A")

    assert store.append(a1, expected_sequence=0).sequence == 1
    assert store.append(b1, expected_sequence=0).sequence == 1
    assert store.append(a2, expected_sequence=1).sequence == 2

    assert store.current_sequence("PROJ-A") == 2
    assert store.current_sequence("PROJ-B") == 1
    assert tuple(store.load("PROJ-A")) == (
        StoredEvent(sequence=1, event=a1),
        StoredEvent(sequence=2, event=a2),
    )
    assert tuple(store.load("PROJ-B")) == (StoredEvent(sequence=1, event=b1),)


def test_load_returns_a_snapshot_not_a_live_view() -> None:
    store = InMemoryEventStore()
    store.append(_event(event_id="EVT-1"), expected_sequence=0)
    before = tuple(store.load("PROJ-1"))
    store.append(_event(event_id="EVT-2"), expected_sequence=1)
    assert len(before) == 1
    assert len(store.load("PROJ-1")) == 2


def test_stores_are_isolated_instances() -> None:
    first = InMemoryEventStore()
    second = InMemoryEventStore()
    first.append(_event(event_id="EVT-1"), expected_sequence=0)
    assert second.current_sequence("PROJ-1") == 0
    second.append(_event(event_id="EVT-1"), expected_sequence=0)
    assert second.current_sequence("PROJ-1") == 1

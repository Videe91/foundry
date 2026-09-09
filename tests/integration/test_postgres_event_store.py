from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from foundry.adapters.postgres.database import create_database_engine
from foundry.adapters.postgres.event_store import PostgresEventStore
from foundry.domain.events import EventEnvelope, EventType, UserStatedIntentPayload
from foundry.ports.event_store import ConcurrencyError, DuplicateEventError, EventStore


def _event(event_id: str, project_id: str = "PROJ-1") -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        project_id=project_id,
        event_type=EventType.USER_STATED_INTENT,
        occurred_at=datetime(2026, 9, 9, tzinfo=UTC),
        payload=UserStatedIntentPayload(text="Need login.", actor_id="OWNER"),
    )


def _upgrade(database_url: str) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def test_unknown_project_current_sequence_is_zero_and_first_append_round_trips() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        store = PostgresEventStore(create_database_engine(database_url))
        event = _event("EVT-1")

        assert store.current_sequence("PROJ-1") == 0
        stored = store.append(event, expected_sequence=0)

        assert stored.sequence == 1
        loaded = store.load("PROJ-1")
        assert len(loaded) == 1
        assert loaded[0].event == event
        assert store.current_sequence("PROJ-1") == 1


def test_stale_expected_sequence_raises_concurrency_error_and_does_not_write() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        store = PostgresEventStore(create_database_engine(database_url))
        first = _event("EVT-1")
        second = _event("EVT-2")

        stored = store.append(first, expected_sequence=0)
        assert stored.sequence == 1
        with pytest.raises(ConcurrencyError, match="project PROJ-1 expected 0 actual 1"):
            store.append(second, expected_sequence=0)

        assert store.current_sequence("PROJ-1") == 1
        loaded = store.load("PROJ-1")
        assert [item.event.event_id for item in loaded] == ["EVT-1"]
        assert loaded[0].event == first


def test_duplicate_event_id_with_next_sequence_raises_duplicate_error() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        store = PostgresEventStore(create_database_engine(database_url))
        event = _event("EVT-1")

        store.append(event, expected_sequence=0)
        with pytest.raises(DuplicateEventError, match="event_id EVT-1 already exists"):
            store.append(event, expected_sequence=1)

        assert store.current_sequence("PROJ-1") == 1
        loaded = store.load("PROJ-1")
        assert len(loaded) == 1
        assert loaded[0].event == event


def test_duplicate_event_id_takes_precedence_over_stale_sequence() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        store = PostgresEventStore(create_database_engine(database_url))
        event = _event("EVT-1")

        store.append(event, expected_sequence=0)
        with pytest.raises(DuplicateEventError, match="event_id EVT-1 already exists"):
            store.append(event, expected_sequence=0)

        assert store.current_sequence("PROJ-1") == 1


def test_intent_events_rejects_update_delete_and_truncate() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        engine = create_database_engine(database_url)
        store = PostgresEventStore(engine)
        event = _event("EVT-1")
        store.append(event, expected_sequence=0)

        with (
            engine.connect() as connection,
            pytest.raises(Exception, match="intent_events is append-only"),
        ):
            connection.execute(text("UPDATE intent_events SET event_type = 'TAMPERED'"))
            connection.commit()
        with (
            engine.connect() as connection,
            pytest.raises(Exception, match="intent_events is append-only"),
        ):
            connection.execute(text("DELETE FROM intent_events"))
            connection.commit()
        with (
            engine.connect() as connection,
            pytest.raises(Exception, match="intent_events is append-only"),
        ):
            connection.execute(text("TRUNCATE intent_events"))
            connection.commit()

        loaded = store.load("PROJ-1")
        assert len(loaded) == 1
        assert loaded[0].event == event


def test_projects_have_independent_sequences() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        store = PostgresEventStore(create_database_engine(database_url))

        first = store.append(_event("EVT-A", project_id="PROJ-A"), expected_sequence=0)
        second = store.append(_event("EVT-B", project_id="PROJ-B"), expected_sequence=0)

        assert first.sequence == 1
        assert second.sequence == 1
        assert store.current_sequence("PROJ-A") == 1
        assert store.current_sequence("PROJ-B") == 1


def test_load_returns_events_in_ascending_sequence_and_honors_after_sequence() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        store = PostgresEventStore(create_database_engine(database_url))
        events = [_event(f"EVT-{index}") for index in (1, 2, 3)]
        for index, event in enumerate(events):
            store.append(event, expected_sequence=index)

        loaded = store.load("PROJ-1")
        assert [item.sequence for item in loaded] == [1, 2, 3]
        assert [item.event for item in loaded] == events

        after_first = store.load("PROJ-1", after_sequence=1)
        assert [item.sequence for item in after_first] == [2, 3]
        assert [item.event for item in after_first] == events[1:]


def test_unknown_project_current_sequence_does_not_create_a_stream() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        engine = create_database_engine(database_url)
        store = PostgresEventStore(engine)

        assert store.current_sequence("UNKNOWN") == 0
        with engine.connect() as connection:
            count = connection.execute(
                text("SELECT count(*) FROM intent_event_streams")
            ).scalar_one()
        assert count == 0


def test_stale_first_write_does_not_leave_a_phantom_stream() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        store = PostgresEventStore(create_database_engine(database_url))
        event = _event("EVT-5", project_id="PROJ-NEW")

        with pytest.raises(ConcurrencyError, match="project PROJ-NEW expected 5 actual 0"):
            store.append(event, expected_sequence=5)

        assert store.current_sequence("PROJ-NEW") == 0
        assert store.load("PROJ-NEW") == ()


def test_event_store_exposes_no_history_mutation_api() -> None:
    forbidden = {"update", "delete", "replace", "truncate"}
    assert forbidden.isdisjoint(set(dir(EventStore)))
    assert forbidden.isdisjoint(set(dir(PostgresEventStore)))

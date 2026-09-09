from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

from foundry.adapters.postgres.database import create_database_engine
from foundry.adapters.postgres.event_store import PostgresEventStore
from foundry.domain.events import EventEnvelope, EventType, UserStatedIntentPayload
from foundry.ports.event_store import ConcurrencyError, DuplicateEventError


def _database_url(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("+psycopg2", "+psycopg")


def _migrate(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _event(event_id: str, text: str = "Build the system.") -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        project_id="PROJ-STORE",
        event_type=EventType.USER_STATED_INTENT,
        occurred_at=datetime(2026, 9, 9, tzinfo=UTC),
        payload=UserStatedIntentPayload(text=text, actor_id="OWNER"),
    )


def test_postgres_event_store_is_append_only_and_concurrency_safe() -> None:
    with PostgresContainer("postgres:16-alpine") as postgres:
        database_url = _database_url(postgres)
        _migrate(database_url)
        engine = create_database_engine(database_url)
        store = PostgresEventStore(engine)

        first = store.append(_event("EVT-1"), expected_sequence=0)
        second = store.append(_event("EVT-2", "Make it reliable."), expected_sequence=1)

        assert first.sequence == 1
        assert second.sequence == 2
        assert store.current_sequence("PROJ-STORE") == 2
        assert [item.event.event_id for item in store.load("PROJ-STORE")] == ["EVT-1", "EVT-2"]

        with pytest.raises(ConcurrencyError):
            store.append(_event("EVT-3"), expected_sequence=0)

        with pytest.raises(DuplicateEventError):
            store.append(_event("EVT-1", "Duplicate."), expected_sequence=2)

        assert store.current_sequence("PROJ-STORE") == 2
        assert [item.sequence for item in store.load("PROJ-STORE")] == [1, 2]

        engine.dispose()

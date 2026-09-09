from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_event_streams"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intent_event_streams",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("current_sequence", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("current_sequence >= 0"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "intent_events",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("sequence >= 1"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["intent_event_streams.project_id"],
        ),
        sa.PrimaryKeyConstraint("project_id", "sequence"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_intent_events_project_type",
        "intent_events",
        ["project_id", "event_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_intent_events_project_type", table_name="intent_events")
    op.drop_table("intent_events")
    op.drop_table("intent_event_streams")

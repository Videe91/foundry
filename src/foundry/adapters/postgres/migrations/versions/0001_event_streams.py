"""Create append-only intent event streams."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_event_streams"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intent_event_streams",
        sa.Column("project_id", sa.Text(), primary_key=True),
        sa.Column("current_sequence", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "current_sequence >= 0",
            name="ck_intent_event_streams_current_sequence",
        ),
    )
    op.create_table(
        "intent_events",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("event_document", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("project_id", "sequence"),
        sa.ForeignKeyConstraint(["project_id"], ["intent_event_streams.project_id"]),
        sa.UniqueConstraint("event_id", name="uq_intent_events_event_id"),
        sa.CheckConstraint("sequence >= 1", name="ck_intent_events_sequence"),
    )
    op.create_index(
        "ix_intent_events_project_type",
        "intent_events",
        ["project_id", "event_type"],
    )
    op.execute(
        """
        CREATE FUNCTION foundry_reject_intent_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'intent_events is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_intent_events_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON intent_events
        FOR EACH STATEMENT
        EXECUTE FUNCTION foundry_reject_intent_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_intent_events_append_only ON intent_events")
    op.execute("DROP FUNCTION IF EXISTS foundry_reject_intent_event_mutation()")
    op.drop_index("ix_intent_events_project_type", table_name="intent_events")
    op.drop_table("intent_events")
    op.drop_table("intent_event_streams")

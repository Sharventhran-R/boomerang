"""phase_7_4_consumer_events

Revision ID: f99144acbb2a
Revises: a4d442db2420
Create Date: 2026-10-18 22:33:34.351055

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f99144acbb2a"
down_revision: str | Sequence[str] | None = "a4d442db2420"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consumer_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("consumer_name", sa.String(length=100), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", sa.UUID(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("partition", sa.Integer(), nullable=False),
        sa.Column("offset", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PROCESSING",
                "COMPLETED",
                "FAILED",
                "QUARANTINED",
                name="consumer_event_status_enum",
            ),
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(length=50), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "consumer_name",
            "event_id",
            name="uq_consumer_events_consumer_event",
        ),
    )
    op.create_index(
        op.f("ix_consumer_events_aggregate_id"),
        "consumer_events",
        ["aggregate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consumer_events_consumer_name"),
        "consumer_events",
        ["consumer_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consumer_events_created_at"),
        "consumer_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consumer_events_event_id"),
        "consumer_events",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consumer_events_event_type"),
        "consumer_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consumer_events_status"),
        "consumer_events",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_consumer_events_status_retry",
        "consumer_events",
        ["consumer_name", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_consumer_events_topic_partition_offset",
        "consumer_events",
        ["topic", "partition", "offset"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_consumer_events_topic_partition_offset", table_name="consumer_events"
    )
    op.drop_index("ix_consumer_events_status_retry", table_name="consumer_events")
    op.drop_index(op.f("ix_consumer_events_status"), table_name="consumer_events")
    op.drop_index(op.f("ix_consumer_events_event_type"), table_name="consumer_events")
    op.drop_index(op.f("ix_consumer_events_event_id"), table_name="consumer_events")
    op.drop_index(op.f("ix_consumer_events_created_at"), table_name="consumer_events")
    op.drop_index(
        op.f("ix_consumer_events_consumer_name"), table_name="consumer_events"
    )
    op.drop_index(op.f("ix_consumer_events_aggregate_id"), table_name="consumer_events")
    op.drop_table("consumer_events")
    sa.Enum(name="consumer_event_status_enum").drop(op.get_bind(), checkfirst=True)

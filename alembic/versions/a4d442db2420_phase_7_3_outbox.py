"""phase_7_3_outbox

Revision ID: a4d442db2420
Revises: 491e9669403b
Create Date: 2026-10-18 21:22:20.045061

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4d442db2420"
down_revision: str | Sequence[str] | None = "491e9669403b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", sa.UUID(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PROCESSING",
                "PUBLISHED",
                "FAILED",
                "DEAD_LETTER",
                name="outbox_status_enum",
            ),
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbox_events_aggregate",
        "outbox_events",
        ["aggregate_type", "aggregate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_aggregate_id"),
        "outbox_events",
        ["aggregate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_aggregate_type"),
        "outbox_events",
        ["aggregate_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_created_at"),
        "outbox_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_event_id"),
        "outbox_events",
        ["event_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_outbox_events_event_type"),
        "outbox_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_status"),
        "outbox_events",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_events_status_next_retry",
        "outbox_events",
        ["status", "next_retry_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_next_retry", table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_status"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_event_type"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_event_id"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_created_at"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_aggregate_type"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_aggregate_id"), table_name="outbox_events")
    op.drop_index("ix_outbox_events_aggregate", table_name="outbox_events")
    op.drop_table("outbox_events")
    sa.Enum(name="outbox_status_enum").drop(op.get_bind(), checkfirst=True)

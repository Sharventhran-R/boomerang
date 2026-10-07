"""phase_2_domain_model

Revision ID: b3feb293d5d0
Revises:
Create Date: 2026-10-06 16:33:17.817404

"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3feb293d5d0"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Enums
    report_type_enum = postgresql.ENUM(
        "MISSING", "FOUND", name="report_type_enum", create_type=False
    )
    report_type_enum.create(op.get_bind(), checkfirst=True)

    report_category_enum = postgresql.ENUM(
        "ELECTRONICS",
        "DOCUMENT",
        "WALLET",
        "BAG",
        "KEYS",
        "JEWELRY",
        "PET",
        "VEHICLE",
        "CLOTHING",
        "OTHER",
        name="report_category_enum",
        create_type=False,
    )
    report_category_enum.create(op.get_bind(), checkfirst=True)

    report_status_enum = postgresql.ENUM(
        "ACTIVE",
        "RESOLVED",
        "EXPIRED",
        "CANCELLED",
        name="report_status_enum",
        create_type=False,
    )
    report_status_enum.create(op.get_bind(), checkfirst=True)

    recovery_request_status_enum = postgresql.ENUM(
        "PENDING",
        "ACCEPTED",
        "REJECTED",
        "CANCELLED",
        "COMPLETED",
        name="recovery_request_status_enum",
        create_type=False,
    )
    recovery_request_status_enum.create(op.get_bind(), checkfirst=True)

    # Tables
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
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
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", report_type_enum, nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", report_category_enum, nullable=False),
        sa.Column(
            "location",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                from_text="ST_GeogFromText",
                name="geography",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reward_amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column(
            "status", report_status_enum, nullable=False, server_default="ACTIVE"
        ),
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
        sa.CheckConstraint("reward_amount >= 0", name="chk_reward_amount_positive"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(op.f("ix_reports_category"), "reports", ["category"], unique=False)
    op.create_index(
        op.f("ix_reports_created_at"), "reports", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_reports_created_by_user_id"),
        "reports",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_reports_status"), "reports", ["status"], unique=False)
    op.create_index(op.f("ix_reports_type"), "reports", ["type"], unique=False)

    op.create_table(
        "report_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_url", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
    )
    op.create_index(
        op.f("ix_report_images_report_id"), "report_images", ["report_id"], unique=False
    )

    op.create_table(
        "recovery_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            recovery_request_status_enum,
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("verification_response", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "requester_id != recipient_id", name="chk_requester_not_recipient"
        ),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        op.f("ix_recovery_requests_recipient_id"),
        "recovery_requests",
        ["recipient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recovery_requests_report_id"),
        "recovery_requests",
        ["report_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recovery_requests_requester_id"),
        "recovery_requests",
        ["requester_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recovery_requests_status"),
        "recovery_requests",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("recovery_requests")
    op.drop_table("report_images")
    op.drop_table("reports")
    op.drop_table("users")

    postgresql.ENUM(name="recovery_request_status_enum").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="report_status_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="report_category_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="report_type_enum").drop(op.get_bind(), checkfirst=True)

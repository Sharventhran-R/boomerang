"""phase_9_2_notification_history_retention_fk_restrict

Revision ID: a2c41f9e0e57
Revises: edc880a835c9
Create Date: 2026-11-02 16:30:34.930889

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2c41f9e0e57"
down_revision: str | Sequence[str] | None = "edc880a835c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        "notification_deliveries_notification_id_fkey",
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "notification_deliveries_user_device_id_fkey",
        "notification_deliveries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "notification_deliveries_notification_id_fkey",
        "notification_deliveries",
        "notifications",
        ["notification_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "notification_deliveries_user_device_id_fkey",
        "notification_deliveries",
        "user_devices",
        ["user_device_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "notifications_user_id_fkey",
        "notifications",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "notifications_user_id_fkey",
        "notifications",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "user_devices_user_id_fkey",
        "user_devices",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "user_devices_user_id_fkey",
        "user_devices",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "user_devices_user_id_fkey",
        "user_devices",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "user_devices_user_id_fkey",
        "user_devices",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "notifications_user_id_fkey",
        "notifications",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "notifications_user_id_fkey",
        "notifications",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "notification_deliveries_user_device_id_fkey",
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "notification_deliveries_notification_id_fkey",
        "notification_deliveries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "notification_deliveries_user_device_id_fkey",
        "notification_deliveries",
        "user_devices",
        ["user_device_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "notification_deliveries_notification_id_fkey",
        "notification_deliveries",
        "notifications",
        ["notification_id"],
        ["id"],
        ondelete="CASCADE",
    )

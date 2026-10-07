"""phase_4_report_images

Revision ID: 491e9669403b
Revises: e721eeb62d8b
Create Date: 2026-10-07 16:15:44.709177

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "491e9669403b"
down_revision: str | Sequence[str] | None = "e721eeb62d8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM report_images")
    op.add_column("report_images", sa.Column("object_key", sa.String(), nullable=False))
    op.add_column(
        "report_images", sa.Column("content_type", sa.String(), nullable=False)
    )
    op.add_column("report_images", sa.Column("file_size", sa.Integer(), nullable=False))
    op.drop_column("report_images", "image_url")


def downgrade() -> None:
    op.add_column(
        "report_images",
        sa.Column("image_url", sa.VARCHAR(), autoincrement=False, nullable=False),
    )
    op.drop_column("report_images", "file_size")
    op.drop_column("report_images", "content_type")
    op.drop_column("report_images", "object_key")

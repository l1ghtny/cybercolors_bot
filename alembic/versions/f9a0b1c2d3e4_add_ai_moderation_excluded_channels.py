"""add ai moderation excluded channels

Revision ID: f9a0b1c2d3e4
Revises: e7f8a9b0c1d2
Create Date: 2026-07-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f9a0b1c2d3e4"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "server_ai_settings",
        sa.Column("moderation_excluded_channel_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.alter_column("server_ai_settings", "moderation_excluded_channel_ids", server_default=None)


def downgrade() -> None:
    op.drop_column("server_ai_settings", "moderation_excluded_channel_ids")

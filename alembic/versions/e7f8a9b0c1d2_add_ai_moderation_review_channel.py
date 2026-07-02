"""add ai moderation review channel

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-07-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("server_ai_settings", sa.Column("moderation_review_channel_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("server_ai_settings", "moderation_review_channel_id")

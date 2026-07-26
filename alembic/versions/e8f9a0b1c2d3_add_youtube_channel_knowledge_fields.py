"""Add YouTube channel knowledge aliases and related members.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from alembic import op


revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "youtube_channel_subscriptions",
        sa.Column("aliases", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
    )
    op.add_column(
        "youtube_channel_subscriptions",
        sa.Column("related_user_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
    )
    op.alter_column("youtube_channel_subscriptions", "aliases", server_default=None)
    op.alter_column("youtube_channel_subscriptions", "related_user_ids", server_default=None)


def downgrade() -> None:
    op.drop_column("youtube_channel_subscriptions", "related_user_ids")
    op.drop_column("youtube_channel_subscriptions", "aliases")

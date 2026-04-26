"""Add bot presence fields to servers.

Revision ID: 5d2a9f1c7b3e
Revises: 4a8d2e1b7c40
Create Date: 2026-04-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5d2a9f1c7b3e"
down_revision = "4a8d2e1b7c40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("bot_active", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("servers", sa.Column("bot_joined_at", sa.DateTime(), nullable=True))
    op.add_column("servers", sa.Column("bot_left_at", sa.DateTime(), nullable=True))
    op.add_column("servers", sa.Column("bot_presence_updated_at", sa.DateTime(), nullable=True))

    # Backfill current rows as active based on historical assumption that existing server rows
    # were observed while the bot had access.
    op.execute(
        """
        UPDATE servers
        SET bot_active = TRUE,
            bot_presence_updated_at = NOW()
        WHERE server_id IS NOT NULL
        """
    )

    op.alter_column("servers", "bot_active", server_default=None)


def downgrade() -> None:
    op.drop_column("servers", "bot_presence_updated_at")
    op.drop_column("servers", "bot_left_at")
    op.drop_column("servers", "bot_joined_at")
    op.drop_column("servers", "bot_active")

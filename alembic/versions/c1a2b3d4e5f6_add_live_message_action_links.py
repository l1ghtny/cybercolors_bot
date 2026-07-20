"""Add durable links between live messages and moderation actions.

Revision ID: c1a2b3d4e5f6
Revises: be8f1a2c3d40
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c1a2b3d4e5f6"
down_revision: str | None = "be8f1a2c3d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "moderation_action_message_links",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("moderation_action_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), nullable=False),
        sa.Column("linked_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["moderation_action_id"],
            ["moderation_actions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["linked_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "moderation_action_id",
            "message_id",
            name="uq_moderation_action_message_link",
        ),
    )
    op.create_index(
        "ix_moderation_action_message_links_moderation_action_id",
        "moderation_action_message_links",
        ["moderation_action_id"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_action_message_links_message_id",
        "moderation_action_message_links",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_action_message_links_server_id",
        "moderation_action_message_links",
        ["server_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_moderation_action_message_links_server_id",
        table_name="moderation_action_message_links",
    )
    op.drop_index(
        "ix_moderation_action_message_links_message_id",
        table_name="moderation_action_message_links",
    )
    op.drop_index(
        "ix_moderation_action_message_links_moderation_action_id",
        table_name="moderation_action_message_links",
    )
    op.drop_table("moderation_action_message_links")

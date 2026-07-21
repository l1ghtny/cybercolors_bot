"""Add audited moderator-authored bot messages.

Revision ID: a6b7c8d9e0f1
Revises: c1a2b3d4e5f6
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a6b7c8d9e0f1"
down_revision: str | None = "c1a2b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_message_audit_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_message_id", sa.BigInteger(), nullable=True),
        sa.Column("reply_to_message_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("discord_message_id"),
    )
    op.create_index(
        "ix_bot_message_audit_events_server_created_at",
        "bot_message_audit_events",
        ["server_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_bot_message_audit_events_channel_id",
        "bot_message_audit_events",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_bot_message_audit_events_actor_user_id",
        "bot_message_audit_events",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_bot_message_audit_events_status",
        "bot_message_audit_events",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_bot_message_audit_events_status", table_name="bot_message_audit_events")
    op.drop_index("ix_bot_message_audit_events_actor_user_id", table_name="bot_message_audit_events")
    op.drop_index("ix_bot_message_audit_events_channel_id", table_name="bot_message_audit_events")
    op.drop_index(
        "ix_bot_message_audit_events_server_created_at",
        table_name="bot_message_audit_events",
    )
    op.drop_table("bot_message_audit_events")

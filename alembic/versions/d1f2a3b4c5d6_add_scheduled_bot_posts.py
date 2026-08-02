"""add scheduled bot posts

Revision ID: d1f2a3b4c5d6
Revises: c0f1a2b3c4d5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d1f2a3b4c5d6"
down_revision: str | None = "c0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_bot_posts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mention_everyone", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("mention_user_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("mention_role_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("schedule_type", sa.String(length=20), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("next_run_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("lease_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("schedule_type IN ('once', 'interval')", name="ck_scheduled_bot_posts_type"),
        sa.CheckConstraint("status IN ('active', 'paused', 'completed')", name="ck_scheduled_bot_posts_status"),
        sa.CheckConstraint(
            "interval_seconds IS NULL OR interval_seconds BETWEEN 60 AND 31536000",
            name="ck_scheduled_bot_posts_interval",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_bot_posts_server_id", "scheduled_bot_posts", ["server_id"])
    op.create_index("ix_scheduled_bot_posts_channel_id", "scheduled_bot_posts", ["channel_id"])
    op.create_index("ix_scheduled_bot_posts_created_by_user_id", "scheduled_bot_posts", ["created_by_user_id"])
    op.create_index("ix_scheduled_bot_posts_status", "scheduled_bot_posts", ["status"])
    op.create_index("ix_scheduled_bot_posts_next_run_at", "scheduled_bot_posts", ["next_run_at"])
    op.create_index("ix_scheduled_bot_posts_lease_until", "scheduled_bot_posts", ["lease_until"])
    op.create_index("ix_scheduled_bot_posts_due", "scheduled_bot_posts", ["status", "next_run_at"])

    op.create_table(
        "scheduled_bot_post_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("scheduled_post_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_for", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="claimed", nullable=False),
        sa.Column("bot_message_audit_id", sa.Uuid(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["bot_message_audit_id"], ["bot_message_audit_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scheduled_post_id"], ["scheduled_bot_posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scheduled_post_id", "scheduled_for", name="uq_scheduled_bot_post_run_occurrence"),
    )
    op.create_index("ix_scheduled_bot_post_runs_scheduled_post_id", "scheduled_bot_post_runs", ["scheduled_post_id"])
    op.create_index("ix_scheduled_bot_post_runs_scheduled_for", "scheduled_bot_post_runs", ["scheduled_for"])
    op.create_index("ix_scheduled_bot_post_runs_status", "scheduled_bot_post_runs", ["status"])


def downgrade() -> None:
    op.drop_table("scheduled_bot_post_runs")
    op.drop_table("scheduled_bot_posts")

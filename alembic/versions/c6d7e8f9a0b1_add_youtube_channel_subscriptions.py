"""Add YouTube channel subscription catalogue tables.

Revision ID: c6d7e8f9a0b1
Revises: b7c8d9e0f1a2
Create Date: 2026-07-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c6d7e8f9a0b1"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "youtube_channel_subscriptions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("handle", sa.String(length=100), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("uploads_playlist_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="enabled", nullable=False),
        sa.Column(
            "auto_index_new_videos",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["global_users.discord_id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_id",
            "channel_id",
            name="uq_youtube_channel_subscriptions_server_channel",
        ),
    )
    op.create_index(
        "ix_youtube_channel_subscriptions_next_sync_at",
        "youtube_channel_subscriptions",
        ["next_sync_at"],
    )
    op.create_index(
        "ix_youtube_channel_subscriptions_server_id",
        "youtube_channel_subscriptions",
        ["server_id"],
    )
    op.create_index(
        "ix_youtube_channel_subscriptions_status",
        "youtube_channel_subscriptions",
        ["status"],
    )

    op.create_table(
        "youtube_channel_videos",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("video_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("availability", sa.String(length=30), server_default="public", nullable=False),
        sa.Column("captions_available", sa.Boolean(), nullable=True),
        sa.Column("knowledge_source_id", sa.Uuid(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_source_id"],
            ["ai_knowledge_sources.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["youtube_channel_subscriptions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscription_id",
            "video_id",
            name="uq_youtube_channel_videos_subscription_video",
        ),
    )
    op.create_index(
        "ix_youtube_channel_videos_published_at",
        "youtube_channel_videos",
        ["published_at"],
    )
    op.create_index(
        "ix_youtube_channel_videos_server_id",
        "youtube_channel_videos",
        ["server_id"],
    )
    op.create_index(
        "ix_youtube_channel_videos_subscription_id",
        "youtube_channel_videos",
        ["subscription_id"],
    )
    op.create_index(
        "uq_youtube_channel_videos_knowledge_source_id",
        "youtube_channel_videos",
        ["knowledge_source_id"],
        unique=True,
        postgresql_where=sa.text("knowledge_source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_youtube_channel_videos_knowledge_source_id",
        table_name="youtube_channel_videos",
    )
    op.drop_index(
        "ix_youtube_channel_videos_subscription_id",
        table_name="youtube_channel_videos",
    )
    op.drop_index("ix_youtube_channel_videos_server_id", table_name="youtube_channel_videos")
    op.drop_index("ix_youtube_channel_videos_published_at", table_name="youtube_channel_videos")
    op.drop_table("youtube_channel_videos")

    op.drop_index(
        "ix_youtube_channel_subscriptions_status",
        table_name="youtube_channel_subscriptions",
    )
    op.drop_index(
        "ix_youtube_channel_subscriptions_server_id",
        table_name="youtube_channel_subscriptions",
    )
    op.drop_index(
        "ix_youtube_channel_subscriptions_next_sync_at",
        table_name="youtube_channel_subscriptions",
    )
    op.drop_table("youtube_channel_subscriptions")

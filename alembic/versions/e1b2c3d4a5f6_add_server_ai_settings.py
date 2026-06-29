"""Add server AI settings.

Revision ID: e1b2c3d4a5f6
Revises: a6d4f9b2c801
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e1b2c3d4a5f6"
down_revision = "a6d4f9b2c801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_ai_settings",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("answer_channel_mode", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("answer_allowed_channel_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("answer_allowed_role_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("moderation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("moderation_channel_mode", sa.String(length=20), nullable=False, server_default="all"),
        sa.Column("moderation_included_channel_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("moderation_monitor_attachments", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("moderation_monitor_bots", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("moderation_strictness", sa.String(length=20), nullable=False, server_default="standard"),
        sa.Column("moderation_action_mode", sa.String(length=30), nullable=False, server_default="review_only"),
        sa.Column("log_ai_decisions", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("server_id"),
    )

    op.execute(
        """
        INSERT INTO server_ai_settings (
            server_id,
            answer_channel_mode,
            answer_allowed_channel_ids,
            answer_allowed_role_ids,
            moderation_enabled,
            moderation_channel_mode,
            moderation_included_channel_ids,
            moderation_monitor_attachments,
            moderation_monitor_bots,
            moderation_strictness,
            moderation_action_mode,
            log_ai_decisions,
            updated_at
        )
        SELECT
            server_id,
            'none',
            '[]',
            '[]',
            false,
            'all',
            '[]',
            false,
            false,
            'standard',
            'review_only',
            true,
            now()
        FROM servers
        """
    )


def downgrade() -> None:
    op.drop_table("server_ai_settings")

"""Add AI moderation runtime limits.

Revision ID: c9d0e1f2a3b4
Revises: a7b8c9d0e1f2
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9d0e1f2a3b4"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "server_ai_settings",
        sa.Column("moderation_kill_switch_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("server_ai_settings", sa.Column("moderation_daily_token_limit", sa.Integer(), nullable=True))
    op.add_column(
        "server_ai_settings",
        sa.Column("moderation_provider_timeout_seconds", sa.Integer(), nullable=False, server_default="20"),
    )
    op.add_column(
        "ai_moderation_decisions",
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("server_ai_settings", "moderation_kill_switch_enabled", server_default=None)
    op.alter_column("server_ai_settings", "moderation_provider_timeout_seconds", server_default=None)
    op.alter_column("ai_moderation_decisions", "total_tokens", server_default=None)


def downgrade() -> None:
    op.drop_column("ai_moderation_decisions", "total_tokens")
    op.drop_column("server_ai_settings", "moderation_provider_timeout_seconds")
    op.drop_column("server_ai_settings", "moderation_daily_token_limit")
    op.drop_column("server_ai_settings", "moderation_kill_switch_enabled")

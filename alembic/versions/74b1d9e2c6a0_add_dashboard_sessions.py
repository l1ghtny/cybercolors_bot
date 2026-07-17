"""Add server-side dashboard OAuth sessions.

Revision ID: 74b1d9e2c6a0
Revises: 632b76d67a18
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "74b1d9e2c6a0"
down_revision: str | None = "632b76d67a18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboard_sessions",
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_access_token", sa.Text(), nullable=False),
        sa.Column("discord_refresh_token", sa.Text(), nullable=True),
        sa.Column("discord_token_expires_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["discord_user_id"],
            ["global_users.discord_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_token_hash"),
    )
    op.create_index(
        "ix_dashboard_sessions_discord_user_id",
        "dashboard_sessions",
        ["discord_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_sessions_expires_at",
        "dashboard_sessions",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_sessions_expires_at", table_name="dashboard_sessions")
    op.drop_index("ix_dashboard_sessions_discord_user_id", table_name="dashboard_sessions")
    op.drop_table("dashboard_sessions")

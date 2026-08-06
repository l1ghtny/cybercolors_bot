"""Add Discord application profiles to servers and dashboard sessions.

Revision ID: f3b4c5d6e7a8
Revises: e2a3b4c5d6e7
Create Date: 2026-08-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f3b4c5d6e7a8"
down_revision = "e2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "servers",
        sa.Column("bot_profile", sa.String(length=32), nullable=False, server_default="cybercolors"),
    )
    op.create_index("ix_servers_bot_profile", "servers", ["bot_profile"])
    op.add_column(
        "dashboard_sessions",
        sa.Column(
            "application_profile",
            sa.String(length=32),
            nullable=False,
            server_default="cybercolors",
        ),
    )
    op.create_index(
        "ix_dashboard_sessions_application_profile",
        "dashboard_sessions",
        ["application_profile"],
    )
    op.alter_column("servers", "bot_profile", server_default=None)
    op.alter_column("dashboard_sessions", "application_profile", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_dashboard_sessions_application_profile", table_name="dashboard_sessions")
    op.drop_column("dashboard_sessions", "application_profile")
    op.drop_index("ix_servers_bot_profile", table_name="servers")
    op.drop_column("servers", "bot_profile")

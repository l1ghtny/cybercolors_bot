"""add AI companion and lockdown controls

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "server_ai_settings",
        sa.Column("answer_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "server_security_settings",
        sa.Column("public_bot_responses_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "server_security_settings",
        sa.Column("role_mutations_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "server_security_settings",
        sa.Column("lockdown_slowmode_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "server_security_settings",
        sa.Column(
            "lockdown_slowmode_channel_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "server_security_settings",
        sa.Column(
            "lockdown_slowmode_previous",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.alter_column("server_ai_settings", "answer_enabled", server_default=None)
    op.alter_column("server_security_settings", "public_bot_responses_paused", server_default=None)
    op.alter_column("server_security_settings", "role_mutations_paused", server_default=None)
    op.alter_column("server_security_settings", "lockdown_slowmode_channel_ids", server_default=None)
    op.alter_column("server_security_settings", "lockdown_slowmode_previous", server_default=None)


def downgrade() -> None:
    op.drop_column("server_security_settings", "lockdown_slowmode_previous")
    op.drop_column("server_security_settings", "lockdown_slowmode_channel_ids")
    op.drop_column("server_security_settings", "lockdown_slowmode_seconds")
    op.drop_column("server_security_settings", "role_mutations_paused")
    op.drop_column("server_security_settings", "public_bot_responses_paused")
    op.drop_column("server_ai_settings", "answer_enabled")

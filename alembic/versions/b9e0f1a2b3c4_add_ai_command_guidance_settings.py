"""Add requester-aware AI command guidance settings.

Revision ID: b9e0f1a2b3c4
Revises: b8d9e0f1a2c3
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op


revision = "b9e0f1a2b3c4"
down_revision = "b8d9e0f1a2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "server_ai_settings",
        sa.Column(
            "answer_command_guidance_mode",
            sa.String(length=20),
            nullable=False,
            server_default="personalized",
        ),
    )
    op.alter_column(
        "server_ai_settings",
        "answer_command_guidance_mode",
        server_default=None,
    )
    op.execute(
        sa.text(
            """
            UPDATE server_ai_settings
            SET answer_enabled_tools = (
                answer_enabled_tools::jsonb || '["get_available_commands"]'::jsonb
            )::json
            WHERE NOT answer_enabled_tools::jsonb @> '["get_available_commands"]'::jsonb
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE server_ai_settings
            SET answer_enabled_tools = (
                answer_enabled_tools::jsonb - 'get_available_commands'
            )::json
            """
        )
    )
    op.drop_column("server_ai_settings", "answer_command_guidance_mode")

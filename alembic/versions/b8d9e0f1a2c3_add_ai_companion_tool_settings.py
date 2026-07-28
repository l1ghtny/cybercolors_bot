"""Add per-server AI companion tool settings.

Revision ID: b8d9e0f1a2c3
Revises: a7c8d9e0f1b2
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op


revision = "b8d9e0f1a2c3"
down_revision = "a7c8d9e0f1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "server_ai_settings",
        sa.Column(
            "answer_enabled_tools",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(
                "'[\"get_active_rules\", \"get_member_profile\", \"get_server_activity\", "
                "\"search_server_knowledge\", \"search_youtube_channel_catalog\", \"web_search\"]'"
            ),
        ),
    )
    op.alter_column("server_ai_settings", "answer_enabled_tools", server_default=None)


def downgrade() -> None:
    op.drop_column("server_ai_settings", "answer_enabled_tools")

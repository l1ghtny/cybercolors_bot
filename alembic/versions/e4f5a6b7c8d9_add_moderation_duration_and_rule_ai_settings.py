"""Add configurable moderation durations and per-rule AI controls.

Revision ID: e4f5a6b7c8d9
Revises: d1e2f3a4b5c6, e2f3a4b5c6d7
Create Date: 2026-07-27
"""

import sqlalchemy as sa
from alembic import op


revision = "e4f5a6b7c8d9"
down_revision = ("d1e2f3a4b5c6", "e2f3a4b5c6d7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "server_moderation_settings",
        sa.Column(
            "mute_duration_presets",
            sa.JSON(),
            server_default=sa.text("'[60, 360, 720, 1440, 4320, 10080]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "server_moderation_settings",
        sa.Column("default_ban_minutes", sa.Integer(), server_default="43200", nullable=False),
    )
    op.add_column(
        "server_moderation_settings",
        sa.Column(
            "ban_duration_presets",
            sa.JSON(),
            server_default=sa.text("'[1440, 4320, 10080, 20160, 43200]'::json"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE server_moderation_settings "
            "SET default_mute_minutes = 720 "
            "WHERE default_mute_minutes = 60"
        )
    )

    op.add_column(
        "moderation_rules",
        sa.Column("ai_moderation_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "moderation_rules",
        sa.Column("ai_guidance", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_moderation_rules_ai_moderation_enabled",
        "moderation_rules",
        ["ai_moderation_enabled"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_rules_ai_moderation_enabled", table_name="moderation_rules")
    op.drop_column("moderation_rules", "ai_guidance")
    op.drop_column("moderation_rules", "ai_moderation_enabled")
    op.drop_column("server_moderation_settings", "ban_duration_presets")
    op.drop_column("server_moderation_settings", "default_ban_minutes")
    op.drop_column("server_moderation_settings", "mute_duration_presets")

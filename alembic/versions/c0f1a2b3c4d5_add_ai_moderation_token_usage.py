"""Add detailed AI moderation token usage.

Revision ID: c0f1a2b3c4d5
Revises: b9e0f1a2b3c4
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op


revision = "c0f1a2b3c4d5"
down_revision = "b9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_moderation_decisions",
        sa.Column("response_id", sa.String(length=120), nullable=True),
    )
    for column_name in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    ):
        op.add_column(
            "ai_moderation_decisions",
            sa.Column(column_name, sa.Integer(), nullable=False, server_default="0"),
        )
        op.alter_column(
            "ai_moderation_decisions",
            column_name,
            server_default=None,
        )


def downgrade() -> None:
    for column_name in (
        "reasoning_tokens",
        "output_tokens",
        "cached_input_tokens",
        "input_tokens",
    ):
        op.drop_column("ai_moderation_decisions", column_name)
    op.drop_column("ai_moderation_decisions", "response_id")

"""Add separate AI moderation policy diagnostics.

Revision ID: b0d2e5f8a3c7
Revises: c1e2f3a4b5c6
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op


revision = "b0d2e5f8a3c7"
down_revision = "c1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_moderation_decisions",
        sa.Column(
            "policy_notes",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_moderation_decisions
            SET policy_notes = json_build_array(
                    split_part(reason, ' Original AI reason: ', 1)
                ),
                reason = substring(
                    reason FROM position(' Original AI reason: ' IN reason)
                        + char_length(' Original AI reason: ')
                )
            WHERE reason LIKE '% Original AI reason: %'
            """
        )
    )


def downgrade() -> None:
    op.drop_column("ai_moderation_decisions", "policy_notes")

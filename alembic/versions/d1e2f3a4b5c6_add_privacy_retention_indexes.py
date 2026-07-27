"""Add indexes used by privacy retention cleanup.

Revision ID: d1e2f3a4b5c6
Revises: b0d2e5f8a3c7
Create Date: 2026-07-27 13:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "b0d2e5f8a3c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_ai_moderation_decisions_created_at",
        "ai_moderation_decisions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_answer_logs_created_at",
        "ai_answer_logs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_answer_logs_created_at", table_name="ai_answer_logs")
    op.drop_index("ix_ai_moderation_decisions_created_at", table_name="ai_moderation_decisions")

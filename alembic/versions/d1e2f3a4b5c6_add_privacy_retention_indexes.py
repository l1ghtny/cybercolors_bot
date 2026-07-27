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
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_moderation_decisions_created_at "
        "ON ai_moderation_decisions (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ai_moderation_decisions_created_at")

"""add knowledge subject role priority

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "a6b7c8d9e0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "server_ai_settings",
        sa.Column(
            "knowledge_subject_priority_role_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.alter_column(
        "server_ai_settings",
        "knowledge_subject_priority_role_ids",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("server_ai_settings", "knowledge_subject_priority_role_ids")

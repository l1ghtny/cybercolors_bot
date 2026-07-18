"""Add private object metadata to moderation case evidence.

Revision ID: c5e6f7a8b9d0
Revises: 74b1d9e2c6a0
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5e6f7a8b9d0"
down_revision: str | None = "74b1d9e2c6a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "moderation_case_evidence",
        sa.Column("attachment_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "moderation_case_evidence",
        sa.Column("attachment_content_type", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "moderation_case_evidence",
        sa.Column("attachment_size_bytes", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ux_moderation_case_evidence_attachment_key",
        "moderation_case_evidence",
        ["attachment_key"],
        unique=True,
        postgresql_where=sa.text("attachment_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_moderation_case_evidence_attachment_key",
        table_name="moderation_case_evidence",
    )
    op.drop_column("moderation_case_evidence", "attachment_size_bytes")
    op.drop_column("moderation_case_evidence", "attachment_content_type")
    op.drop_column("moderation_case_evidence", "attachment_filename")

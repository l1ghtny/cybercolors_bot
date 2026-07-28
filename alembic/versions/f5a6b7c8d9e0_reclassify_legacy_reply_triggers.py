"""Reclassify legacy reply triggers as manual entries.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op


revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


# The intent-based reply system was committed at 2026-07-26 13:41:55 UTC.
# Trigger ids are UUIDv7, so their natural ordering preserves creation time.
# Before this boundary every trigger was entered through the legacy manual UI;
# the intent migration incorrectly labelled entries after the first five as AI-generated.
INTENT_SYSTEM_CUTOFF_ID = "019f9ea9-2cb8-7000-8000-000000000000"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE triggers
            SET source = 'manual'
            WHERE source = 'generated'
              AND id < '{INTENT_SYSTEM_CUTOFF_ID}'::uuid
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE triggers
            SET source = 'generated'
            WHERE source = 'manual'
              AND id < '{INTENT_SYSTEM_CUTOFF_ID}'::uuid
            """
        )
    )

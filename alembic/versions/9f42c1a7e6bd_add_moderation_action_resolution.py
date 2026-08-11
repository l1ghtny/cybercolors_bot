"""Distinguish expired moderation actions from explicit reversals.

Revision ID: 9f42c1a7e6bd
Revises: b5c6d7e8f9a0
Create Date: 2026-08-11 21:00:00.000000

Legacy inactive temporary actions can only be classified from their stored
expiry. Future state transitions write the exact resolution type.
"""

from alembic import op
import sqlalchemy as sa


revision = "9f42c1a7e6bd"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "moderation_actions",
        sa.Column("resolution_type", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE moderation_actions
        SET resolution_type = CASE
            WHEN action_type IN ('MUTE', 'BAN')
             AND expires_at IS NOT NULL
             AND expires_at <= CURRENT_TIMESTAMP
                THEN 'expired_legacy'
            ELSE 'reverted'
        END
        WHERE is_active = FALSE
          AND action_type IN ('WARN', 'MUTE', 'BAN')
        """
    )


def downgrade() -> None:
    op.drop_column("moderation_actions", "resolution_type")

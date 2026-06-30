"""Add AI review message references.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_moderation_decisions", sa.Column("review_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("ai_moderation_decisions", sa.Column("review_message_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_moderation_decisions", "review_message_id")
    op.drop_column("ai_moderation_decisions", "review_channel_id")

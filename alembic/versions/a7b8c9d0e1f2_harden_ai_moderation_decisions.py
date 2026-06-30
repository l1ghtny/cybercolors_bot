"""Harden AI moderation decisions.

Revision ID: a7b8c9d0e1f2
Revises: f2c3d4e5a6b7
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f2c3d4e5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_moderation_decisions", sa.Column("selected_action", sa.String(length=30), nullable=True))
    op.add_column("ai_moderation_decisions", sa.Column("action_reason", sa.Text(), nullable=True))
    op.add_column(
        "ai_moderation_decisions",
        sa.Column("action_override", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_unique_constraint(
        "uq_ai_moderation_decisions_server_message",
        "ai_moderation_decisions",
        ["server_id", "message_id"],
    )
    op.alter_column("ai_moderation_decisions", "action_override", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "uq_ai_moderation_decisions_server_message",
        "ai_moderation_decisions",
        type_="unique",
    )
    op.drop_column("ai_moderation_decisions", "action_override")
    op.drop_column("ai_moderation_decisions", "action_reason")
    op.drop_column("ai_moderation_decisions", "selected_action")
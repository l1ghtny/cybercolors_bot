"""Add moderation rule sync states.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b9"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_rule_sync_states",
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("sync_status", sa.String(), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=True),
        sa.Column("source_segment_hash", sa.String(length=64), nullable=True),
        sa.Column("sync_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["moderation_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rule_id"),
    )
    op.create_index(
        "ix_moderation_rule_sync_states_sync_status",
        "moderation_rule_sync_states",
        ["sync_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_moderation_rule_sync_states_sync_status",
        table_name="moderation_rule_sync_states",
    )
    op.drop_table("moderation_rule_sync_states")

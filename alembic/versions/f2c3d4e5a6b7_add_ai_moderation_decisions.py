"""Add AI moderation decisions.

Revision ID: f2c3d4e5a6b7
Revises: e1b2c3d4a5f6
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2c3d4e5a6b7"
down_revision = "e1b2c3d4a5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_moderation_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), nullable=False),
        sa.Column("message_content", sa.Text(), nullable=True),
        sa.Column("attachments_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("strictness", sa.String(length=20), nullable=False, server_default="standard"),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("categories", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.String(length=30), nullable=False, server_default="none"),
        sa.Column("rule_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_review"),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("linked_case_id", sa.Uuid(), nullable=True),
        sa.Column("linked_action_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["linked_action_id"], ["moderation_actions.id"]),
        sa.ForeignKeyConstraint(["linked_case_id"], ["moderation_cases.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_moderation_decisions_server_id", "ai_moderation_decisions", ["server_id"])
    op.create_index("ix_ai_moderation_decisions_channel_id", "ai_moderation_decisions", ["channel_id"])
    op.create_index("ix_ai_moderation_decisions_message_id", "ai_moderation_decisions", ["message_id"])
    op.create_index("ix_ai_moderation_decisions_author_user_id", "ai_moderation_decisions", ["author_user_id"])
    op.create_index("ix_ai_moderation_decisions_flagged", "ai_moderation_decisions", ["flagged"])
    op.create_index("ix_ai_moderation_decisions_status", "ai_moderation_decisions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ai_moderation_decisions_status", table_name="ai_moderation_decisions")
    op.drop_index("ix_ai_moderation_decisions_flagged", table_name="ai_moderation_decisions")
    op.drop_index("ix_ai_moderation_decisions_author_user_id", table_name="ai_moderation_decisions")
    op.drop_index("ix_ai_moderation_decisions_message_id", table_name="ai_moderation_decisions")
    op.drop_index("ix_ai_moderation_decisions_channel_id", table_name="ai_moderation_decisions")
    op.drop_index("ix_ai_moderation_decisions_server_id", table_name="ai_moderation_decisions")
    op.drop_table("ai_moderation_decisions")

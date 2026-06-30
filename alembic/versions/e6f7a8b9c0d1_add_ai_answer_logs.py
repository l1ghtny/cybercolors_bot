"""Add AI answer logs.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-30 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_answer_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("author_user_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("response_id", sa.String(length=120), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visual_input_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversation_message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_content", sa.Text(), nullable=True),
        sa.Column("response_content", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_answer_logs_author_user_id", "ai_answer_logs", ["author_user_id"])
    op.create_index("ix_ai_answer_logs_channel_id", "ai_answer_logs", ["channel_id"])
    op.create_index("ix_ai_answer_logs_created_at", "ai_answer_logs", ["created_at"])
    op.create_index("ix_ai_answer_logs_message_id", "ai_answer_logs", ["message_id"])
    op.create_index("ix_ai_answer_logs_server_created", "ai_answer_logs", ["server_id", "created_at"])
    op.create_index("ix_ai_answer_logs_server_id", "ai_answer_logs", ["server_id"])
    op.create_index("ix_ai_answer_logs_status", "ai_answer_logs", ["status"])
    op.alter_column("ai_answer_logs", "total_tokens", server_default=None)
    op.alter_column("ai_answer_logs", "tool_call_count", server_default=None)
    op.alter_column("ai_answer_logs", "visual_input_count", server_default=None)
    op.alter_column("ai_answer_logs", "conversation_message_count", server_default=None)
    op.alter_column("ai_answer_logs", "created_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_ai_answer_logs_status", table_name="ai_answer_logs")
    op.drop_index("ix_ai_answer_logs_server_id", table_name="ai_answer_logs")
    op.drop_index("ix_ai_answer_logs_server_created", table_name="ai_answer_logs")
    op.drop_index("ix_ai_answer_logs_message_id", table_name="ai_answer_logs")
    op.drop_index("ix_ai_answer_logs_created_at", table_name="ai_answer_logs")
    op.drop_index("ix_ai_answer_logs_channel_id", table_name="ai_answer_logs")
    op.drop_index("ix_ai_answer_logs_author_user_id", table_name="ai_answer_logs")
    op.drop_table("ai_answer_logs")

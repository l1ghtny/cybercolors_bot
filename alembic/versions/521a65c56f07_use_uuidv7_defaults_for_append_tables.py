"""Use PostgreSQL 18 UUIDv7 defaults for append-oriented tables.

Revision ID: 521a65c56f07
Revises: b4c5d6e7f809
Create Date: 2026-07-13 08:56:53.029067
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "521a65c56f07"
down_revision: str | None = "b4c5d6e7f809"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID7_TABLES = (
    "ai_moderation_decisions",
    "ai_answer_logs",
    "ai_knowledge_chunks",
    "ai_knowledge_index_jobs",
    "moderation_actions",
    "moderation_import_runs",
    "moderation_import_source_items",
    "monitored_user_comments",
    "monitored_user_status_events",
    "monitored_user_activity_events",
    "server_rbac_audit_events",
    "moderation_cases",
    "moderation_case_users",
    "moderation_case_action_links",
    "moderation_action_rules",
    "moderation_case_rules",
    "moderation_case_notes",
    "moderation_case_evidence",
    "deleted_messages",
    "moderation_action_deleted_message_links",
    "temp_voice_log",
    "temp_voice_participants",
    "attachment_log",
    "triggers",
)


def upgrade() -> None:
    for table_name in UUID7_TABLES:
        op.alter_column(
            table_name,
            "id",
            existing_type=sa.Uuid(),
            server_default=sa.text("uuidv7()"),
        )


def downgrade() -> None:
    for table_name in reversed(UUID7_TABLES):
        op.alter_column(
            table_name,
            "id",
            existing_type=sa.Uuid(),
            server_default=None,
        )

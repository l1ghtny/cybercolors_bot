"""Add dashboard query indexes.

Revision ID: f1a2b3c4d5e6
Revises: e9f0a1b2c3d4
Create Date: 2026-07-09 18:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_message_log_server_created_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_message_log_server_created_at "
        "ON message_log (server_id, created_at DESC)",
    ),
    (
        "ix_message_log_server_user_created_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_message_log_server_user_created_at "
        "ON message_log (server_id, user_id, created_at DESC)",
    ),
    (
        "ix_message_log_server_channel_created_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_message_log_server_channel_created_at "
        "ON message_log (server_id, channel_id, created_at DESC)",
    ),
    (
        "ix_deleted_messages_server_deleted_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deleted_messages_server_deleted_at "
        "ON deleted_messages (server_id, deleted_at DESC)",
    ),
    (
        "ix_deleted_messages_server_author_deleted_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deleted_messages_server_author_deleted_at "
        "ON deleted_messages (server_id, author_user_id, deleted_at DESC)",
    ),
    (
        "ix_deleted_messages_server_channel_deleted_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deleted_messages_server_channel_deleted_at "
        "ON deleted_messages (server_id, channel_id, deleted_at DESC)",
    ),
    (
        "ix_moderation_actions_server_created_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_moderation_actions_server_created_at "
        "ON moderation_actions (server_id, created_at DESC)",
    ),
    (
        "ix_moderation_actions_server_target_created_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_moderation_actions_server_target_created_at "
        "ON moderation_actions (server_id, target_user_id, created_at DESC)",
    ),
    (
        "ix_moderation_actions_active_warns_target_created_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_moderation_actions_active_warns_target_created_at "
        "ON moderation_actions (server_id, target_user_id, created_at DESC) "
        "WHERE action_type = 'WARN' AND is_active = true",
    ),
    (
        "ix_ai_moderation_decisions_server_status_created_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ai_moderation_decisions_server_status_created_at "
        "ON ai_moderation_decisions (server_id, status, created_at DESC)",
    ),
    (
        "ix_ai_moderation_decisions_server_author_created_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ai_moderation_decisions_server_author_created_at "
        "ON ai_moderation_decisions (server_id, author_user_id, created_at DESC)",
    ),
    (
        "ix_monitored_events_server_user_occurred_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_monitored_events_server_user_occurred_at "
        "ON monitored_user_activity_events (server_id, user_id, occurred_at DESC)",
    ),
    (
        "ix_monitored_events_monitored_occurred_at",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_monitored_events_monitored_occurred_at "
        "ON monitored_user_activity_events (monitored_user_id, occurred_at DESC)",
    ),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for _, ddl in INDEXES:
            op.execute(ddl)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ in reversed(INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")

"""Use timezone-aware timestamps for stored instants.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-07-24

Every PostgreSQL timestamp in the application schema represents an instant.
Calendar-only values are modeled with DATE instead. Existing naïve timestamps
have always been written as UTC, so the conversion explicitly interprets them
in UTC and preserves the represented instant.
"""

import sqlalchemy as sa
from alembic import op


revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


INSTANT_COLUMNS = {
    "ai_answer_logs": ("created_at",),
    "ai_knowledge_chunks": ("created_at", "updated_at"),
    "ai_knowledge_index_jobs": ("run_after", "locked_at", "created_at", "updated_at"),
    "ai_knowledge_sources": ("created_at", "updated_at", "indexed_at", "deleted_at"),
    "ai_moderation_decisions": ("reviewed_at", "created_at", "updated_at"),
    "birthdays": ("role_added_at",),
    "bot_message_audit_events": ("created_at", "sent_at"),
    "congratulations": ("added_at",),
    "dashboard_access_roles": ("created_at",),
    "dashboard_access_users": ("created_at",),
    "dashboard_sessions": ("discord_token_expires_at", "expires_at", "created_at", "last_seen_at"),
    "deleted_messages": ("deleted_at",),
    "historical_activity_import_cursors": ("oldest_message_at", "newest_message_at", "updated_at"),
    "historical_user_activity_daily": ("last_message_at", "created_at", "updated_at"),
    "message_claims": ("created_at", "claimed_at"),
    "message_log": ("created_at",),
    "moderation_action_deleted_message_links": ("linked_at",),
    "moderation_action_message_links": ("linked_at",),
    "moderation_action_rules": ("cited_at", "rule_deleted_at"),
    "moderation_actions": ("created_at", "expires_at"),
    "moderation_case_action_links": ("linked_at",),
    "moderation_case_evidence": ("created_at",),
    "moderation_case_notes": ("created_at",),
    "moderation_case_rules": ("cited_at", "rule_deleted_at"),
    "moderation_case_users": ("added_at",),
    "moderation_cases": ("created_at", "closed_at"),
    "moderation_import_runs": ("started_at", "completed_at"),
    "moderation_import_source_items": ("created_at",),
    "moderation_rules": ("created_at", "updated_at"),
    "moderation_rule_sync_states": ("created_at", "updated_at"),
    "monitored_user_activity_events": ("occurred_at",),
    "monitored_user_comments": ("created_at",),
    "monitored_user_notification_settings": ("updated_at",),
    "monitored_user_status_events": ("changed_at",),
    "monitored_users": (
        "release_due_at",
        "released_at",
        "notification_snoozed_until",
        "last_notification_at",
        "created_at",
        "updated_at",
    ),
    "past_nicknames": ("recorded_at",),
    "replies": ("created_at",),
    "server_ai_settings": ("updated_at",),
    "server_localization_settings": ("updated_at",),
    "server_moderation_settings": ("updated_at",),
    "server_monitoring_settings": ("updated_at",),
    "server_overview_settings": ("updated_at",),
    "server_rbac_assignments": ("created_at", "updated_at"),
    "server_rbac_audit_events": ("created_at",),
    "server_security_settings": ("updated_at",),
    "server_temp_voice_settings": ("updated_at",),
    "servers": ("bot_joined_at", "bot_left_at", "bot_presence_updated_at"),
    "temp_voice_log": ("created_at", "deleted_at"),
    "temp_voice_participants": ("joined_at", "left_at"),
    "user_activity": ("last_message_at",),
    "users": ("joined_server_at", "left_server_at", "flagged_absent_at"),
    "voice_channels": ("created_at",),
    "youtube_channel_subscriptions": ("last_synced_at", "next_sync_at", "created_at", "updated_at"),
    "youtube_channel_videos": ("published_at", "discovered_at", "updated_at"),
}


def _quote_identifier(value: str) -> str:
    return op.get_bind().dialect.identifier_preparer.quote_identifier(value)


def upgrade() -> None:
    for table_name, column_names in INSTANT_COLUMNS.items():
        for column_name in column_names:
            table = _quote_identifier(table_name)
            column = _quote_identifier(column_name)
            op.execute(
                sa.text(
                    f"ALTER TABLE {table} ALTER COLUMN {column} "
                    f"TYPE TIMESTAMP WITH TIME ZONE USING {column} AT TIME ZONE 'UTC'"
                )
            )


def downgrade() -> None:
    for table_name, column_names in reversed(tuple(INSTANT_COLUMNS.items())):
        for column_name in reversed(column_names):
            table = _quote_identifier(table_name)
            column = _quote_identifier(column_name)
            op.execute(
                sa.text(
                    f"ALTER TABLE {table} ALTER COLUMN {column} "
                    f"TYPE TIMESTAMP WITHOUT TIME ZONE USING {column} AT TIME ZONE 'UTC'"
                )
            )

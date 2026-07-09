"""add monitoring settings and activity events

Revision ID: c7d8e9f0a1b2
Revises: b2c3d4e5f6a7
Create Date: 2026-07-09 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "server_monitoring_settings",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("discord_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_notify_rejoin", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_notify_messages", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_message_threshold", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("default_notify_images", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_notify_voice", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_notify_threads", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_notify_commands", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_notify_ai_interactions", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_monitor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_monitor_recent_account_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("auto_monitor_no_avatar", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "auto_monitor_reason",
            sa.String(length=250),
            nullable=False,
            server_default="Automatic monitoring: newcomer risk signals",
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("server_id"),
    )

    op.create_table(
        "monitored_user_notification_settings",
        sa.Column("monitored_user_id", sa.Uuid(), nullable=False),
        sa.Column("notify_rejoin", sa.Boolean(), nullable=True),
        sa.Column("notify_messages", sa.Boolean(), nullable=True),
        sa.Column("message_threshold", sa.Integer(), nullable=True),
        sa.Column("notify_images", sa.Boolean(), nullable=True),
        sa.Column("notify_voice", sa.Boolean(), nullable=True),
        sa.Column("notify_threads", sa.Boolean(), nullable=True),
        sa.Column("notify_commands", sa.Boolean(), nullable=True),
        sa.Column("notify_ai_interactions", sa.Boolean(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["monitored_user_id"], ["monitored_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("monitored_user_id"),
    )

    op.create_table(
        "monitored_user_activity_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("monitored_user_id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("message_content", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("notification_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["monitored_user_id"], ["monitored_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitored_user_activity_events_monitored_user_id", "monitored_user_activity_events", ["monitored_user_id"])
    op.create_index("ix_monitored_user_activity_events_server_id", "monitored_user_activity_events", ["server_id"])
    op.create_index("ix_monitored_user_activity_events_user_id", "monitored_user_activity_events", ["user_id"])
    op.create_index("ix_monitored_user_activity_events_event_type", "monitored_user_activity_events", ["event_type"])
    op.create_index("ix_monitored_user_activity_events_channel_id", "monitored_user_activity_events", ["channel_id"])
    op.create_index("ix_monitored_user_activity_events_message_id", "monitored_user_activity_events", ["message_id"])
    op.create_index("ix_monitored_user_activity_events_occurred_at", "monitored_user_activity_events", ["occurred_at"])

    op.alter_column("server_monitoring_settings", "discord_notifications_enabled", server_default=None)
    op.alter_column("server_monitoring_settings", "default_notify_rejoin", server_default=None)
    op.alter_column("server_monitoring_settings", "default_notify_messages", server_default=None)
    op.alter_column("server_monitoring_settings", "default_message_threshold", server_default=None)
    op.alter_column("server_monitoring_settings", "default_notify_images", server_default=None)
    op.alter_column("server_monitoring_settings", "default_notify_voice", server_default=None)
    op.alter_column("server_monitoring_settings", "default_notify_threads", server_default=None)
    op.alter_column("server_monitoring_settings", "default_notify_commands", server_default=None)
    op.alter_column("server_monitoring_settings", "default_notify_ai_interactions", server_default=None)
    op.alter_column("server_monitoring_settings", "auto_monitor_enabled", server_default=None)
    op.alter_column("server_monitoring_settings", "auto_monitor_recent_account_days", server_default=None)
    op.alter_column("server_monitoring_settings", "auto_monitor_no_avatar", server_default=None)
    op.alter_column("server_monitoring_settings", "auto_monitor_reason", server_default=None)
    op.alter_column("server_monitoring_settings", "updated_at", server_default=None)
    op.alter_column("monitored_user_notification_settings", "updated_at", server_default=None)
    op.alter_column("monitored_user_activity_events", "metadata_json", server_default=None)
    op.alter_column("monitored_user_activity_events", "notification_sent", server_default=None)
    op.alter_column("monitored_user_activity_events", "occurred_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_monitored_user_activity_events_occurred_at", table_name="monitored_user_activity_events")
    op.drop_index("ix_monitored_user_activity_events_message_id", table_name="monitored_user_activity_events")
    op.drop_index("ix_monitored_user_activity_events_channel_id", table_name="monitored_user_activity_events")
    op.drop_index("ix_monitored_user_activity_events_event_type", table_name="monitored_user_activity_events")
    op.drop_index("ix_monitored_user_activity_events_user_id", table_name="monitored_user_activity_events")
    op.drop_index("ix_monitored_user_activity_events_server_id", table_name="monitored_user_activity_events")
    op.drop_index("ix_monitored_user_activity_events_monitored_user_id", table_name="monitored_user_activity_events")
    op.drop_table("monitored_user_activity_events")
    op.drop_table("monitored_user_notification_settings")
    op.drop_table("server_monitoring_settings")

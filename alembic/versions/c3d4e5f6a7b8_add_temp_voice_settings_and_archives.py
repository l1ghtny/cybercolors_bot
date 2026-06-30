"""Add temp voice settings and archives.

Revision ID: c3d4e5f6a7b8
Revises: f7b8c9d0e1f2
Create Date: 2026-06-30
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _fk_exists(table_name: str, fk_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    inspector = sa.inspect(op.get_bind())
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _table_exists("server_temp_voice_settings"):
        op.create_table(
            "server_temp_voice_settings",
            sa.Column("server_id", sa.BigInteger(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("trigger_channel_id", sa.BigInteger(), nullable=True),
            sa.Column("archive_channel_id", sa.BigInteger(), nullable=True),
            sa.Column("channel_name_template", sa.String(length=100), nullable=False, server_default="{display_name}'s channel"),
            sa.Column("owner_manage_channel_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
            sa.PrimaryKeyConstraint("server_id"),
        )
        op.alter_column("server_temp_voice_settings", "enabled", server_default=None)
        op.alter_column("server_temp_voice_settings", "channel_name_template", server_default=None)
        op.alter_column("server_temp_voice_settings", "owner_manage_channel_enabled", server_default=None)

    voice_columns = [
        ("trigger_channel_id", sa.Column("trigger_channel_id", sa.BigInteger(), nullable=True)),
        ("owner_user_id", sa.Column("owner_user_id", sa.BigInteger(), nullable=True)),
        ("channel_name", sa.Column("channel_name", sa.String(), nullable=True)),
        ("created_at", sa.Column("created_at", sa.DateTime(), nullable=True)),
    ]
    for column_name, column in voice_columns:
        if not _column_exists("voice_channels", column_name):
            op.add_column("voice_channels", column)
    if _column_exists("voice_channels", "created_at"):
        op.execute(sa.text("UPDATE voice_channels SET created_at = NOW() WHERE created_at IS NULL"))
        op.alter_column("voice_channels", "created_at", nullable=False)
    if not _fk_exists("voice_channels", "fk_voice_channels_owner_user_id_global_users"):
        op.create_foreign_key(
            "fk_voice_channels_owner_user_id_global_users",
            "voice_channels",
            "global_users",
            ["owner_user_id"],
            ["discord_id"],
        )

    temp_log_columns = [
        ("trigger_channel_id", sa.Column("trigger_channel_id", sa.BigInteger(), nullable=True)),
        ("owner_user_id", sa.Column("owner_user_id", sa.BigInteger(), nullable=True)),
        ("archive_channel_id", sa.Column("archive_channel_id", sa.BigInteger(), nullable=True)),
        ("archive_message_id", sa.Column("archive_message_id", sa.BigInteger(), nullable=True)),
    ]
    for column_name, column in temp_log_columns:
        if not _column_exists("temp_voice_log", column_name):
            op.add_column("temp_voice_log", column)
    if not _fk_exists("temp_voice_log", "fk_temp_voice_log_owner_user_id_global_users"):
        op.create_foreign_key(
            "fk_temp_voice_log_owner_user_id_global_users",
            "temp_voice_log",
            "global_users",
            ["owner_user_id"],
            ["discord_id"],
        )
    for index_name, columns in (
        ("ix_temp_voice_log_server_channel", ["server_id", "channel_id"]),
        ("ix_temp_voice_log_archive_message", ["archive_channel_id", "archive_message_id"]),
    ):
        if not _index_exists("temp_voice_log", index_name):
            op.create_index(index_name, "temp_voice_log", columns)

    for table_name in ("ai_moderation_decisions",):
        if not _column_exists(table_name, "archive_channel_id"):
            op.add_column(table_name, sa.Column("archive_channel_id", sa.BigInteger(), nullable=True))
        if not _column_exists(table_name, "archive_message_id"):
            op.add_column(table_name, sa.Column("archive_message_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    if _column_exists("ai_moderation_decisions", "archive_message_id"):
        op.drop_column("ai_moderation_decisions", "archive_message_id")
    if _column_exists("ai_moderation_decisions", "archive_channel_id"):
        op.drop_column("ai_moderation_decisions", "archive_channel_id")

    if _index_exists("temp_voice_log", "ix_temp_voice_log_archive_message"):
        op.drop_index("ix_temp_voice_log_archive_message", table_name="temp_voice_log")
    if _index_exists("temp_voice_log", "ix_temp_voice_log_server_channel"):
        op.drop_index("ix_temp_voice_log_server_channel", table_name="temp_voice_log")
    if _fk_exists("temp_voice_log", "fk_temp_voice_log_owner_user_id_global_users"):
        op.drop_constraint("fk_temp_voice_log_owner_user_id_global_users", "temp_voice_log", type_="foreignkey")
    for column_name in ("archive_message_id", "archive_channel_id", "owner_user_id", "trigger_channel_id"):
        if _column_exists("temp_voice_log", column_name):
            op.drop_column("temp_voice_log", column_name)

    if _fk_exists("voice_channels", "fk_voice_channels_owner_user_id_global_users"):
        op.drop_constraint("fk_voice_channels_owner_user_id_global_users", "voice_channels", type_="foreignkey")
    for column_name in ("created_at", "channel_name", "owner_user_id", "trigger_channel_id"):
        if _column_exists("voice_channels", column_name):
            op.drop_column("voice_channels", column_name)

    if _table_exists("server_temp_voice_settings"):
        op.drop_table("server_temp_voice_settings")

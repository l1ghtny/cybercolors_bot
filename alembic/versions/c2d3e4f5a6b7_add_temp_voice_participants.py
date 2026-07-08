"""add temp voice participants

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _table_exists("temp_voice_participants"):
        op.create_table(
            "temp_voice_participants",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("log_id", sa.Uuid(), nullable=False),
            sa.Column("server_id", sa.BigInteger(), nullable=False),
            sa.Column("channel_id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("joined_at", sa.DateTime(), nullable=False),
            sa.Column("left_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["log_id"], ["temp_voice_log.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["global_users.discord_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = [
        ("ix_temp_voice_participants_log_id", ["log_id"]),
        ("ix_temp_voice_participants_server_id", ["server_id"]),
        ("ix_temp_voice_participants_channel_id", ["channel_id"]),
        ("ix_temp_voice_participants_user_id", ["user_id"]),
        ("ix_temp_voice_participants_left_at", ["left_at"]),
    ]
    for index_name, columns in indexes:
        if not _index_exists("temp_voice_participants", index_name):
            op.create_index(index_name, "temp_voice_participants", columns)


def downgrade() -> None:
    if _table_exists("temp_voice_participants"):
        op.drop_table("temp_voice_participants")
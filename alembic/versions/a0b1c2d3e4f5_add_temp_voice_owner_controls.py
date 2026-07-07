"""add temp voice owner controls

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-07-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _column_exists("server_temp_voice_settings", "owner_rename_enabled"):
        op.add_column(
            "server_temp_voice_settings",
            sa.Column("owner_rename_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column("server_temp_voice_settings", "owner_rename_enabled", server_default=None)
    if not _column_exists("server_temp_voice_settings", "owner_user_limit_enabled"):
        op.add_column(
            "server_temp_voice_settings",
            sa.Column("owner_user_limit_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column("server_temp_voice_settings", "owner_user_limit_enabled", server_default=None)
    if not _column_exists("server_temp_voice_settings", "owner_control_allowed_role_ids"):
        op.add_column(
            "server_temp_voice_settings",
            sa.Column("owner_control_allowed_role_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
        op.alter_column("server_temp_voice_settings", "owner_control_allowed_role_ids", server_default=None)


def downgrade() -> None:
    for column_name in (
        "owner_control_allowed_role_ids",
        "owner_user_limit_enabled",
        "owner_rename_enabled",
    ):
        if _column_exists("server_temp_voice_settings", column_name):
            op.drop_column("server_temp_voice_settings", column_name)
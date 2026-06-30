"""Fix temp voice log server id bigint.

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-06-30
"""

from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b9c0"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _column_type(table_name: str, column_name: str):
    if not _table_exists(table_name):
        return None
    inspector = sa.inspect(op.get_bind())
    for column in inspector.get_columns(table_name):
        if column["name"] == column_name:
            return column["type"]
    return None


def _server_id_fk_names() -> list[str]:
    if not _table_exists("temp_voice_log"):
        return []
    inspector = sa.inspect(op.get_bind())
    return [
        fk["name"]
        for fk in inspector.get_foreign_keys("temp_voice_log")
        if fk.get("constrained_columns") == ["server_id"]
    ]


def _fk_exists(fk_name: str) -> bool:
    return fk_name in _server_id_fk_names()


def upgrade() -> None:
    if not _table_exists("temp_voice_log"):
        return

    fk_names = _server_id_fk_names()
    for fk_name in fk_names:
        if fk_name:
            op.drop_constraint(fk_name, "temp_voice_log", type_="foreignkey")

    column_type = _column_type("temp_voice_log", "server_id")
    if column_type is not None and not isinstance(column_type, sa.BigInteger):
        op.alter_column(
            "temp_voice_log",
            "server_id",
            existing_type=column_type,
            type_=sa.BigInteger(),
            existing_nullable=False,
            postgresql_using="server_id::bigint",
        )

    if not _fk_exists("fk_temp_voice_log_server_id_servers"):
        op.create_foreign_key(
            "fk_temp_voice_log_server_id_servers",
            "temp_voice_log",
            "servers",
            ["server_id"],
            ["server_id"],
        )


def downgrade() -> None:
    if not _table_exists("temp_voice_log"):
        return
    if _fk_exists("fk_temp_voice_log_server_id_servers"):
        op.drop_constraint("fk_temp_voice_log_server_id_servers", "temp_voice_log", type_="foreignkey")
    op.alter_column(
        "temp_voice_log",
        "server_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="server_id::integer",
    )
    op.create_foreign_key(
        "temp_voice_log_server_id_fkey",
        "temp_voice_log",
        "servers",
        ["server_id"],
        ["server_id"],
    )

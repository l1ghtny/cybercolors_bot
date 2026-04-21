"""Align message_log schema with runtime usage.

Revision ID: 6b3e4f2a9d10
Revises: d14f6e9b3a55
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b3e4f2a9d10"
down_revision = "d14f6e9b3a55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "message_log",
        "log_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.alter_column(
        "message_log",
        "user_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.add_column("message_log", sa.Column("channel_id", sa.BigInteger(), nullable=True))
    op.add_column("message_log", sa.Column("server_id", sa.BigInteger(), nullable=True))

    op.execute(
        """
        UPDATE message_log AS ml
        SET channel_id = tvl.channel_id,
            server_id = tvl.server_id
        FROM temp_voice_log AS tvl
        WHERE ml.log_id = tvl.id
        """
    )

    op.create_foreign_key(
        "fk_message_log_server_id_servers",
        "message_log",
        "servers",
        ["server_id"],
        ["server_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_message_log_server_id_servers", "message_log", type_="foreignkey")
    op.drop_column("message_log", "server_id")
    op.drop_column("message_log", "channel_id")
    op.alter_column(
        "message_log",
        "user_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "message_log",
        "log_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )

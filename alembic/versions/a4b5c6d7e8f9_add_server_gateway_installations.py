"""Track multiple Discord gateway installations per server.

Revision ID: a4b5c6d7e8f9
Revises: f3b4c5d6e7a8
Create Date: 2026-08-06 22:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a4b5c6d7e8f9"
down_revision = "f3b4c5d6e7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_gateway_installations",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_key", sa.String(length=32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("presence_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("server_id", "profile_key"),
    )
    op.create_index(
        "ix_server_gateway_installations_profile_active",
        "server_gateway_installations",
        ["profile_key", "active"],
    )
    op.execute(
        """
        INSERT INTO server_gateway_installations (
            server_id,
            profile_key,
            active,
            joined_at,
            left_at,
            presence_updated_at
        )
        SELECT
            server_id,
            bot_profile,
            bot_active,
            bot_joined_at,
            bot_left_at,
            bot_presence_updated_at
        FROM servers
        ON CONFLICT (server_id, profile_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_server_gateway_installations_profile_active",
        table_name="server_gateway_installations",
    )
    op.drop_table("server_gateway_installations")

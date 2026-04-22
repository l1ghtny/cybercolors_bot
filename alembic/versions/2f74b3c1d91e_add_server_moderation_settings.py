"""Add server moderation settings.

Revision ID: 2f74b3c1d91e
Revises: 8c1d7e4ab222
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2f74b3c1d91e"
down_revision = "8c1d7e4ab222"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_moderation_settings",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("mute_role_id", sa.BigInteger(), nullable=True),
        sa.Column("default_mute_minutes", sa.Integer(), nullable=False),
        sa.Column("max_mute_minutes", sa.Integer(), nullable=False),
        sa.Column("auto_reconnect_voice_on_mute", sa.Boolean(), nullable=False),
        sa.Column("mod_log_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("server_id"),
    )

    op.execute(
        """
        INSERT INTO server_moderation_settings (
            server_id,
            mute_role_id,
            default_mute_minutes,
            max_mute_minutes,
            auto_reconnect_voice_on_mute,
            mod_log_channel_id,
            updated_at
        )
        SELECT
            server_id,
            NULL,
            60,
            10080,
            true,
            NULL,
            now()
        FROM servers
        """
    )


def downgrade() -> None:
    op.drop_table("server_moderation_settings")

"""Add historical activity import aggregates.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-07-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: str | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "historical_user_activity_daily",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.TIMESTAMP(timezone=False), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["global_users.discord_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("server_id", "user_id", "channel_id", "activity_date"),
    )
    op.create_index(
        "ix_historical_activity_server_date",
        "historical_user_activity_daily",
        ["server_id", "activity_date"],
    )
    op.create_index(
        "ix_historical_activity_server_user_date",
        "historical_user_activity_daily",
        ["server_id", "user_id", "activity_date"],
    )
    op.create_index(
        "ix_historical_activity_server_channel_date",
        "historical_user_activity_daily",
        ["server_id", "channel_id", "activity_date"],
    )

    op.create_table(
        "historical_activity_import_cursors",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_name", sa.String(), nullable=True),
        sa.Column("channel_type", sa.String(), nullable=True),
        sa.Column("last_before_message_id", sa.BigInteger(), nullable=True),
        sa.Column("reached_start", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pages_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("oldest_message_at", sa.DateTime(), nullable=True),
        sa.Column("newest_message_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("server_id", "channel_id"),
    )


def downgrade() -> None:
    op.drop_table("historical_activity_import_cursors")
    op.drop_index("ix_historical_activity_server_channel_date", table_name="historical_user_activity_daily")
    op.drop_index("ix_historical_activity_server_user_date", table_name="historical_user_activity_daily")
    op.drop_index("ix_historical_activity_server_date", table_name="historical_user_activity_daily")
    op.drop_table("historical_user_activity_daily")

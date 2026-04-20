"""add monitored user status events

Revision ID: c8a14e7d2b11
Revises: b3e9a1f4d6c7
Create Date: 2026-04-21 01:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c8a14e7d2b11"
down_revision = "b3e9a1f4d6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitored_user_status_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("monitored_user_id", sa.Uuid(), nullable=False),
        sa.Column("changed_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("from_is_active", sa.Boolean(), nullable=True),
        sa.Column("to_is_active", sa.Boolean(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["monitored_user_id"], ["monitored_users.id"]),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monitored_user_status_events_monitored_user_id",
        "monitored_user_status_events",
        ["monitored_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_monitored_user_status_events_changed_at",
        "monitored_user_status_events",
        ["changed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_monitored_user_status_events_changed_at", table_name="monitored_user_status_events")
    op.drop_index("ix_monitored_user_status_events_monitored_user_id", table_name="monitored_user_status_events")
    op.drop_table("monitored_user_status_events")

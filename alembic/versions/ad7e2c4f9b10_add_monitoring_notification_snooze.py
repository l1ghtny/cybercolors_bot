"""Add temporary notification snoozes for monitored users.

Revision ID: ad7e2c4f9b10
Revises: 9a4b6c8d0e2f
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "ad7e2c4f9b10"
down_revision: str | None = "9a4b6c8d0e2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "monitored_users",
        sa.Column("notification_snoozed_until", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_monitored_users_notification_snoozed_until",
        "monitored_users",
        ["notification_snoozed_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_monitored_users_notification_snoozed_until",
        table_name="monitored_users",
    )
    op.drop_column("monitored_users", "notification_snoozed_until")

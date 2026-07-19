"""Add monitoring notification cooldowns.

Revision ID: be8f1a2c3d40
Revises: ad7e2c4f9b10
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "be8f1a2c3d40"
down_revision: str | None = "ad7e2c4f9b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "server_monitoring_settings",
        sa.Column(
            "notification_cooldown_minutes",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
    )
    op.alter_column(
        "server_monitoring_settings",
        "notification_cooldown_minutes",
        server_default=None,
    )
    op.add_column(
        "monitored_users",
        sa.Column("last_notification_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("monitored_users", "last_notification_at")
    op.drop_column(
        "server_monitoring_settings",
        "notification_cooldown_minutes",
    )

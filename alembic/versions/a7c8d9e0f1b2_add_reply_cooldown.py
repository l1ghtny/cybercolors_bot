"""Add a per-reply trigger cooldown.

Revision ID: a7c8d9e0f1b2
Revises: f5a6b7c8d9e0
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op


revision = "a7c8d9e0f1b2"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "replies",
        sa.Column(
            "cooldown_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("10"),
        ),
    )
    op.create_check_constraint(
        "ck_replies_cooldown_seconds",
        "replies",
        "cooldown_seconds BETWEEN 0 AND 2592000",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_replies_cooldown_seconds",
        "replies",
        type_="check",
    )
    op.drop_column("replies", "cooldown_seconds")

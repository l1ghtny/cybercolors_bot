"""Add explicit notification allowlists to automatic replies.

Revision ID: e2f3a4b5c6d7
Revises: c1e2f3a4b5c6
Create Date: 2026-07-27
"""

import sqlalchemy as sa
from alembic import op


revision = "e2f3a4b5c6d7"
down_revision = "c1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "replies",
        sa.Column(
            "mention_user_ids",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "replies",
        sa.Column(
            "mention_role_ids",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("replies", "mention_role_ids")
    op.drop_column("replies", "mention_user_ids")

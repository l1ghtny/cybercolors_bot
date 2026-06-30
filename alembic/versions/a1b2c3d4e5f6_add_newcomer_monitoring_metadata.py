"""add newcomer monitoring metadata

Revision ID: a1b2c3d4e5f6
Revises: f8c9d0e1f2a3
Create Date: 2026-06-30 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "monitored_users",
        sa.Column("source", sa.String(length=30), nullable=False, server_default="manual"),
    )
    op.add_column("monitored_users", sa.Column("release_due_at", sa.DateTime(), nullable=True))
    op.add_column("monitored_users", sa.Column("released_at", sa.DateTime(), nullable=True))
    op.add_column("monitored_users", sa.Column("release_error", sa.Text(), nullable=True))
    op.alter_column("monitored_users", "source", server_default=None)
    op.create_index("ix_monitored_users_source", "monitored_users", ["source"])
    op.create_index("ix_monitored_users_release_due_at", "monitored_users", ["release_due_at"])


def downgrade() -> None:
    op.drop_index("ix_monitored_users_release_due_at", table_name="monitored_users")
    op.drop_index("ix_monitored_users_source", table_name="monitored_users")
    op.drop_column("monitored_users", "release_error")
    op.drop_column("monitored_users", "released_at")
    op.drop_column("monitored_users", "release_due_at")
    op.drop_column("monitored_users", "source")

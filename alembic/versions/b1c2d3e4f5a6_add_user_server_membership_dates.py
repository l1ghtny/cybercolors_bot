"""add user server membership dates

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-07-07 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("joined_server_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("left_server_at", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE users "
        "SET left_server_at = flagged_absent_at "
        "WHERE is_member = false "
        "AND flagged_absent_at IS NOT NULL "
        "AND left_server_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "left_server_at")
    op.drop_column("users", "joined_server_at")
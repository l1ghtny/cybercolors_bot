"""Merge temp voice and monitoring heads.

Revision ID: d8e9f0a1b2c3
Revises: c2d3e4f5a6b7, c7d8e9f0a1b2
Create Date: 2026-07-09 00:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: str | tuple[str, str] = ("c2d3e4f5a6b7", "c7d8e9f0a1b2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

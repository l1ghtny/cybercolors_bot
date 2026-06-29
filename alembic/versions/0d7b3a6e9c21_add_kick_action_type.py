"""Add kick moderation action type

Revision ID: 0d7b3a6e9c21
Revises: 3ac8b19d5f20
Create Date: 2026-06-28 00:00:00.000000
"""

from alembic import op


revision = "0d7b3a6e9c21"
down_revision = "3ac8b19d5f20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'KICK'")


def downgrade() -> None:
    pass


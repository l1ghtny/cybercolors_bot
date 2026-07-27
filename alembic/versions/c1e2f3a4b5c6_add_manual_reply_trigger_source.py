"""Add manual automatic-reply trigger source.

Revision ID: c1e2f3a4b5c6
Revises: a9c1d4e7f2b6
Create Date: 2026-07-27
"""

from alembic import op


revision = "c1e2f3a4b5c6"
down_revision = "a9c1d4e7f2b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_triggers_source", "triggers", type_="check")
    op.create_check_constraint(
        "ck_triggers_source",
        "triggers",
        "source IN ('representative', 'manual', 'generated')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_triggers_source", "triggers", type_="check")
    op.execute("UPDATE triggers SET source = 'generated' WHERE source = 'manual'")
    op.create_check_constraint(
        "ck_triggers_source",
        "triggers",
        "source IN ('representative', 'generated')",
    )

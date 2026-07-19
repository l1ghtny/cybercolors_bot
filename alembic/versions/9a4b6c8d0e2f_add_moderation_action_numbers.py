"""Add human-readable moderation action numbers.

Revision ID: 9a4b6c8d0e2f
Revises: c5e6f7a8b9d0
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "9a4b6c8d0e2f"
down_revision: str | None = "c5e6f7a8b9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "moderation_actions",
        sa.Column("action_number", sa.BigInteger(), nullable=True),
    )
    op.execute(
        """
        WITH numbered AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY server_id
                    ORDER BY created_at ASC, id ASC
                )::BIGINT AS action_number
            FROM moderation_actions
        )
        UPDATE moderation_actions AS action
        SET action_number = numbered.action_number
        FROM numbered
        WHERE action.id = numbered.id
        """
    )
    op.alter_column(
        "moderation_actions",
        "action_number",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_moderation_actions_server_action_number",
        "moderation_actions",
        ["server_id", "action_number"],
    )
    op.create_table(
        "moderation_action_counters",
        sa.Column(
            "server_id",
            sa.BigInteger(),
            sa.ForeignKey("servers.server_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("last_number", sa.BigInteger(), nullable=False),
    )
    op.execute(
        """
        INSERT INTO moderation_action_counters (server_id, last_number)
        SELECT server_id, MAX(action_number)
        FROM moderation_actions
        GROUP BY server_id
        """
    )


def downgrade() -> None:
    op.drop_table("moderation_action_counters")
    op.drop_constraint(
        "uq_moderation_actions_server_action_number",
        "moderation_actions",
        type_="unique",
    )
    op.drop_column("moderation_actions", "action_number")

"""Add newcomer probation role and restriction settings.

Revision ID: b4c5d6e7f809
Revises: a3b4c5d6e7f8
Create Date: 2026-07-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f809"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "server_security_settings",
        sa.Column("newcomer_member_role_id", sa.BigInteger(), nullable=True),
    )
    for name in (
        "newcomer_block_bot_commands",
        "newcomer_block_attachments",
        "newcomer_block_embeds",
        "newcomer_block_streaming",
        "newcomer_block_threads",
    ):
        op.add_column(
            "server_security_settings",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.alter_column("server_security_settings", name, server_default=None)


def downgrade() -> None:
    for name in (
        "newcomer_block_threads",
        "newcomer_block_streaming",
        "newcomer_block_embeds",
        "newcomer_block_attachments",
        "newcomer_block_bot_commands",
        "newcomer_member_role_id",
    ):
        op.drop_column("server_security_settings", name)

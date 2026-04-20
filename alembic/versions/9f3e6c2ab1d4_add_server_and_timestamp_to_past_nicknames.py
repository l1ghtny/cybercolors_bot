"""add server and timestamp to past nicknames

Revision ID: 9f3e6c2ab1d4
Revises: e3f7fd0a5a2b
Create Date: 2026-04-20 22:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f3e6c2ab1d4"
down_revision = "e3f7fd0a5a2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("past_nicknames", sa.Column("server_id", sa.BigInteger(), nullable=True))
    op.add_column("past_nicknames", sa.Column("recorded_at", sa.DateTime(), nullable=True))

    op.execute("UPDATE past_nicknames SET recorded_at = NOW() WHERE recorded_at IS NULL")
    op.alter_column("past_nicknames", "recorded_at", existing_type=sa.DateTime(), nullable=False)

    op.create_index("ix_past_nicknames_server_id", "past_nicknames", ["server_id"], unique=False)
    op.create_foreign_key(
        "fk_past_nicknames_server_id",
        "past_nicknames",
        "servers",
        ["server_id"],
        ["server_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_past_nicknames_server_id", "past_nicknames", type_="foreignkey")
    op.drop_index("ix_past_nicknames_server_id", table_name="past_nicknames")
    op.drop_column("past_nicknames", "recorded_at")
    op.drop_column("past_nicknames", "server_id")

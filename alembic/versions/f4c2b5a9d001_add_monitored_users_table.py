"""add monitored users table

Revision ID: f4c2b5a9d001
Revises: c1f4d2b8e7aa
Create Date: 2026-04-20 23:59:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f4c2b5a9d001"
down_revision = "c1f4d2b8e7aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitored_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("added_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "user_id", name="uq_monitored_users_server_user"),
    )
    op.create_index("ix_monitored_users_server_id", "monitored_users", ["server_id"], unique=False)
    op.create_index("ix_monitored_users_user_id", "monitored_users", ["user_id"], unique=False)
    op.create_index("ix_monitored_users_is_active", "monitored_users", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_monitored_users_is_active", table_name="monitored_users")
    op.drop_index("ix_monitored_users_user_id", table_name="monitored_users")
    op.drop_index("ix_monitored_users_server_id", table_name="monitored_users")
    op.drop_table("monitored_users")

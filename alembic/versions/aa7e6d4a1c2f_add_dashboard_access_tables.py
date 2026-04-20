"""add dashboard access tables

Revision ID: aa7e6d4a1c2f
Revises: f4c2b5a9d001
Create Date: 2026-04-21 00:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "aa7e6d4a1c2f"
down_revision = "f4c2b5a9d001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_access_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("added_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "user_id", name="uq_dashboard_access_users_server_user"),
    )
    op.create_index("ix_dashboard_access_users_server_id", "dashboard_access_users", ["server_id"], unique=False)
    op.create_index("ix_dashboard_access_users_user_id", "dashboard_access_users", ["user_id"], unique=False)

    op.create_table(
        "dashboard_access_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("added_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "role_id", name="uq_dashboard_access_roles_server_role"),
    )
    op.create_index("ix_dashboard_access_roles_server_id", "dashboard_access_roles", ["server_id"], unique=False)
    op.create_index("ix_dashboard_access_roles_role_id", "dashboard_access_roles", ["role_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_dashboard_access_roles_role_id", table_name="dashboard_access_roles")
    op.drop_index("ix_dashboard_access_roles_server_id", table_name="dashboard_access_roles")
    op.drop_table("dashboard_access_roles")

    op.drop_index("ix_dashboard_access_users_user_id", table_name="dashboard_access_users")
    op.drop_index("ix_dashboard_access_users_server_id", table_name="dashboard_access_users")
    op.drop_table("dashboard_access_users")

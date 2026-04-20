"""add server security settings

Revision ID: d14f6e9b3a55
Revises: c8a14e7d2b11
Create Date: 2026-04-21 01:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d14f6e9b3a55"
down_revision = "c8a14e7d2b11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_security_settings",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("verified_role_id", sa.BigInteger(), nullable=True),
        sa.Column("normal_permissions", sa.BigInteger(), nullable=True),
        sa.Column("lockdown_permissions", sa.BigInteger(), nullable=True),
        sa.Column("lockdown_enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("server_id"),
    )


def downgrade() -> None:
    op.drop_table("server_security_settings")

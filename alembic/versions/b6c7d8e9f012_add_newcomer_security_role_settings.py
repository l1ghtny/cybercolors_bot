"""add newcomer security role settings

Revision ID: b6c7d8e9f012
Revises: a7b8c9d0e1f2
Create Date: 2026-06-29 18:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b6c7d8e9f012"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "server_security_settings",
        sa.Column("newcomer_role_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "server_security_settings",
        sa.Column(
            "newcomer_restriction_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "server_security_settings",
        sa.Column("newcomer_auto_release_minutes", sa.Integer(), nullable=True),
    )
    op.alter_column("server_security_settings", "newcomer_restriction_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("server_security_settings", "newcomer_auto_release_minutes")
    op.drop_column("server_security_settings", "newcomer_restriction_enabled")
    op.drop_column("server_security_settings", "newcomer_role_id")

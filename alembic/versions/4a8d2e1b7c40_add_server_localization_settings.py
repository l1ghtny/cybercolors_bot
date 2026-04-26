"""Add server localization settings.

Revision ID: 4a8d2e1b7c40
Revises: 2f74b3c1d91e
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4a8d2e1b7c40"
down_revision = "2f74b3c1d91e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_localization_settings",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("locale_code", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("server_id"),
    )
    op.execute(
        """
        INSERT INTO server_localization_settings (server_id, locale_code, updated_at)
        SELECT server_id, 'en', now()
        FROM servers
        """
    )


def downgrade() -> None:
    op.drop_table("server_localization_settings")

"""Add server overview settings.

Revision ID: 632b76d67a18
Revises: 521a65c56f07
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "632b76d67a18"
down_revision = "521a65c56f07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("server_overview_settings"):
        return
    op.create_table(
        "server_overview_settings",
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("role_ids", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("server_id"),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("server_overview_settings"):
        op.drop_table("server_overview_settings")

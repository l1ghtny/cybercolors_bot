"""Add activity excluded channels to moderation settings.

Revision ID: 3ac8b19d5f20
Revises: f9a5c31d7e42
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3ac8b19d5f20"
down_revision = "f9a5c31d7e42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "server_moderation_settings",
        sa.Column(
            "activity_excluded_channel_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("server_moderation_settings", "activity_excluded_channel_ids")
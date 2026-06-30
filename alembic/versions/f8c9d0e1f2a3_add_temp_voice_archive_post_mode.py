"""add temp voice archive post mode

Revision ID: f8c9d0e1f2a3
Revises: e6f7a8b9c0d1
Create Date: 2026-06-30 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8c9d0e1f2a3"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "server_temp_voice_settings",
        sa.Column(
            "archive_post_mode",
            sa.String(length=30),
            nullable=False,
            server_default="mod_log_fallback",
        ),
    )
    op.alter_column("server_temp_voice_settings", "archive_post_mode", server_default=None)


def downgrade() -> None:
    op.drop_column("server_temp_voice_settings", "archive_post_mode")

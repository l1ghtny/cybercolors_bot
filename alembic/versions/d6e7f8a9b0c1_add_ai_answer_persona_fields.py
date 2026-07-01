"""Add AI answer persona fields.

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d6e7f8a9b0c1"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("server_ai_settings", sa.Column("answer_persona", sa.Text(), nullable=True))
    op.add_column("server_ai_settings", sa.Column("server_brief", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("server_ai_settings", "server_brief")
    op.drop_column("server_ai_settings", "answer_persona")

"""add scheduled post attachments

Revision ID: e2a3b4c5d6e7
Revises: d1f2a3b4c5d6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e2a3b4c5d6e7"
down_revision: str | None = "d1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_bot_post_attachments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("scheduled_post_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_scheduled_post_attachment_size"),
        sa.CheckConstraint("position >= 0", name="ck_scheduled_post_attachment_position"),
        sa.ForeignKeyConstraint(
            ["scheduled_post_id"], ["scheduled_bot_posts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_scheduled_post_attachment_object_key"),
        sa.UniqueConstraint(
            "scheduled_post_id", "position", name="uq_scheduled_post_attachment_position"
        ),
    )
    op.create_index(
        "ix_scheduled_bot_post_attachments_post_id",
        "scheduled_bot_post_attachments",
        ["scheduled_post_id"],
    )


def downgrade() -> None:
    op.drop_table("scheduled_bot_post_attachments")

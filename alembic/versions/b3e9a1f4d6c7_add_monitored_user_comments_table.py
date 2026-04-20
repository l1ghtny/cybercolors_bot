"""add monitored user comments table

Revision ID: b3e9a1f4d6c7
Revises: aa7e6d4a1c2f
Create Date: 2026-04-21 00:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3e9a1f4d6c7"
down_revision = "aa7e6d4a1c2f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitored_user_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("monitored_user_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["monitored_user_id"], ["monitored_users.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monitored_user_comments_monitored_user_id",
        "monitored_user_comments",
        ["monitored_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_monitored_user_comments_created_at",
        "monitored_user_comments",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_monitored_user_comments_created_at", table_name="monitored_user_comments")
    op.drop_index("ix_monitored_user_comments_monitored_user_id", table_name="monitored_user_comments")
    op.drop_table("monitored_user_comments")

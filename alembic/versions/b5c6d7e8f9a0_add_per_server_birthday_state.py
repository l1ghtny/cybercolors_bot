"""Track birthday greeting and role state per server membership.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-08-07 12:00:00.000000

The legacy birthdays.role_added_at value was global per Discord user. Copy it
to every existing server membership so cleanup remains conservative during the
transition. The legacy column stays in place for rolling-deployment safety and
can be removed after every runtime uses the per-membership fields.
"""

from alembic import op
import sqlalchemy as sa


revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("birthday_greeted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("birthday_role_added_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_birthday_role_added_at_pending",
        "users",
        ["birthday_role_added_at"],
        postgresql_where=sa.text("birthday_role_added_at IS NOT NULL"),
    )
    op.execute(
        """
        UPDATE users AS membership
        SET
            birthday_greeted_at = birthday.role_added_at,
            birthday_role_added_at = birthday.role_added_at
        FROM birthdays AS birthday
        WHERE birthday.user_id = membership.user_id
          AND birthday.role_added_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_users_birthday_role_added_at_pending",
        table_name="users",
    )
    op.drop_column("users", "birthday_role_added_at")
    op.drop_column("users", "birthday_greeted_at")

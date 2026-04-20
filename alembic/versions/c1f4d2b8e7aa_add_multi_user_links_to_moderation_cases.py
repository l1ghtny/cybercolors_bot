"""add multi user links to moderation cases

Revision ID: c1f4d2b8e7aa
Revises: 9f3e6c2ab1d4
Create Date: 2026-04-20 23:40:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid


# revision identifiers, used by Alembic.
revision = "c1f4d2b8e7aa"
down_revision = "9f3e6c2ab1d4"
branch_labels = None
depends_on = None


case_user_role_enum = postgresql.ENUM(
    "PRIMARY_TARGET",
    "TARGET",
    "REPORTER",
    "WITNESS",
    "MODERATOR",
    "RELATED",
    name="caseuserrole",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE caseuserrole AS ENUM (
                'PRIMARY_TARGET',
                'TARGET',
                'REPORTER',
                'WITNESS',
                'MODERATOR',
                'RELATED'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "moderation_case_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", case_user_role_enum, nullable=False),
        sa.Column("added_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["moderation_cases.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "user_id", name="uq_case_user_link"),
    )
    op.create_index("ix_moderation_case_users_case_id", "moderation_case_users", ["case_id"], unique=False)
    op.create_index("ix_moderation_case_users_user_id", "moderation_case_users", ["user_id"], unique=False)

    bind = op.get_bind()
    case_rows = bind.execute(
        sa.text(
            """
            SELECT id, target_user_id, opened_by_user_id, created_at
            FROM moderation_cases
            WHERE target_user_id IS NOT NULL
            """
        )
    ).mappings().all()

    if case_rows:
        case_users_table = sa.table(
            "moderation_case_users",
            sa.column("id", sa.Uuid()),
            sa.column("case_id", sa.Uuid()),
            sa.column("user_id", sa.BigInteger()),
            sa.column("role", case_user_role_enum),
            sa.column("added_by_user_id", sa.BigInteger()),
            sa.column("added_at", sa.DateTime()),
        )
        op.bulk_insert(
            case_users_table,
            [
                {
                    "id": uuid.uuid4(),
                    "case_id": row["id"],
                    "user_id": row["target_user_id"],
                    "role": "PRIMARY_TARGET",
                    "added_by_user_id": row["opened_by_user_id"],
                    "added_at": row["created_at"],
                }
                for row in case_rows
            ],
        )


def downgrade() -> None:
    op.drop_index("ix_moderation_case_users_user_id", table_name="moderation_case_users")
    op.drop_index("ix_moderation_case_users_case_id", table_name="moderation_case_users")
    op.drop_table("moderation_case_users")
    op.execute("DROP TYPE IF EXISTS caseuserrole")

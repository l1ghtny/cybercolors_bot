"""Add intent trigger metadata and reusable reply concepts.

Revision ID: a9c1d4e7f2b6
Revises: f0a1b2c3d4e5
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op


revision = "a9c1d4e7f2b6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "triggers",
        sa.Column(
            "source",
            sa.String(length=32),
            server_default="representative",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_triggers_source",
        "triggers",
        "source IN ('representative', 'generated')",
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY reply_id ORDER BY id) AS position
                FROM triggers
            )
            UPDATE triggers
            SET source = 'generated'
            FROM ranked
            WHERE triggers.id = ranked.id
              AND ranked.position > 5
            """
        )
    )
    op.create_index("ix_triggers_reply_id", "triggers", ["reply_id"], unique=False)
    op.create_index("ix_replies_server_id", "replies", ["server_id"], unique=False)

    op.create_table(
        "reply_concepts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "variants",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "name", name="uq_reply_concepts_server_name"),
    )
    op.create_index(
        "ix_reply_concepts_server_id",
        "reply_concepts",
        ["server_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reply_concepts_server_id", table_name="reply_concepts")
    op.drop_table("reply_concepts")
    op.drop_index("ix_replies_server_id", table_name="replies")
    op.drop_index("ix_triggers_reply_id", table_name="triggers")
    op.drop_constraint("ck_triggers_source", "triggers", type_="check")
    op.drop_column("triggers", "source")

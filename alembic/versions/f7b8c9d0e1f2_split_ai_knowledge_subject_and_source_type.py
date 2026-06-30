"""Split AI knowledge subject and source type.

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _fk_exists(table_name: str, fk_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    if not _column_exists("ai_knowledge_sources", "subject_type"):
        op.add_column(
            "ai_knowledge_sources",
            sa.Column("subject_type", sa.String(length=30), nullable=False, server_default="server"),
        )
        op.alter_column("ai_knowledge_sources", "subject_type", server_default=None)

    if not _column_exists("ai_knowledge_sources", "subject_user_id"):
        op.add_column("ai_knowledge_sources", sa.Column("subject_user_id", sa.BigInteger(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE ai_knowledge_sources
            SET subject_type = 'admin',
                subject_user_id = COALESCE(subject_user_id, created_by_user_id),
                source_type = 'text'
            WHERE source_type = 'admin_note'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_knowledge_sources
            SET subject_type = 'server',
                subject_user_id = NULL,
                source_type = 'text'
            WHERE source_type = 'server_note'
            """
        )
    )

    if not _index_exists("ai_knowledge_sources", "ix_ai_knowledge_sources_subject_type"):
        op.create_index("ix_ai_knowledge_sources_subject_type", "ai_knowledge_sources", ["subject_type"])
    if not _index_exists("ai_knowledge_sources", "ix_ai_knowledge_sources_subject_user_id"):
        op.create_index("ix_ai_knowledge_sources_subject_user_id", "ai_knowledge_sources", ["subject_user_id"])

    if not _fk_exists("ai_knowledge_sources", "fk_ai_knowledge_sources_subject_user_id_global_users"):
        op.create_foreign_key(
            "fk_ai_knowledge_sources_subject_user_id_global_users",
            "ai_knowledge_sources",
            "global_users",
            ["subject_user_id"],
            ["discord_id"],
        )


def downgrade() -> None:
    if _column_exists("ai_knowledge_sources", "subject_type"):
        op.execute(
            sa.text(
                """
                UPDATE ai_knowledge_sources
                SET source_type = 'admin_note'
                WHERE source_type = 'text' AND subject_type = 'admin'
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE ai_knowledge_sources
                SET source_type = 'server_note'
                WHERE source_type = 'text' AND subject_type = 'server'
                """
            )
        )

    if _fk_exists("ai_knowledge_sources", "fk_ai_knowledge_sources_subject_user_id_global_users"):
        op.drop_constraint(
            "fk_ai_knowledge_sources_subject_user_id_global_users",
            "ai_knowledge_sources",
            type_="foreignkey",
        )
    if _index_exists("ai_knowledge_sources", "ix_ai_knowledge_sources_subject_user_id"):
        op.drop_index("ix_ai_knowledge_sources_subject_user_id", table_name="ai_knowledge_sources")
    if _index_exists("ai_knowledge_sources", "ix_ai_knowledge_sources_subject_type"):
        op.drop_index("ix_ai_knowledge_sources_subject_type", table_name="ai_knowledge_sources")
    if _column_exists("ai_knowledge_sources", "subject_user_id"):
        op.drop_column("ai_knowledge_sources", "subject_user_id")
    if _column_exists("ai_knowledge_sources", "subject_type"):
        op.drop_column("ai_knowledge_sources", "subject_type")

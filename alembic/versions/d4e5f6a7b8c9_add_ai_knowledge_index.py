"""Add AI knowledge index tables.

Revision ID: d4e5f6a7b8c9
Revises: b8c9d0e1f2a3
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(
        constraint["name"] == constraint_name
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    )


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    if not _table_exists("ai_knowledge_sources"):
        op.create_table(
            "ai_knowledge_sources",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("server_id", sa.BigInteger(), nullable=False),
            sa.Column("source_type", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("visibility", sa.String(length=30), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("content_text", sa.Text(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("storage_key", sa.String(length=512), nullable=True),
            sa.Column("mime_type", sa.String(length=120), nullable=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("sha256", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("error_code", sa.String(length=80), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("indexed_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["global_users.discord_id"]),
            sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_ai_knowledge_sources_created_by_user_id", "ai_knowledge_sources", ["created_by_user_id"])
    _create_index_if_missing("ix_ai_knowledge_sources_deleted_at", "ai_knowledge_sources", ["deleted_at"])
    _create_index_if_missing("ix_ai_knowledge_sources_server_id", "ai_knowledge_sources", ["server_id"])
    _create_index_if_missing("ix_ai_knowledge_sources_sha256", "ai_knowledge_sources", ["sha256"])
    _create_index_if_missing("ix_ai_knowledge_sources_source_type", "ai_knowledge_sources", ["source_type"])
    _create_index_if_missing("ix_ai_knowledge_sources_status", "ai_knowledge_sources", ["status"])
    _create_index_if_missing("ix_ai_knowledge_sources_visibility", "ai_knowledge_sources", ["visibility"])

    if not _table_exists("ai_knowledge_chunks"):
        op.create_table(
            "ai_knowledge_chunks",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("source_id", sa.Uuid(), nullable=False),
            sa.Column("server_id", sa.BigInteger(), nullable=False),
            sa.Column("chunk_ordinal", sa.Integer(), nullable=False),
            sa.Column("chunk_text", sa.Text(), nullable=False),
            sa.Column("text_hash", sa.String(length=64), nullable=False),
            sa.Column("token_count", sa.Integer(), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=False),
            sa.Column("embedding_provider", sa.String(length=50), nullable=True),
            sa.Column("embedding_model", sa.String(length=120), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
            sa.ForeignKeyConstraint(["source_id"], ["ai_knowledge_sources.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_id", "chunk_ordinal", name="uq_ai_knowledge_chunks_source_ordinal"),
        )
    elif not _unique_constraint_exists("ai_knowledge_chunks", "uq_ai_knowledge_chunks_source_ordinal"):
        op.create_unique_constraint(
            "uq_ai_knowledge_chunks_source_ordinal",
            "ai_knowledge_chunks",
            ["source_id", "chunk_ordinal"],
        )
    _create_index_if_missing("ix_ai_knowledge_chunks_server_id", "ai_knowledge_chunks", ["server_id"])
    _create_index_if_missing("ix_ai_knowledge_chunks_source_id", "ai_knowledge_chunks", ["source_id"])
    _create_index_if_missing("ix_ai_knowledge_chunks_text_hash", "ai_knowledge_chunks", ["text_hash"])

    if not _table_exists("ai_knowledge_index_jobs"):
        op.create_table(
            "ai_knowledge_index_jobs",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("server_id", sa.BigInteger(), nullable=False),
            sa.Column("source_id", sa.Uuid(), nullable=True),
            sa.Column("job_type", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("dedupe_key", sa.String(length=255), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("run_after", sa.DateTime(), nullable=False),
            sa.Column("locked_at", sa.DateTime(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
            sa.ForeignKeyConstraint(["source_id"], ["ai_knowledge_sources.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_ai_knowledge_index_jobs_dedupe_key", "ai_knowledge_index_jobs", ["dedupe_key"])
    _create_index_if_missing("ix_ai_knowledge_index_jobs_job_type", "ai_knowledge_index_jobs", ["job_type"])
    _create_index_if_missing("ix_ai_knowledge_index_jobs_run_after", "ai_knowledge_index_jobs", ["run_after"])
    _create_index_if_missing("ix_ai_knowledge_index_jobs_server_id", "ai_knowledge_index_jobs", ["server_id"])
    _create_index_if_missing("ix_ai_knowledge_index_jobs_source_id", "ai_knowledge_index_jobs", ["source_id"])
    _create_index_if_missing("ix_ai_knowledge_index_jobs_status", "ai_knowledge_index_jobs", ["status"])
    _create_index_if_missing(
        "ix_ai_knowledge_index_jobs_status_run_after",
        "ai_knowledge_index_jobs",
        ["status", "run_after"],
    )


def downgrade() -> None:
    _drop_index_if_exists("ix_ai_knowledge_index_jobs_status_run_after", "ai_knowledge_index_jobs")
    _drop_index_if_exists("ix_ai_knowledge_index_jobs_status", "ai_knowledge_index_jobs")
    _drop_index_if_exists("ix_ai_knowledge_index_jobs_source_id", "ai_knowledge_index_jobs")
    _drop_index_if_exists("ix_ai_knowledge_index_jobs_server_id", "ai_knowledge_index_jobs")
    _drop_index_if_exists("ix_ai_knowledge_index_jobs_run_after", "ai_knowledge_index_jobs")
    _drop_index_if_exists("ix_ai_knowledge_index_jobs_job_type", "ai_knowledge_index_jobs")
    _drop_index_if_exists("ix_ai_knowledge_index_jobs_dedupe_key", "ai_knowledge_index_jobs")
    if _table_exists("ai_knowledge_index_jobs"):
        op.drop_table("ai_knowledge_index_jobs")

    _drop_index_if_exists("ix_ai_knowledge_chunks_text_hash", "ai_knowledge_chunks")
    _drop_index_if_exists("ix_ai_knowledge_chunks_source_id", "ai_knowledge_chunks")
    _drop_index_if_exists("ix_ai_knowledge_chunks_server_id", "ai_knowledge_chunks")
    if _table_exists("ai_knowledge_chunks"):
        op.drop_table("ai_knowledge_chunks")

    _drop_index_if_exists("ix_ai_knowledge_sources_visibility", "ai_knowledge_sources")
    _drop_index_if_exists("ix_ai_knowledge_sources_status", "ai_knowledge_sources")
    _drop_index_if_exists("ix_ai_knowledge_sources_source_type", "ai_knowledge_sources")
    _drop_index_if_exists("ix_ai_knowledge_sources_sha256", "ai_knowledge_sources")
    _drop_index_if_exists("ix_ai_knowledge_sources_server_id", "ai_knowledge_sources")
    _drop_index_if_exists("ix_ai_knowledge_sources_deleted_at", "ai_knowledge_sources")
    _drop_index_if_exists("ix_ai_knowledge_sources_created_by_user_id", "ai_knowledge_sources")
    if _table_exists("ai_knowledge_sources"):
        op.drop_table("ai_knowledge_sources")

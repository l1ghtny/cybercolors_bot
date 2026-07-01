"""Use local AI knowledge embeddings.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-30
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _create_hnsw_index() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_knowledge_chunks_embedding_hnsw
        ON ai_knowledge_chunks
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("DROP INDEX IF EXISTS ix_ai_knowledge_chunks_embedding_hnsw")
    op.execute("DELETE FROM ai_knowledge_chunks")
    op.execute(
        """
        ALTER TABLE ai_knowledge_chunks
        ALTER COLUMN embedding DROP NOT NULL,
        ALTER COLUMN embedding TYPE vector(1024) USING NULL
        """
    )
    _create_hnsw_index()
    op.execute(
        """
        WITH candidate_sources AS (
            SELECT id, server_id
            FROM ai_knowledge_sources
            WHERE deleted_at IS NULL
              AND status NOT IN ('deleted', 'disabled')
              AND content_text IS NOT NULL
              AND btrim(content_text) <> ''
        ),
        updated_sources AS (
            UPDATE ai_knowledge_sources AS source
            SET status = 'queued',
                indexed_at = NULL,
                error_code = NULL,
                error_message = NULL,
                updated_at = now()
            FROM candidate_sources AS candidate
            WHERE source.id = candidate.id
            RETURNING source.id, source.server_id
        )
        INSERT INTO ai_knowledge_index_jobs (
            id,
            server_id,
            source_id,
            job_type,
            status,
            dedupe_key,
            attempt_count,
            run_after,
            locked_at,
            error_message,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            source.server_id,
            source.id,
            'reindex_source',
            'pending',
            source.server_id::text || ':reindex_source:' || source.id::text,
            0,
            now(),
            NULL,
            NULL,
            now(),
            now()
        FROM updated_sources AS source
        WHERE NOT EXISTS (
            SELECT 1
            FROM ai_knowledge_index_jobs AS job
            WHERE job.dedupe_key = source.server_id::text || ':reindex_source:' || source.id::text
              AND job.status IN ('pending', 'running')
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ai_knowledge_chunks_embedding_hnsw")
    op.execute("DELETE FROM ai_knowledge_chunks")
    op.execute(
        """
        ALTER TABLE ai_knowledge_chunks
        ALTER COLUMN embedding DROP NOT NULL,
        ALTER COLUMN embedding TYPE vector(1536) USING NULL
        """
    )
    _create_hnsw_index()

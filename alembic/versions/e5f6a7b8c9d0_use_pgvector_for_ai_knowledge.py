"""Use pgvector for AI knowledge embeddings.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        ALTER TABLE ai_knowledge_chunks
        ALTER COLUMN embedding DROP NOT NULL,
        ALTER COLUMN embedding TYPE vector(1536) USING NULL
        """
    )
    if not _index_exists("ai_knowledge_chunks", "ix_ai_knowledge_chunks_embedding_hnsw"):
        op.execute(
            """
            CREATE INDEX ix_ai_knowledge_chunks_embedding_hnsw
            ON ai_knowledge_chunks
            USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL
            """
        )


def downgrade() -> None:
    if _index_exists("ai_knowledge_chunks", "ix_ai_knowledge_chunks_embedding_hnsw"):
        op.drop_index("ix_ai_knowledge_chunks_embedding_hnsw", table_name="ai_knowledge_chunks")
    op.execute(
        """
        ALTER TABLE ai_knowledge_chunks
        ALTER COLUMN embedding TYPE JSON USING '[]'::json,
        ALTER COLUMN embedding SET NOT NULL
        """
    )

import asyncio
import hashlib
import logging
import math
import os
import re
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, delete, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import AIKnowledgeChunk, AIKnowledgeIndexJob, AIKnowledgeSource, utcnow_utc_tz
from src.modules.ai.knowledge_imports import (
    KnowledgeImportError,
    extract_text_from_file,
    extract_text_from_youtube_url,
)
from src.modules.ai.embeddings import (
    KNOWLEDGE_EMBEDDING_DIMENSIONS,
    KNOWLEDGE_EMBEDDING_MODEL,
    KnowledgeEmbedder,
    get_knowledge_embedder,
)


logger = logging.getLogger(__name__)


KNOWLEDGE_CHUNK_TARGET_TOKENS = 350
KNOWLEDGE_CHUNK_MAX_TOKENS = 450
KNOWLEDGE_CHUNK_OVERLAP_WORDS = 45
KNOWLEDGE_JOB_MAX_ATTEMPTS = 3
READY_SOURCE_STATUSES = {"ready"}
PUBLIC_ANSWER_VISIBILITIES = {"public_answer"}
ACTIVE_JOB_STATUSES = {"pending", "running"}
RETRYABLE_KNOWLEDGE_IMPORT_ERRORS = {
    "youtube_access_challenge",
    "youtube_fetch_failed",
    "youtube_audio_download_failed",
    "modal_transcription_failed",
}
DEFAULT_KNOWLEDGE_MIN_RELEVANCE_SCORE = 0.45


def _env_relevance_score(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    value = default if raw_value is None or not raw_value.strip() else float(raw_value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


KNOWLEDGE_MIN_RELEVANCE_SCORE = _env_relevance_score(
    "AI_KNOWLEDGE_MIN_RELEVANCE_SCORE",
    DEFAULT_KNOWLEDGE_MIN_RELEVANCE_SCORE,
)

_WORD_RE = re.compile(r"\S+")


def vector_literal(values: list[float]) -> str:
    if len(values) != KNOWLEDGE_EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Embedding dimension mismatch: expected {KNOWLEDGE_EMBEDDING_DIMENSIONS}, got {len(values)}"
        )
    return "[" + ",".join(str(float(item)) for item in values) + "]"


def normalize_knowledge_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def hash_knowledge_text(text: str) -> str:
    return hashlib.sha256(normalize_knowledge_text(text).encode("utf-8")).hexdigest()


def build_knowledge_chunks(
    text: str,
    *,
    target_tokens: int = KNOWLEDGE_CHUNK_TARGET_TOKENS,
    max_tokens: int = KNOWLEDGE_CHUNK_MAX_TOKENS,
    overlap_words: int = KNOWLEDGE_CHUNK_OVERLAP_WORDS,
) -> list[dict[str, Any]]:
    normalized = normalize_knowledge_text(text)
    if not normalized:
        return []

    words = _WORD_RE.findall(normalized)
    chunks: list[dict[str, Any]] = []
    current: list[str] = []

    def flush_chunk() -> None:
        if not current:
            return
        chunk_text = " ".join(current).strip()
        chunks.append(
            {
                "chunk_ordinal": len(chunks),
                "chunk_text": chunk_text,
                "text_hash": hash_knowledge_text(chunk_text),
                "token_count": estimate_token_count(chunk_text),
            }
        )

    for word in words:
        candidate = " ".join([*current, word])
        candidate_tokens = estimate_token_count(candidate)
        if current and candidate_tokens > max_tokens:
            flush_chunk()
            current = current[-overlap_words:] if overlap_words > 0 else []
        current.append(word)
        if estimate_token_count(" ".join(current)) >= target_tokens:
            flush_chunk()
            current = current[-overlap_words:] if overlap_words > 0 else []

    if current:
        final_text = " ".join(current).strip()
        if not chunks or hash_knowledge_text(final_text) != chunks[-1]["text_hash"]:
            flush_chunk()

    return chunks


def knowledge_source_index_text(source: AIKnowledgeSource) -> str:
    parts: list[str] = []
    title = normalize_knowledge_text(source.title)
    if title:
        parts.append(f"Title: {title}")
    content = normalize_knowledge_text(source.content_text)
    if content:
        parts.append(content)
    return "\n\n".join(parts)


def knowledge_job_dedupe_key(
    *,
    server_id: int,
    job_type: str,
    source_id: UUID | str | None = None,
) -> str:
    source_part = str(source_id) if source_id is not None else "server"
    return f"{server_id}:{job_type}:{source_part}"


async def queue_knowledge_index_job(
    session: AsyncSession,
    *,
    server_id: int,
    source_id: UUID | None,
    job_type: str = "index_source",
    run_after=None,
) -> AIKnowledgeIndexJob:
    dedupe_key = knowledge_job_dedupe_key(server_id=server_id, job_type=job_type, source_id=source_id)
    existing = (
        await session.exec(
            select(AIKnowledgeIndexJob).where(
                AIKnowledgeIndexJob.dedupe_key == dedupe_key,
                AIKnowledgeIndexJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
    ).first()
    if existing is not None:
        return existing

    job = AIKnowledgeIndexJob(
        server_id=server_id,
        source_id=source_id,
        job_type=job_type,
        status="pending",
        dedupe_key=dedupe_key,
        run_after=run_after or utcnow_utc_tz(),
    )
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def upsert_admin_text_source(
    session: AsyncSession,
    *,
    server_id: int,
    title: str,
    content_text: str,
    created_by_user_id: int | None = None,
    visibility: str = "public_answer",
    source_type: str = "text",
    subject_type: str = "admin",
    subject_user_id: int | None = None,
) -> tuple[AIKnowledgeSource, AIKnowledgeIndexJob]:
    source = AIKnowledgeSource(
        server_id=server_id,
        source_type=source_type,
        subject_type=subject_type,
        subject_user_id=subject_user_id if subject_user_id is not None else created_by_user_id,
        status="queued",
        visibility=visibility,
        title=title,
        content_text=content_text,
        created_by_user_id=created_by_user_id,
        metadata_json={},
    )
    session.add(source)
    await session.flush()
    await session.refresh(source)
    job = await queue_knowledge_index_job(session, server_id=server_id, source_id=source.id)
    return source, job


async def claim_next_knowledge_index_job(
    session: AsyncSession,
    *,
    server_id: int | None = None,
) -> AIKnowledgeIndexJob | None:
    now = utcnow_utc_tz()
    statement = (
        select(AIKnowledgeIndexJob)
        .where(
            AIKnowledgeIndexJob.status == "pending",
            AIKnowledgeIndexJob.run_after <= now,
        )
        .order_by(AIKnowledgeIndexJob.run_after, AIKnowledgeIndexJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if server_id is not None:
        statement = statement.where(AIKnowledgeIndexJob.server_id == server_id)
    job = (await session.exec(statement)).first()
    if job is None:
        return None
    job.status = "running"
    job.locked_at = now
    job.updated_at = now
    await session.flush()
    return job


async def process_knowledge_index_job(session: AsyncSession, job: AIKnowledgeIndexJob) -> None:
    await process_knowledge_index_job_with_embedder(session, job, embedder=None)


async def process_knowledge_index_job_with_embedder(
    session: AsyncSession,
    job: AIKnowledgeIndexJob,
    *,
    embedder: KnowledgeEmbedder | None,
) -> None:
    now = utcnow_utc_tz()
    if job.job_type not in {"index_source", "reindex_source"} or job.source_id is None:
        await _mark_job_failed(session, job, f"Unsupported knowledge index job: {job.job_type}")
        return

    source = await session.get(AIKnowledgeSource, job.source_id)
    if source is None or source.server_id != job.server_id:
        await _mark_job_failed(session, job, "Knowledge source was not found for this server.")
        return

    source.status = "processing"
    source.updated_at = now
    await session.flush()

    try:
        index_text = await _prepare_source_index_text(source)
    except KnowledgeImportError as exc:
        retry = exc.code in RETRYABLE_KNOWLEDGE_IMPORT_ERRORS
        source.error_code = exc.code
        source.error_message = str(exc)
        source.indexed_at = None
        source.updated_at = now
        logger.exception(
            "knowledge_import_failed server_id=%s source_id=%s job_id=%s error_code=%s retry=%s",
            source.server_id,
            source.id,
            job.id,
            exc.code,
            retry,
        )
        await _mark_job_failed(session, job, str(exc), retry=retry)
        source.status = "queued" if job.status == "pending" else "failed"
        await session.flush()
        return

    chunks = build_knowledge_chunks(index_text)
    if not chunks:
        source.status = "failed"
        source.error_code = "empty_source"
        source.error_message = "No indexable text was found for this knowledge source."
        source.indexed_at = None
        source.updated_at = now
        job.status = "failed"
        job.error_message = source.error_message
        job.locked_at = None
        job.updated_at = now
        await session.flush()
        return

    active_embedder = embedder or await get_knowledge_embedder()
    embeddings = await active_embedder.embed_texts([chunk["chunk_text"] for chunk in chunks])
    if len(embeddings) != len(chunks):
        raise ValueError(f"Embedding count mismatch: expected {len(chunks)}, got {len(embeddings)}")

    await session.exec(delete(AIKnowledgeChunk).where(AIKnowledgeChunk.source_id == source.id))
    for chunk, embedding in zip(chunks, embeddings):
        session.add(
            AIKnowledgeChunk(
                source_id=source.id,
                server_id=source.server_id,
                chunk_ordinal=chunk["chunk_ordinal"],
                chunk_text=chunk["chunk_text"],
                text_hash=chunk["text_hash"],
                token_count=chunk["token_count"],
                embedding=embedding,
                embedding_provider=active_embedder.provider_name,
                embedding_model=active_embedder.model,
            )
        )

    source.status = "ready"
    source.error_code = None
    source.error_message = None
    source.indexed_at = now
    source.updated_at = now
    job.status = "completed"
    job.error_message = None
    job.locked_at = None
    job.updated_at = now
    await session.flush()


async def run_knowledge_index_job_once(
    session: AsyncSession,
    *,
    server_id: int | None = None,
    embedder: KnowledgeEmbedder | None = None,
) -> bool:
    job = await claim_next_knowledge_index_job(session, server_id=server_id)
    if job is None:
        return False
    try:
        if embedder is None:
            await process_knowledge_index_job(session, job)
        else:
            await process_knowledge_index_job_with_embedder(session, job, embedder=embedder)
    except Exception as exc:
        logger.exception(
            "knowledge_index_job_failed server_id=%s source_id=%s job_id=%s",
            job.server_id,
            job.source_id,
            job.id,
        )
        await _mark_job_failed(session, job, str(exc))
    return True


async def _prepare_source_index_text(source: AIKnowledgeSource) -> str:
    if source.source_type == "file":
        if not source.storage_key:
            raise KnowledgeImportError("file_not_uploaded", "No uploaded file is attached to this source.")
        metadata = dict(source.metadata_json or {})
        extracted_text, extraction_metadata = await asyncio.to_thread(
            extract_text_from_file,
            storage_key=source.storage_key,
            mime_type=source.mime_type,
            filename=metadata.get("original_filename") or source.title,
        )
        source.content_text = extracted_text
        source.metadata_json = {
            **metadata,
            "import": {
                **dict(metadata.get("import") or {}),
                **extraction_metadata,
            },
        }
    elif source.source_type == "youtube":
        if not source.source_url:
            raise KnowledgeImportError("youtube_url_missing", "No YouTube URL is attached to this source.")
        metadata = dict(source.metadata_json or {})
        extracted_text, extraction_metadata = await asyncio.to_thread(extract_text_from_youtube_url, source.source_url)
        source.content_text = extracted_text
        source.metadata_json = {
            **metadata,
            "import": {
                **dict(metadata.get("import") or {}),
                **extraction_metadata,
            },
        }
        if not source.title and extraction_metadata.get("video_title"):
            source.title = str(extraction_metadata["video_title"])[:255]

    return knowledge_source_index_text(source)


async def search_server_knowledge(
    session: AsyncSession,
    *,
    server_id: int,
    query: str,
    visibility: str = "public_answer",
    limit: int = 5,
    embedder: KnowledgeEmbedder | None = None,
    min_score: float | None = None,
    source_id: str | None = None,
) -> list[dict[str, Any]]:
    normalized_query = normalize_knowledge_text(query)
    if not normalized_query:
        return []

    visibility_set = PUBLIC_ANSWER_VISIBILITIES if visibility == "public_answer" else {visibility}
    active_embedder = embedder or await get_knowledge_embedder()
    query_embedding = (await active_embedder.embed_texts([normalized_query]))[0]
    query_vector = vector_literal(query_embedding)
    bounded_limit = min(max(int(limit), 1), 20)
    effective_min_score = (
        KNOWLEDGE_MIN_RELEVANCE_SCORE if min_score is None else float(min_score)
    )
    if not math.isfinite(effective_min_score) or not 0.0 <= effective_min_score <= 1.0:
        raise ValueError("min_score must be between 0 and 1")
    source_filter = "AND source.id = CAST(:source_id AS uuid)" if source_id else ""
    statement = text(
        f"""
        SELECT
            chunk.id AS chunk_id,
            chunk.source_id AS source_id,
            source.source_type AS source_type,
            source.subject_type AS subject_type,
            source.subject_user_id AS subject_user_id,
            source.title AS title,
            source.visibility AS visibility,
            chunk.chunk_ordinal AS chunk_ordinal,
            chunk.chunk_text AS chunk_text,
            source.source_url AS source_url,
            source.indexed_at AS indexed_at,
            chunk.embedding <=> CAST(:query_embedding AS vector) AS distance
        FROM ai_knowledge_chunks AS chunk
        JOIN ai_knowledge_sources AS source ON source.id = chunk.source_id
        WHERE chunk.server_id = :server_id
          AND source.server_id = :server_id
          AND source.status IN :ready_statuses
          AND source.visibility IN :visibility_values
          AND source.deleted_at IS NULL
          AND chunk.embedding IS NOT NULL
          {source_filter}
        ORDER BY chunk.embedding <=> CAST(:query_embedding AS vector)
        LIMIT :limit
        """
    ).bindparams(
        bindparam("ready_statuses", expanding=True),
        bindparam("visibility_values", expanding=True),
    )
    params: dict[str, Any] = {
        "server_id": server_id,
        "ready_statuses": list(READY_SOURCE_STATUSES),
        "visibility_values": list(visibility_set),
        "query_embedding": query_vector,
        "limit": bounded_limit,
    }
    if source_id:
        params["source_id"] = source_id
    rows = (
        await session.exec(
            statement,
            params=params,
        )
    ).all()

    results: list[dict[str, Any]] = []
    for row in rows:
        distance = float(row.distance)
        score = 1 - distance
        if score < effective_min_score:
            continue
        results.append(
            {
                "source_id": str(row.source_id),
                "source_type": row.source_type,
                "subject_type": row.subject_type,
                "subject_user_id": str(row.subject_user_id) if row.subject_user_id is not None else None,
                "title": row.title,
                "visibility": row.visibility,
                "chunk_id": str(row.chunk_id),
                "chunk_ordinal": row.chunk_ordinal,
                "text": row.chunk_text,
                "score": score,
                "distance": distance,
                "source_url": row.source_url,
                "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
                "embedding_provider": active_embedder.provider_name,
                "embedding_model": active_embedder.model,
            }
        )
    return results


async def get_public_knowledge_for_subject_users(
    session: AsyncSession,
    *,
    server_id: int,
    user_ids: list[int],
    limit_per_user: int = 3,
) -> list[dict[str, Any]]:
    unique_user_ids = list(dict.fromkeys(int(user_id) for user_id in user_ids if user_id is not None))
    if not unique_user_ids:
        return []

    bounded_limit = min(max(int(limit_per_user), 1), 10)
    statement = text(
        """
        SELECT *
        FROM (
            SELECT
                chunk.id AS chunk_id,
                chunk.source_id AS source_id,
                source.source_type AS source_type,
                source.subject_type AS subject_type,
                source.subject_user_id AS subject_user_id,
                source.title AS title,
                source.visibility AS visibility,
                chunk.chunk_ordinal AS chunk_ordinal,
                chunk.chunk_text AS chunk_text,
                source.source_url AS source_url,
                source.indexed_at AS indexed_at,
                row_number() OVER (
                    PARTITION BY source.subject_user_id
                    ORDER BY source.indexed_at DESC NULLS LAST, source.updated_at DESC, chunk.chunk_ordinal ASC
                ) AS subject_rank
            FROM ai_knowledge_chunks AS chunk
            JOIN ai_knowledge_sources AS source ON source.id = chunk.source_id
            WHERE chunk.server_id = :server_id
              AND source.server_id = :server_id
              AND source.status IN :ready_statuses
              AND source.visibility IN :visibility_values
              AND source.deleted_at IS NULL
              AND source.subject_user_id IN :user_ids
        ) AS ranked
        WHERE subject_rank <= :limit_per_user
        ORDER BY subject_user_id, subject_rank
        """
    ).bindparams(
        bindparam("ready_statuses", expanding=True),
        bindparam("visibility_values", expanding=True),
        bindparam("user_ids", expanding=True),
    )
    rows = (
        await session.exec(
            statement,
            params={
                "server_id": server_id,
                "ready_statuses": list(READY_SOURCE_STATUSES),
                "visibility_values": list(PUBLIC_ANSWER_VISIBILITIES),
                "user_ids": unique_user_ids,
                "limit_per_user": bounded_limit,
            },
        )
    ).all()

    return [
        {
            "source_id": str(row.source_id),
            "source_type": row.source_type,
            "subject_type": row.subject_type,
            "subject_user_id": str(row.subject_user_id) if row.subject_user_id is not None else None,
            "title": row.title,
            "visibility": row.visibility,
            "chunk_id": str(row.chunk_id),
            "chunk_ordinal": row.chunk_ordinal,
            "text": row.chunk_text,
            "source_url": row.source_url,
            "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
            "retrieval_reason": "subject_user",
        }
        for row in rows
    ]


async def _mark_job_failed(
    session: AsyncSession,
    job: AIKnowledgeIndexJob,
    error_message: str,
    *,
    retry: bool = True,
) -> None:
    now = utcnow_utc_tz()
    job.attempt_count += 1
    job.error_message = error_message[:2000]
    job.locked_at = None
    job.updated_at = now
    if not retry or job.attempt_count >= KNOWLEDGE_JOB_MAX_ATTEMPTS:
        job.status = "failed"
    else:
        job.status = "pending"
        job.run_after = now + timedelta(minutes=2 ** job.attempt_count)
    await session.flush()

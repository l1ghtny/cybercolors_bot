from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.ai_knowledge import (
    AIKnowledgeJobListModel,
    AIKnowledgeJobReadModel,
    AIKnowledgeProcessOneResponseModel,
    AIKnowledgeSearchRequestModel,
    AIKnowledgeSearchResponseModel,
    AIKnowledgeSourceCreateModel,
    AIKnowledgeSourceListModel,
    AIKnowledgeSourceReadModel,
    AIKnowledgeSourceUpdateModel,
)
from src.db.models import AIKnowledgeChunk, AIKnowledgeIndexJob, AIKnowledgeSource, GlobalUser, Server, utcnow_utc_tz
from src.modules.ai.knowledge import queue_knowledge_index_job, run_knowledge_index_job_once, search_server_knowledge
from src.modules.ai.knowledge_imports import KnowledgeImportError, store_knowledge_upload


async def _ensure_server(session: AsyncSession, server_id: int) -> None:
    server = await session.get(Server, server_id)
    if server is None:
        session.add(Server(server_id=server_id, server_name=str(server_id)))
        await session.flush()


async def _ensure_global_user(session: AsyncSession, user_id: int) -> None:
    user = await session.get(GlobalUser, user_id)
    if user is None:
        session.add(GlobalUser(discord_id=user_id, username=None))
        await session.flush()


async def _chunk_counts(session: AsyncSession, source_ids: list[UUID]) -> dict[UUID, int]:
    if not source_ids:
        return {}
    rows = (
        await session.exec(
            select(AIKnowledgeChunk.source_id, func.count(AIKnowledgeChunk.id))
            .where(AIKnowledgeChunk.source_id.in_(source_ids))
            .group_by(AIKnowledgeChunk.source_id)
        )
    ).all()
    return {source_id: int(count or 0) for source_id, count in rows}


def _source_to_model(source: AIKnowledgeSource, *, chunk_count: int = 0) -> AIKnowledgeSourceReadModel:
    return AIKnowledgeSourceReadModel(
        id=str(source.id),
        server_id=str(source.server_id),
        source_type=source.source_type,
        subject_type=source.subject_type,
        subject_user_id=str(source.subject_user_id) if source.subject_user_id is not None else None,
        status=source.status,
        visibility=source.visibility,
        title=source.title,
        content_text=source.content_text,
        source_url=source.source_url,
        storage_key=source.storage_key,
        mime_type=source.mime_type,
        size_bytes=source.size_bytes,
        sha256=source.sha256,
        metadata_json=dict(source.metadata_json or {}),
        created_by_user_id=str(source.created_by_user_id) if source.created_by_user_id is not None else None,
        error_code=source.error_code,
        error_message=source.error_message,
        chunk_count=chunk_count,
        created_at=source.created_at,
        updated_at=source.updated_at,
        indexed_at=source.indexed_at,
        deleted_at=source.deleted_at,
    )


def _job_to_model(job: AIKnowledgeIndexJob) -> AIKnowledgeJobReadModel:
    return AIKnowledgeJobReadModel(
        id=str(job.id),
        server_id=str(job.server_id),
        source_id=str(job.source_id) if job.source_id is not None else None,
        job_type=job.job_type,
        status=job.status,
        dedupe_key=job.dedupe_key,
        attempt_count=job.attempt_count,
        run_after=job.run_after,
        locked_at=job.locked_at,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _get_source(session: AsyncSession, server_id: int, source_id: UUID) -> AIKnowledgeSource:
    source = await session.get(AIKnowledgeSource, source_id)
    if source is None or source.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI knowledge source not found")
    return source


async def list_knowledge_sources(
    session: AsyncSession,
    *,
    server_id: int,
    status_filter: str | None = None,
    visibility: str | None = None,
    source_type: str | None = None,
    subject_type: str | None = None,
    subject_user_id: int | None = None,
    include_deleted: bool = False,
    limit: int = 100,
) -> AIKnowledgeSourceListModel:
    statement = select(AIKnowledgeSource).where(AIKnowledgeSource.server_id == server_id)
    if not include_deleted:
        statement = statement.where(AIKnowledgeSource.deleted_at.is_(None))
    if status_filter and status_filter != "all":
        statement = statement.where(AIKnowledgeSource.status == status_filter)
    if visibility:
        statement = statement.where(AIKnowledgeSource.visibility == visibility)
    if source_type:
        statement = statement.where(AIKnowledgeSource.source_type == source_type)
    if subject_type:
        statement = statement.where(AIKnowledgeSource.subject_type == subject_type)
    if subject_user_id is not None:
        statement = statement.where(AIKnowledgeSource.subject_user_id == subject_user_id)
    statement = statement.order_by(AIKnowledgeSource.updated_at.desc(), AIKnowledgeSource.created_at.desc()).limit(limit)
    sources = (await session.exec(statement)).all()
    counts = await _chunk_counts(session, [source.id for source in sources if source.id is not None])
    return AIKnowledgeSourceListModel(
        items=[_source_to_model(source, chunk_count=counts.get(source.id, 0)) for source in sources]
    )


async def get_knowledge_source(session: AsyncSession, *, server_id: int, source_id: UUID) -> AIKnowledgeSourceReadModel:
    source = await _get_source(session, server_id, source_id)
    counts = await _chunk_counts(session, [source.id])
    return _source_to_model(source, chunk_count=counts.get(source.id, 0))


async def create_knowledge_source(
    session: AsyncSession,
    *,
    server_id: int,
    body: AIKnowledgeSourceCreateModel,
    created_by_user_id: int,
) -> AIKnowledgeSourceReadModel:
    await _ensure_server(session, server_id)
    await _ensure_global_user(session, created_by_user_id)
    if body.subject_user_id is not None:
        await _ensure_global_user(session, body.subject_user_id)
    now = utcnow_utc_tz()
    source = AIKnowledgeSource(
        server_id=server_id,
        source_type=body.source_type,
        subject_type=body.subject_type,
        subject_user_id=body.subject_user_id,
        status="queued" if body.queue_index else "draft",
        visibility=body.visibility,
        title=body.title,
        content_text=body.content_text,
        source_url=body.source_url,
        metadata_json=body.metadata_json,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(source)
    await session.flush()
    await session.refresh(source)
    if body.queue_index:
        await queue_knowledge_index_job(session, server_id=server_id, source_id=source.id)
    return _source_to_model(source)


async def create_file_knowledge_source(
    session: AsyncSession,
    *,
    server_id: int,
    created_by_user_id: int,
    title: str,
    payload: bytes,
    filename: str,
    content_type: str | None,
    subject_type: str = "server",
    subject_user_id: int | None = None,
    visibility: str = "public_answer",
    queue_index: bool = True,
) -> AIKnowledgeSourceReadModel:
    await _ensure_server(session, server_id)
    await _ensure_global_user(session, created_by_user_id)
    if subject_type == "server":
        subject_user_id = None
    elif subject_type == "admin":
        if subject_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="subject_user_id is required when subject_type is admin",
            )
        await _ensure_global_user(session, subject_user_id)
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid subject_type")

    if visibility not in {"public_answer", "admin_answer", "moderation"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid visibility")

    now = utcnow_utc_tz()
    source = AIKnowledgeSource(
        server_id=server_id,
        source_type="file",
        subject_type=subject_type,
        subject_user_id=subject_user_id,
        status="queued" if queue_index else "draft",
        visibility=visibility,
        title=title.strip() or filename,
        mime_type=content_type,
        metadata_json={"original_filename": filename},
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(source)
    await session.flush()

    try:
        upload = store_knowledge_upload(
            server_id=server_id,
            source_id=source.id,
            filename=filename,
            payload=payload,
        )
    except KnowledgeImportError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    source.storage_key = upload["storage_key"]
    source.size_bytes = upload["size_bytes"]
    source.sha256 = upload["sha256"]
    source.updated_at = utcnow_utc_tz()
    session.add(source)
    await session.flush()
    await session.refresh(source)
    if queue_index:
        await queue_knowledge_index_job(session, server_id=server_id, source_id=source.id)
    return _source_to_model(source)


async def update_knowledge_source(
    session: AsyncSession,
    *,
    server_id: int,
    source_id: UUID,
    body: AIKnowledgeSourceUpdateModel,
) -> AIKnowledgeSourceReadModel:
    source = await _get_source(session, server_id, source_id)
    if source.status == "deleted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deleted knowledge sources cannot be updated")

    if body.source_type is not None:
        source.source_type = body.source_type
        if source.status == "ready":
            source.status = "draft"
    if body.subject_type is not None:
        source.subject_type = body.subject_type
    if "subject_user_id" in body.model_fields_set:
        source.subject_user_id = body.subject_user_id
    if source.subject_type == "server":
        source.subject_user_id = None
    if source.subject_type == "admin" and source.subject_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="subject_user_id is required when subject_type is admin",
        )
    if source.subject_user_id is not None:
        await _ensure_global_user(session, source.subject_user_id)
    if body.visibility is not None:
        source.visibility = body.visibility
    if body.status is not None:
        source.status = body.status
    if body.title is not None:
        source.title = body.title
    if "content_text" in body.model_fields_set:
        source.content_text = body.content_text
        if source.status == "ready":
            source.status = "draft"
    if "source_url" in body.model_fields_set:
        source.source_url = body.source_url
    if body.metadata_json is not None:
        source.metadata_json = body.metadata_json
    source.updated_at = utcnow_utc_tz()
    session.add(source)
    await session.flush()
    await session.refresh(source)
    counts = await _chunk_counts(session, [source.id])
    return _source_to_model(source, chunk_count=counts.get(source.id, 0))


async def delete_knowledge_source(session: AsyncSession, *, server_id: int, source_id: UUID) -> None:
    source = await _get_source(session, server_id, source_id)
    now = utcnow_utc_tz()
    source.status = "deleted"
    source.deleted_at = now
    source.updated_at = now
    session.add(source)
    await session.flush()


async def queue_knowledge_source_reindex(
    session: AsyncSession,
    *,
    server_id: int,
    source_id: UUID,
) -> AIKnowledgeJobReadModel:
    source = await _get_source(session, server_id, source_id)
    if source.deleted_at is not None or source.status == "deleted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deleted knowledge sources cannot be reindexed")
    source.status = "queued"
    source.error_code = None
    source.error_message = None
    source.updated_at = utcnow_utc_tz()
    session.add(source)
    job = await queue_knowledge_index_job(
        session,
        server_id=server_id,
        source_id=source.id,
        job_type="reindex_source",
    )
    return _job_to_model(job)


async def list_knowledge_jobs(
    session: AsyncSession,
    *,
    server_id: int,
    status_filter: str | None = None,
    source_id: UUID | None = None,
    limit: int = 100,
) -> AIKnowledgeJobListModel:
    statement = select(AIKnowledgeIndexJob).where(AIKnowledgeIndexJob.server_id == server_id)
    if status_filter and status_filter != "all":
        statement = statement.where(AIKnowledgeIndexJob.status == status_filter)
    if source_id is not None:
        statement = statement.where(AIKnowledgeIndexJob.source_id == source_id)
    statement = statement.order_by(AIKnowledgeIndexJob.created_at.desc()).limit(limit)
    jobs = (await session.exec(statement)).all()
    return AIKnowledgeJobListModel(items=[_job_to_model(job) for job in jobs])


async def search_knowledge_sources(
    session: AsyncSession,
    *,
    server_id: int,
    body: AIKnowledgeSearchRequestModel,
) -> AIKnowledgeSearchResponseModel:
    results = await search_server_knowledge(
        session=session,
        server_id=server_id,
        query=body.query,
        visibility=body.visibility,
        limit=body.limit,
    )
    return AIKnowledgeSearchResponseModel(items=results)


async def process_one_knowledge_job(session: AsyncSession, *, server_id: int) -> AIKnowledgeProcessOneResponseModel:
    processed = await run_knowledge_index_job_once(session, server_id=server_id)
    return AIKnowledgeProcessOneResponseModel(processed=processed)

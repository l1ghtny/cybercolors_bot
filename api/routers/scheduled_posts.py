import mimetypes
from datetime import datetime
from pathlib import PurePath
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.models.scheduled_posts import (
    ScheduledPostReadModel,
    ScheduledPostRunReadModel,
    ScheduledPostStatusModel,
    ScheduledPostWriteModel,
)
from api.services.scheduled_posts import (
    create_scheduled_post,
    delete_scheduled_post,
    list_scheduled_post_runs,
    list_scheduled_posts,
    send_scheduled_post_now,
    set_scheduled_post_status,
    update_scheduled_post,
)
from api.services.scheduled_post_storage import (
    ALLOWED_ATTACHMENT_TYPES,
    MAX_ATTACHMENT_FILE_BYTES,
    MAX_ATTACHMENT_FILES,
    MAX_ATTACHMENT_TOTAL_BYTES,
)
from src.db.database import get_session


scheduled_posts_router = APIRouter(
    prefix="/servers/{server_id}/scheduled-posts",
    dependencies=[Depends(require_server_dashboard_access)],
)


async def _read_attachment_files(files: list[UploadFile]) -> list[tuple[str, bytes, str]]:
    if len(files) > MAX_ATTACHMENT_FILES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Attach at most {MAX_ATTACHMENT_FILES} files",
        )
    payloads: list[tuple[str, bytes, str]] = []
    total_bytes = 0
    for index, file in enumerate(files):
        filename = PurePath(file.filename or f"attachment-{index + 1}").name[:255]
        content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_ATTACHMENT_TYPES:
            guessed = mimetypes.guess_type(filename)[0]
            content_type = guessed.lower() if guessed else content_type
        if content_type not in ALLOWED_ATTACHMENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"{filename} is not a supported attachment type",
            )
        data = await file.read(MAX_ATTACHMENT_FILE_BYTES + 1)
        await file.close()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{filename} is empty",
            )
        if len(data) > MAX_ATTACHMENT_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"{filename} exceeds the 10 MB attachment limit",
            )
        total_bytes += len(data)
        if total_bytes > MAX_ATTACHMENT_TOTAL_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Attachments exceed the 25 MB total limit",
            )
        payloads.append((filename, data, content_type))
    return payloads


def _form_body(
    *,
    channel_id: str,
    content: str,
    mention_everyone: bool,
    mention_user_ids: list[str],
    mention_role_ids: list[str],
    schedule_type: Literal["once", "interval"],
    timezone: str,
    next_run_at: datetime,
    interval_seconds: int | None,
) -> ScheduledPostWriteModel:
    return ScheduledPostWriteModel(
        channel_id=channel_id,
        content=content,
        mention_everyone=mention_everyone,
        mention_user_ids=mention_user_ids,
        mention_role_ids=mention_role_ids,
        schedule_type=schedule_type,
        timezone=timezone,
        next_run_at=next_run_at,
        interval_seconds=interval_seconds,
    )


@scheduled_posts_router.get("", response_model=list[ScheduledPostReadModel])
async def get_scheduled_posts(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await list_scheduled_posts(session, server_id)


@scheduled_posts_router.get("/runs", response_model=list[ScheduledPostRunReadModel])
async def get_scheduled_post_runs(
    server_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await list_scheduled_post_runs(session, server_id, limit=limit)


@scheduled_posts_router.post("", response_model=ScheduledPostReadModel, status_code=status.HTTP_201_CREATED)
async def post_scheduled_post(
    server_id: int,
    body: ScheduledPostWriteModel,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await create_scheduled_post(
        session, server_id=server_id, actor_user_id=actor_user_id, body=body
    )


@scheduled_posts_router.post(
    "/media", response_model=ScheduledPostReadModel, status_code=status.HTTP_201_CREATED
)
async def post_scheduled_post_with_media(
    server_id: int,
    channel_id: str = Form(..., pattern=r"^\d+$"),
    content: str = Form(default="", max_length=2000),
    mention_everyone: bool = Form(default=False),
    mention_user_ids: list[str] = Form(default=[]),
    mention_role_ids: list[str] = Form(default=[]),
    schedule_type: Literal["once", "interval"] = Form(...),
    timezone: str = Form(default="UTC"),
    next_run_at: datetime = Form(...),
    interval_seconds: int | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(
        require_server_permission("communications.scheduled_posts.manage")
    ),
):
    attachments = await _read_attachment_files(files)
    return await create_scheduled_post(
        session,
        server_id=server_id,
        actor_user_id=actor_user_id,
        body=_form_body(
            channel_id=channel_id,
            content=content,
            mention_everyone=mention_everyone,
            mention_user_ids=mention_user_ids,
            mention_role_ids=mention_role_ids,
            schedule_type=schedule_type,
            timezone=timezone,
            next_run_at=next_run_at,
            interval_seconds=interval_seconds,
        ),
        attachments=attachments,
    )


@scheduled_posts_router.put("/{post_id}", response_model=ScheduledPostReadModel)
async def put_scheduled_post(
    server_id: int,
    post_id: UUID,
    body: ScheduledPostWriteModel,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await update_scheduled_post(
        session,
        server_id=server_id,
        post_id=post_id,
        actor_user_id=actor_user_id,
        body=body,
    )


@scheduled_posts_router.put("/{post_id}/media", response_model=ScheduledPostReadModel)
async def put_scheduled_post_with_media(
    server_id: int,
    post_id: UUID,
    channel_id: str = Form(..., pattern=r"^\d+$"),
    content: str = Form(default="", max_length=2000),
    mention_everyone: bool = Form(default=False),
    mention_user_ids: list[str] = Form(default=[]),
    mention_role_ids: list[str] = Form(default=[]),
    schedule_type: Literal["once", "interval"] = Form(...),
    timezone: str = Form(default="UTC"),
    next_run_at: datetime = Form(...),
    interval_seconds: int | None = Form(default=None),
    retained_attachment_ids: list[UUID] = Form(default=[]),
    files: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(
        require_server_permission("communications.scheduled_posts.manage")
    ),
):
    attachments = await _read_attachment_files(files)
    return await update_scheduled_post(
        session,
        server_id=server_id,
        post_id=post_id,
        actor_user_id=actor_user_id,
        body=_form_body(
            channel_id=channel_id,
            content=content,
            mention_everyone=mention_everyone,
            mention_user_ids=mention_user_ids,
            mention_role_ids=mention_role_ids,
            schedule_type=schedule_type,
            timezone=timezone,
            next_run_at=next_run_at,
            interval_seconds=interval_seconds,
        ),
        attachments=attachments,
        retained_attachment_ids=retained_attachment_ids,
    )


@scheduled_posts_router.patch("/{post_id}/status", response_model=ScheduledPostReadModel)
async def patch_scheduled_post_status(
    server_id: int,
    post_id: UUID,
    body: ScheduledPostStatusModel,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await set_scheduled_post_status(
        session,
        server_id=server_id,
        post_id=post_id,
        actor_user_id=actor_user_id,
        new_status=body.status,
    )


@scheduled_posts_router.post("/{post_id}/send-now", response_model=ScheduledPostRunReadModel)
async def post_scheduled_post_now(
    server_id: int,
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await send_scheduled_post_now(
        session,
        server_id=server_id,
        post_id=post_id,
        actor_user_id=actor_user_id,
    )


@scheduled_posts_router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_scheduled_post(
    server_id: int,
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    await delete_scheduled_post(session, server_id, post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

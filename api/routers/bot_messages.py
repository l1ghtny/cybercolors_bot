import mimetypes
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.models.bot_messages import BotMessageAuditReadModel, BotMessageCreateModel
from api.services.bot_messages import list_bot_message_audits, send_bot_message
from src.db.database import get_session


bot_messages_router = APIRouter(
    prefix="/servers/{server_id}/bot-messages",
    dependencies=[Depends(require_server_dashboard_access)],
)

_ALLOWED_MEDIA_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}
_MAX_MEDIA_FILES = 10
_MAX_MEDIA_FILE_BYTES = 10 * 1024 * 1024
_MAX_MEDIA_TOTAL_BYTES = 25 * 1024 * 1024


async def _read_media_files(files: list[UploadFile]) -> list[tuple[str, bytes, str]]:
    if len(files) > _MAX_MEDIA_FILES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Attach at most {_MAX_MEDIA_FILES} images or GIFs",
        )

    attachments: list[tuple[str, bytes, str]] = []
    total_bytes = 0
    for index, file in enumerate(files):
        filename = PurePath(file.filename or f"image-{index + 1}").name[:255]
        content_type = (file.content_type or "").lower()
        if content_type not in _ALLOWED_MEDIA_TYPES:
            guessed_type = mimetypes.guess_type(filename)[0]
            content_type = guessed_type.lower() if guessed_type else content_type
        if content_type not in _ALLOWED_MEDIA_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"{filename} is not a supported image or GIF",
            )

        data = await file.read(_MAX_MEDIA_FILE_BYTES + 1)
        await file.close()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{filename} is empty",
            )
        if len(data) > _MAX_MEDIA_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{filename} exceeds the 10 MB attachment limit",
            )
        total_bytes += len(data)
        if total_bytes > _MAX_MEDIA_TOTAL_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Attachments exceed the 25 MB total limit",
            )
        attachments.append((filename, data, content_type))
    return attachments


@bot_messages_router.get("", response_model=list[BotMessageAuditReadModel])
async def get_bot_message_audits(
    server_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("audit.timeline.view")),
):
    return await list_bot_message_audits(session, server_id=server_id, limit=limit)


@bot_messages_router.post(
    "",
    response_model=BotMessageAuditReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def create_bot_message(
    server_id: int,
    body: BotMessageCreateModel,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.send_as_bot")),
):
    return await send_bot_message(
        session,
        server_id=server_id,
        actor_user_id=actor_user_id,
        body=body,
        source="dashboard",
    )


@bot_messages_router.post(
    "/media",
    response_model=BotMessageAuditReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def create_bot_message_with_media(
    server_id: int,
    channel_id: str = Form(..., pattern=r"^\d+$"),
    content: str = Form(default="", max_length=2000),
    files: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.send_as_bot")),
):
    attachments = await _read_media_files(files)
    return await send_bot_message(
        session,
        server_id=server_id,
        actor_user_id=actor_user_id,
        body=BotMessageCreateModel(channel_id=channel_id, content=content),
        source="dashboard",
        attachments=attachments,
    )

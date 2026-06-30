from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.auth import get_bearer_access_token
from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.models.server_temp_voice import (
    ServerTempVoiceCreateTriggerChannelModel,
    TempVoiceArchiveDetailModel,
    TempVoiceArchiveSummaryModel,
    ServerTempVoiceSettingsReadModel,
    ServerTempVoiceSettingsUpdateModel,
)
from api.services.rbac_service import assert_user_has_permission
from api.services.server_temp_voice import (
    build_temp_voice_archive_transcript,
    create_temp_voice_trigger_channel_and_attach,
    get_temp_voice_archive_detail,
    get_or_create_server_temp_voice_settings,
    list_temp_voice_archives,
    to_server_temp_voice_read_model,
    update_server_temp_voice_settings,
)
from src.db.database import get_session

server_temp_voice_router = APIRouter(
    prefix="/servers/{server_id}/temp-voice",
    dependencies=[Depends(require_server_dashboard_access)],
)


async def _attach_edit_permission(
    *,
    payload: ServerTempVoiceSettingsReadModel,
    session: AsyncSession,
    server_id: int,
    user_id: int,
    access_token: str,
) -> ServerTempVoiceSettingsReadModel:
    try:
        await assert_user_has_permission(
            session=session,
            server_id=server_id,
            user_id=user_id,
            permission_key="temp_voice.settings.edit",
            access_token=access_token,
        )
        payload.permissions.can_edit = True
    except HTTPException as error:
        if error.status_code != 403:
            raise
        payload.permissions.can_edit = False
    return payload


@server_temp_voice_router.get("", response_model=ServerTempVoiceSettingsReadModel)
async def get_server_temp_voice_settings(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("temp_voice.settings.view")),
    access_token: str = Depends(get_bearer_access_token),
):
    settings = await get_or_create_server_temp_voice_settings(session, server_id)
    payload = await to_server_temp_voice_read_model(server_id, settings)
    return await _attach_edit_permission(
        payload=payload,
        session=session,
        server_id=server_id,
        user_id=current_user_id,
        access_token=access_token,
    )


@server_temp_voice_router.put("", response_model=ServerTempVoiceSettingsReadModel)
async def set_server_temp_voice_settings(
    server_id: int,
    body: ServerTempVoiceSettingsUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("temp_voice.settings.edit")),
):
    settings = await update_server_temp_voice_settings(session=session, server_id=server_id, body=body)
    payload = await to_server_temp_voice_read_model(server_id, settings)
    payload.permissions.can_edit = True
    return payload


@server_temp_voice_router.get("/archives", response_model=list[TempVoiceArchiveSummaryModel])
async def list_server_temp_voice_archives(
    server_id: int,
    include_active: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("temp_voice.settings.view")),
):
    return await list_temp_voice_archives(
        session=session,
        server_id=server_id,
        include_active=include_active,
        limit=limit,
        offset=offset,
    )


@server_temp_voice_router.get("/archives/{log_id}/transcript.txt")
async def get_server_temp_voice_archive_transcript(
    server_id: int,
    log_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("temp_voice.settings.view")),
):
    transcript = await build_temp_voice_archive_transcript(session=session, server_id=server_id, log_id=log_id)
    return Response(content=transcript, media_type="text/plain; charset=utf-8")


@server_temp_voice_router.get("/archives/{log_id}", response_model=TempVoiceArchiveDetailModel)
async def get_server_temp_voice_archive(
    server_id: int,
    log_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("temp_voice.settings.view")),
):
    return await get_temp_voice_archive_detail(session=session, server_id=server_id, log_id=log_id)


@server_temp_voice_router.post("/trigger-channel/create", response_model=ServerTempVoiceSettingsReadModel)
async def create_server_temp_voice_trigger_channel(
    server_id: int,
    body: ServerTempVoiceCreateTriggerChannelModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("temp_voice.settings.edit")),
):
    settings = await create_temp_voice_trigger_channel_and_attach(session=session, server_id=server_id, body=body)
    payload = await to_server_temp_voice_read_model(server_id, settings)
    payload.permissions.can_edit = True
    return payload

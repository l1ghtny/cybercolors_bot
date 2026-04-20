from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_current_discord_user_id
from api.models.dashboard_access import (
    DashboardAccessAddRoleModel,
    DashboardAccessAddUserModel,
    DashboardAccessReadModel,
)
from api.services.dashboard_access_service import (
    add_dashboard_access_role,
    add_dashboard_access_user,
    assert_server_owner,
    get_dashboard_access,
    remove_dashboard_access_role,
    remove_dashboard_access_user,
)
from api.models.server_directory import (
    ServerChannelModel,
    ServerMetadataModel,
    ServerRoleModel,
    ServerUserModel,
    ServerUsersLookupRequest,
)
from api.services.server_directory import (
    build_server_metadata,
    get_server_channel_payload,
    list_server_channels,
    list_server_roles,
    lookup_server_users_by_ids,
    query_server_users,
)
from src.db.database import get_session
from src.db.models import Server

servers = APIRouter(prefix="/servers", tags=["servers"])


@servers.get("/")
async def get_servers():
    return "get_servers"


@servers.get("/{server_id}", response_model=ServerMetadataModel)
async def get_server(server_id: int, session: AsyncSession = Depends(get_session)):
    server = await session.get(Server, server_id)
    metadata = await build_server_metadata(session, server_id)
    if not server and not metadata.name and not metadata.owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return metadata


@servers.get("/{server_id}/channels", response_model=list[ServerChannelModel])
async def get_server_channels(
    server_id: int,
    text_only: bool = Query(default=True),
):
    return await list_server_channels(server_id, text_only=text_only)


@servers.get("/{server_id}/channels/{channel_id}", response_model=ServerChannelModel)
async def get_server_channel(server_id: int, channel_id: int):
    channel = await get_server_channel_payload(server_id, channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return channel


@servers.get("/{server_id}/roles", response_model=list[ServerRoleModel])
async def get_server_roles(server_id: int):
    return await list_server_roles(server_id)


@servers.get("/{server_id}/users", response_model=list[ServerUserModel])
async def get_server_users(
    server_id: int,
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await query_server_users(session=session, server_id=server_id, search=search, limit=limit)


@servers.post("/{server_id}/users/lookup", response_model=list[ServerUserModel])
async def lookup_server_users(
    server_id: int,
    body: ServerUsersLookupRequest,
    session: AsyncSession = Depends(get_session),
):
    user_ids: list[int] = []
    for raw_id in body.user_ids:
        if raw_id.isdigit():
            user_ids.append(int(raw_id))
    return await lookup_server_users_by_ids(session=session, server_id=server_id, user_ids=user_ids)


@servers.get("/{server_id}/dashboard-access", response_model=DashboardAccessReadModel)
async def get_server_dashboard_access(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
):
    await assert_server_owner(server_id, current_user_id)
    return await get_dashboard_access(session=session, server_id=server_id)


@servers.post("/{server_id}/dashboard-access/users", response_model=DashboardAccessReadModel)
async def add_server_dashboard_access_user(
    server_id: int,
    body: DashboardAccessAddUserModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
):
    await assert_server_owner(server_id, current_user_id)
    return await add_dashboard_access_user(
        session=session,
        server_id=server_id,
        user_id=int(body.user_id),
        added_by_user_id=current_user_id,
    )


@servers.delete("/{server_id}/dashboard-access/users/{user_id}", response_model=DashboardAccessReadModel)
async def remove_server_dashboard_access_user(
    server_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
):
    await assert_server_owner(server_id, current_user_id)
    return await remove_dashboard_access_user(session=session, server_id=server_id, user_id=user_id)


@servers.post("/{server_id}/dashboard-access/roles", response_model=DashboardAccessReadModel)
async def add_server_dashboard_access_role(
    server_id: int,
    body: DashboardAccessAddRoleModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
):
    await assert_server_owner(server_id, current_user_id)
    return await add_dashboard_access_role(
        session=session,
        server_id=server_id,
        role_id=int(body.role_id),
        added_by_user_id=current_user_id,
    )


@servers.delete("/{server_id}/dashboard-access/roles/{role_id}", response_model=DashboardAccessReadModel)
async def remove_server_dashboard_access_role(
    server_id: int,
    role_id: int,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
):
    await assert_server_owner(server_id, current_user_id)
    return await remove_dashboard_access_role(session=session, server_id=server_id, role_id=role_id)

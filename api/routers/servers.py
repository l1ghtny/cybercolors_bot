from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_directory import (
    ServerChannelModel,
    ServerRoleModel,
    ServerUserModel,
    ServerUsersLookupRequest,
)
from api.services.discord_guilds import TEXT_CHANNEL_TYPES, fetch_channel, fetch_guild_channels, fetch_guild_roles
from api.services.server_directory import lookup_server_users_by_ids, query_server_users
from src.db.database import get_session
from src.db.models import Server

servers = APIRouter(prefix="/servers", tags=["servers"])


@servers.get("/")
async def get_servers():
    return "get_servers"


@servers.get("/{server_id}")
async def get_server(server_id: int, session: AsyncSession = Depends(get_session)):
    server = await session.get(Server, server_id)
    if not server:
        return None

    server_data = server.model_dump()
    server_data["server_id"] = str(server.server_id)
    if server.birthday_channel_id:
        server_data["birthday_channel_id"] = str(server.birthday_channel_id)
    if server.birthday_role_id:
        server_data["birthday_role_id"] = str(server.birthday_role_id)
    return server_data


@servers.get("/{server_id}/channels", response_model=list[ServerChannelModel])
async def get_server_channels(
    server_id: int,
    text_only: bool = Query(default=True),
):
    raw_channels = await fetch_guild_channels(server_id)

    categories = {item["id"]: item["name"] for item in raw_channels if int(item.get("type", -1)) == 4}
    payload: list[ServerChannelModel] = []

    for channel in raw_channels:
        channel_type = int(channel.get("type", -1))
        if text_only and channel_type not in TEXT_CHANNEL_TYPES:
            continue

        parent_id = channel.get("parent_id")
        payload.append(
            ServerChannelModel(
                id=str(channel["id"]),
                name=channel.get("name", ""),
                type=channel_type,
                position=int(channel.get("position", 0)),
                parent_id=str(parent_id) if parent_id else None,
                parent_name=categories.get(parent_id) if parent_id else None,
            )
        )

    payload.sort(key=lambda c: ((c.parent_name or "").lower(), c.position, c.name.lower()))
    return payload


@servers.get("/{server_id}/channels/{channel_id}", response_model=ServerChannelModel)
async def get_server_channel(server_id: int, channel_id: int):
    channel = await fetch_channel(server_id, channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    channels = await fetch_guild_channels(server_id)
    categories = {item["id"]: item["name"] for item in channels if int(item.get("type", -1)) == 4}
    parent_id = channel.get("parent_id")
    return ServerChannelModel(
        id=str(channel["id"]),
        name=channel.get("name", ""),
        type=int(channel.get("type", -1)),
        position=int(channel.get("position", 0)),
        parent_id=str(parent_id) if parent_id else None,
        parent_name=categories.get(parent_id) if parent_id else None,
    )


@servers.get("/{server_id}/roles", response_model=list[ServerRoleModel])
async def get_server_roles(server_id: int):
    roles = await fetch_guild_roles(server_id)
    payload = [
        ServerRoleModel(
            id=str(role["id"]),
            name=role.get("name", ""),
            color=int(role.get("color", 0)),
            position=int(role.get("position", 0)),
            managed=bool(role.get("managed", False)),
        )
        for role in roles
    ]
    payload.sort(key=lambda r: r.position, reverse=True)
    return payload


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

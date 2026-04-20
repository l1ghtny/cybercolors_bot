from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_directory import (
    ServerChannelModel,
    ServerMetadataModel,
    ServerRoleModel,
    ServerUserModel,
    ServerUsersLookupRequest,
)
from api.services.discord_guilds import (
    TEXT_CHANNEL_TYPES,
    fetch_channel,
    fetch_guild_channels,
    fetch_guild_metadata,
    fetch_guild_roles,
)
from api.services.server_directory import lookup_server_users_by_ids, query_server_users
from src.db.database import get_session
from src.db.models import Server, User

servers = APIRouter(prefix="/servers", tags=["servers"])


@servers.get("/")
async def get_servers():
    return "get_servers"


@servers.get("/{server_id}", response_model=ServerMetadataModel)
async def get_server(server_id: int, session: AsyncSession = Depends(get_session)):
    server = await session.get(Server, server_id)
    metadata: dict = {}
    try:
        metadata = await fetch_guild_metadata(server_id)
    except Exception:
        metadata = {}

    if not server and not metadata:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    birthday_role_id = server.birthday_role_id if server else None
    birthday_role_name: str | None = None
    if birthday_role_id:
        try:
            roles = await fetch_guild_roles(server_id)
            for role in roles:
                raw_id = role.get("id")
                if raw_id is not None and int(raw_id) == birthday_role_id:
                    birthday_role_name = role.get("name")
                    break
        except Exception:
            birthday_role_name = None

    db_member_count = (
        await session.exec(
            select(func.count())
            .select_from(User)
            .where(User.server_id == server_id, User.is_member.is_(True))
        )
    ).one()
    db_member_count_int = int(db_member_count or 0)
    member_count = db_member_count_int if db_member_count_int > 0 else metadata.get("approximate_member_count")

    return ServerMetadataModel(
        server_id=str(server_id),
        name=(server.server_name if server and server.server_name else metadata.get("name")),
        icon=(server.icon if server and server.icon else metadata.get("icon")),
        member_count=member_count,
        owner_id=str(metadata["owner_id"]) if metadata.get("owner_id") else None,
        features=[str(item) for item in metadata.get("features", [])],
        birthday_channel_id=str(server.birthday_channel_id) if server and server.birthday_channel_id else None,
        birthday_channel_name=server.birthday_channel_name if server else None,
        birthday_role_id=str(birthday_role_id) if birthday_role_id else None,
        birthday_role_name=birthday_role_name,
    )


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

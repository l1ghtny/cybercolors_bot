import asyncio
import os
import time
from dataclasses import dataclass

from sqlalchemy import String, cast, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_directory import (
    ServerChannelModel,
    ServerMemberPageModel,
    ServerMetadataModel,
    ServerRoleModel,
    ServerUserModel,
)
from api.services.discord_guilds import (
    TEXT_CHANNEL_TYPES,
    fetch_channel,
    fetch_guild_channels,
    fetch_guild_metadata,
    fetch_guild_roles,
    fetch_all_guild_members,
)
from src.db.models import GlobalUser, Server, User


def _display_name(user: User, global_user: GlobalUser) -> str:
    if user.server_nickname:
        return user.server_nickname
    if global_user.username:
        return global_user.username
    return str(user.user_id)

def _to_server_user(user: User, global_user: GlobalUser) -> ServerUserModel:
    return ServerUserModel(
        user_id=str(user.user_id),
        display_name=_display_name(user, global_user),
        username=global_user.username,
        server_nickname=user.server_nickname,
        avatar_hash=global_user.avatar_hash,
        is_member=user.is_member,
    )


@dataclass
class _GuildMembersCacheEntry:
    expires_at: float
    members: list[dict]


_MEMBER_DIRECTORY_CACHE_SECONDS = max(
    15.0,
    float(os.getenv("SERVER_MEMBER_DIRECTORY_CACHE_SECONDS", "60")),
)
_member_directory_cache: dict[int, _GuildMembersCacheEntry] = {}
_member_directory_locks: dict[int, asyncio.Lock] = {}


async def _cached_guild_members(server_id: int) -> list[dict]:
    now = time.monotonic()
    cached = _member_directory_cache.get(server_id)
    if cached and cached.expires_at > now:
        return cached.members

    lock = _member_directory_locks.setdefault(server_id, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _member_directory_cache.get(server_id)
        if cached and cached.expires_at > now:
            return cached.members

        members = await fetch_all_guild_members(server_id)
        _member_directory_cache[server_id] = _GuildMembersCacheEntry(
            expires_at=now + _MEMBER_DIRECTORY_CACHE_SECONDS,
            members=members,
        )
        return members


def _to_discord_server_user(member: dict) -> ServerUserModel | None:
    raw_user = member.get("user")
    if not isinstance(raw_user, dict) or raw_user.get("id") is None:
        return None

    user_id = str(raw_user["id"])
    username = raw_user.get("username")
    server_nickname = member.get("nick")
    global_name = raw_user.get("global_name")
    display_name = server_nickname or global_name or username or user_id

    return ServerUserModel(
        user_id=user_id,
        display_name=str(display_name),
        username=str(username) if username is not None else None,
        server_nickname=str(server_nickname) if server_nickname is not None else None,
        avatar_hash=str(raw_user["avatar"]) if raw_user.get("avatar") else None,
        is_member=True,
        role_ids=[str(role_id) for role_id in member.get("roles", [])],
        joined_at=str(member["joined_at"]) if member.get("joined_at") else None,
        is_bot=bool(raw_user.get("bot", False)),
    )


async def query_server_members(
    server_id: int,
    *,
    search: str | None = None,
    role_ids: list[int] | None = None,
    sort: str = "name_asc",
    offset: int = 0,
    limit: int = 50,
) -> ServerMemberPageModel:
    raw_members = await _cached_guild_members(server_id)
    members = [
        payload
        for member in raw_members
        if (payload := _to_discord_server_user(member)) is not None
    ]

    normalized_search = (search or "").strip().casefold()
    selected_role_ids = {str(role_id) for role_id in (role_ids or [])}
    if normalized_search:
        members = [
            member
            for member in members
            if normalized_search in member.user_id.casefold()
            or normalized_search in (member.username or "").casefold()
            or normalized_search in (member.server_nickname or "").casefold()
            or normalized_search in member.display_name.casefold()
        ]
    if selected_role_ids:
        members = [
            member
            for member in members
            if selected_role_ids.intersection(member.role_ids)
        ]

    if sort == "name_desc":
        members.sort(
            key=lambda member: (member.display_name.casefold(), member.user_id),
            reverse=True,
        )
    elif sort == "joined_newest":
        members.sort(key=lambda member: (member.display_name.casefold(), member.user_id))
        members.sort(key=lambda member: member.joined_at or "", reverse=True)
    elif sort == "joined_oldest":
        members.sort(
            key=lambda member: (
                member.joined_at is None,
                member.joined_at or "",
                member.display_name.casefold(),
                member.user_id,
            )
        )
    else:
        members.sort(key=lambda member: (member.display_name.casefold(), member.user_id))
    total = len(members)
    return ServerMemberPageModel(
        items=members[offset : offset + limit],
        total=total,
        offset=offset,
        limit=limit,
    )


async def query_server_users(
    session: AsyncSession,
    server_id: int,
    search: str | None = None,
    limit: int = 50,
) -> list[ServerUserModel]:
    statement = (
        select(User, GlobalUser)
        .join(GlobalUser, GlobalUser.discord_id == User.user_id)
        .where(User.server_id == server_id)
    )

    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                cast(User.user_id, String).ilike(pattern),
                User.server_nickname.ilike(pattern),
                GlobalUser.username.ilike(pattern),
            )
        )

    statement = statement.order_by(User.server_nickname, GlobalUser.username).limit(limit)
    rows = (await session.exec(statement)).all()
    return [_to_server_user(user, global_user) for user, global_user in rows]


async def lookup_server_users_by_ids(
    session: AsyncSession,
    server_id: int,
    user_ids: list[int],
) -> list[ServerUserModel]:
    if not user_ids:
        return []

    statement = (
        select(User, GlobalUser)
        .join(GlobalUser, GlobalUser.discord_id == User.user_id)
        .where(User.server_id == server_id, User.user_id.in_(user_ids))
    )
    rows = (await session.exec(statement)).all()
    return [_to_server_user(user, global_user) for user, global_user in rows]


async def build_server_metadata(session: AsyncSession, server_id: int) -> ServerMetadataModel:
    server = await session.get(Server, server_id)
    metadata: dict = {}
    try:
        metadata = await fetch_guild_metadata(server_id)
    except Exception:
        metadata = {}

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


async def list_server_channels(server_id: int, text_only: bool = True) -> list[ServerChannelModel]:
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
                rate_limit_per_user=int(channel.get("rate_limit_per_user") or 0),
            )
        )

    payload.sort(key=lambda c: ((c.parent_name or "").lower(), c.position, c.name.lower()))
    return payload


async def get_server_channel_payload(server_id: int, channel_id: int) -> ServerChannelModel | None:
    channel = await fetch_channel(server_id, channel_id)
    if not channel:
        return None

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
        rate_limit_per_user=int(channel.get("rate_limit_per_user") or 0),
    )


async def list_server_roles(server_id: int) -> list[ServerRoleModel]:
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

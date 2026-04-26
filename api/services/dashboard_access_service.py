import asyncio
from collections import defaultdict
from dataclasses import dataclass
import logging
import os
from time import monotonic

import httpx
from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import DISCORD_API_BASE_URL
from api.models.dashboard_access import (
    DashboardAccessReadModel,
    DashboardAccessRoleReadModel,
    DashboardAccessUserReadModel,
)
from api.services.discord_guilds import fetch_guild_member, fetch_guild_metadata, fetch_guild_roles
from api.services.moderation_core import build_optional_actor
from src.db.models import DashboardAccessRole, DashboardAccessUser, GlobalUser, Server

logger = logging.getLogger("api.dashboard_access")
DASHBOARD_ACCESS_USER_GUILDS_CACHE_TTL_SECONDS = int(os.getenv("DASHBOARD_ACCESS_USER_GUILDS_CACHE_TTL_SECONDS", "90"))
DASHBOARD_ACCESS_MEMBER_ROLES_CACHE_TTL_SECONDS = int(os.getenv("DASHBOARD_ACCESS_MEMBER_ROLES_CACHE_TTL_SECONDS", "60"))


@dataclass
class _UserGuildsCacheEntry:
    payload_by_server_id: dict[int, dict]
    expires_at: float


@dataclass
class _MemberRolesCacheEntry:
    role_ids: set[int]
    expires_at: float


_user_guild_payload_cache: dict[str, _UserGuildsCacheEntry] = {}
_member_roles_cache: dict[tuple[int, int], _MemberRolesCacheEntry] = {}
_user_guild_payload_locks: dict[str, asyncio.Lock] = {}
_member_roles_locks: dict[tuple[int, int], asyncio.Lock] = {}
_dashboard_access_locks_guard = asyncio.Lock()


async def _get_user_guild_payload_lock(access_token: str) -> asyncio.Lock:
    async with _dashboard_access_locks_guard:
        lock = _user_guild_payload_locks.get(access_token)
        if lock is None:
            lock = asyncio.Lock()
            _user_guild_payload_locks[access_token] = lock
        return lock


async def _get_member_roles_lock(server_id: int, user_id: int) -> asyncio.Lock:
    key = (server_id, user_id)
    async with _dashboard_access_locks_guard:
        lock = _member_roles_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _member_roles_locks[key] = lock
        return lock


async def assert_server_owner(server_id: int, caller_user_id: int) -> None:
    metadata = await fetch_guild_metadata(server_id)
    owner_id = metadata.get("owner_id")
    if owner_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if int(owner_id) != caller_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only server owner can modify dashboard access")


async def get_or_create_server(session: AsyncSession, server_id: int) -> Server:
    server = await session.get(Server, server_id)
    if server:
        return server
    server = Server(server_id=server_id, server_name=str(server_id))
    session.add(server)
    await session.flush()
    return server


async def _ensure_global_user(session: AsyncSession, user_id: int) -> None:
    existing = await session.get(GlobalUser, user_id)
    if existing:
        return
    session.add(GlobalUser(discord_id=user_id, username=None))
    await session.flush()


async def load_dashboard_access_maps(
    session: AsyncSession,
    server_ids: list[int],
) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    if not server_ids:
        return {}, {}

    users_map: dict[int, set[int]] = defaultdict(set)
    roles_map: dict[int, set[int]] = defaultdict(set)

    users = (
        await session.exec(
            select(DashboardAccessUser).where(DashboardAccessUser.server_id.in_(server_ids))
        )
    ).all()
    for item in users:
        users_map[item.server_id].add(item.user_id)

    roles = (
        await session.exec(
            select(DashboardAccessRole).where(DashboardAccessRole.server_id.in_(server_ids))
        )
    ).all()
    for item in roles:
        roles_map[item.server_id].add(item.role_id)

    return users_map, roles_map


async def get_dashboard_access(session: AsyncSession, server_id: int) -> DashboardAccessReadModel:
    users = (
        await session.exec(
            select(DashboardAccessUser)
            .where(DashboardAccessUser.server_id == server_id)
            .order_by(DashboardAccessUser.created_at.desc())
        )
    ).all()
    roles = (
        await session.exec(
            select(DashboardAccessRole)
            .where(DashboardAccessRole.server_id == server_id)
            .order_by(DashboardAccessRole.created_at.desc())
        )
    ).all()

    role_name_map: dict[int, str] = {}
    try:
        guild_roles = await fetch_guild_roles(server_id)
        role_name_map = {int(role["id"]): role.get("name", "") for role in guild_roles}
    except Exception:
        role_name_map = {}

    users_payload: list[DashboardAccessUserReadModel] = []
    for item in users:
        users_payload.append(
            DashboardAccessUserReadModel(
                user=(await build_optional_actor(session, server_id, item.user_id)),
                created_at=item.created_at,
                added_by=(await build_optional_actor(session, server_id, item.added_by_user_id)),
            )
        )

    roles_payload: list[DashboardAccessRoleReadModel] = []
    for item in roles:
        roles_payload.append(
            DashboardAccessRoleReadModel(
                role_id=str(item.role_id),
                role_name=role_name_map.get(item.role_id),
                created_at=item.created_at,
                added_by=(await build_optional_actor(session, server_id, item.added_by_user_id)),
            )
        )

    return DashboardAccessReadModel(server_id=str(server_id), users=users_payload, roles=roles_payload)


async def add_dashboard_access_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    added_by_user_id: int,
) -> DashboardAccessReadModel:
    await get_or_create_server(session, server_id)
    await _ensure_global_user(session, user_id)
    await _ensure_global_user(session, added_by_user_id)

    existing = (
        await session.exec(
            select(DashboardAccessUser).where(
                DashboardAccessUser.server_id == server_id,
                DashboardAccessUser.user_id == user_id,
            )
        )
    ).first()
    if not existing:
        session.add(
            DashboardAccessUser(
                server_id=server_id,
                user_id=user_id,
                added_by_user_id=added_by_user_id,
            )
        )
        await session.flush()

    return await get_dashboard_access(session, server_id)


async def remove_dashboard_access_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
) -> DashboardAccessReadModel:
    existing = (
        await session.exec(
            select(DashboardAccessUser).where(
                DashboardAccessUser.server_id == server_id,
                DashboardAccessUser.user_id == user_id,
            )
        )
    ).first()
    if existing:
        await session.delete(existing)
        await session.flush()
    return await get_dashboard_access(session, server_id)


async def add_dashboard_access_role(
    session: AsyncSession,
    server_id: int,
    role_id: int,
    added_by_user_id: int,
) -> DashboardAccessReadModel:
    await get_or_create_server(session, server_id)
    await _ensure_global_user(session, added_by_user_id)

    existing = (
        await session.exec(
            select(DashboardAccessRole).where(
                DashboardAccessRole.server_id == server_id,
                DashboardAccessRole.role_id == role_id,
            )
        )
    ).first()
    if not existing:
        session.add(
            DashboardAccessRole(
                server_id=server_id,
                role_id=role_id,
                added_by_user_id=added_by_user_id,
            )
        )
        await session.flush()

    return await get_dashboard_access(session, server_id)


async def remove_dashboard_access_role(
    session: AsyncSession,
    server_id: int,
    role_id: int,
) -> DashboardAccessReadModel:
    existing = (
        await session.exec(
            select(DashboardAccessRole).where(
                DashboardAccessRole.server_id == server_id,
                DashboardAccessRole.role_id == role_id,
            )
        )
    ).first()
    if existing:
        await session.delete(existing)
        await session.flush()
    return await get_dashboard_access(session, server_id)


def _parse_guild_id(payload: dict) -> int | None:
    raw_id = payload.get("id")
    if raw_id is None or not str(raw_id).isdigit():
        return None
    return int(raw_id)


def _get_cached_user_guild_payload(access_token: str, server_id: int) -> dict | None:
    if DASHBOARD_ACCESS_USER_GUILDS_CACHE_TTL_SECONDS <= 0:
        return None
    cached = _user_guild_payload_cache.get(access_token)
    if not cached:
        return None
    if cached.expires_at <= monotonic():
        _user_guild_payload_cache.pop(access_token, None)
        return None
    payload = cached.payload_by_server_id.get(server_id)
    if payload is None:
        return None
    return dict(payload)


def _store_cached_user_guild_payloads(access_token: str, guilds: list[dict]) -> None:
    if DASHBOARD_ACCESS_USER_GUILDS_CACHE_TTL_SECONDS <= 0:
        return
    payload_by_server_id: dict[int, dict] = {}
    for payload in guilds:
        guild_id = _parse_guild_id(payload)
        if guild_id is None:
            continue
        payload_by_server_id[guild_id] = dict(payload)
    _user_guild_payload_cache[access_token] = _UserGuildsCacheEntry(
        payload_by_server_id=payload_by_server_id,
        expires_at=monotonic() + DASHBOARD_ACCESS_USER_GUILDS_CACHE_TTL_SECONDS,
    )


def _get_cached_member_role_ids(server_id: int, user_id: int) -> set[int] | None:
    if DASHBOARD_ACCESS_MEMBER_ROLES_CACHE_TTL_SECONDS <= 0:
        return None
    cached = _member_roles_cache.get((server_id, user_id))
    if not cached:
        return None
    if cached.expires_at <= monotonic():
        _member_roles_cache.pop((server_id, user_id), None)
        return None
    return set(cached.role_ids)


def _store_cached_member_role_ids(server_id: int, user_id: int, role_ids: set[int]) -> None:
    if DASHBOARD_ACCESS_MEMBER_ROLES_CACHE_TTL_SECONDS <= 0:
        return
    _member_roles_cache[(server_id, user_id)] = _MemberRolesCacheEntry(
        role_ids=set(role_ids),
        expires_at=monotonic() + DASHBOARD_ACCESS_MEMBER_ROLES_CACHE_TTL_SECONDS,
    )


async def _get_user_guild_payload(access_token: str, server_id: int) -> dict:
    cached_payload = _get_cached_user_guild_payload(access_token, server_id)
    if cached_payload is not None:
        return cached_payload

    payload_lock = await _get_user_guild_payload_lock(access_token)
    async with payload_lock:
        cached_payload = _get_cached_user_guild_payload(access_token, server_id)
        if cached_payload is not None:
            return cached_payload

        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            guilds_response = await client.get(f"{DISCORD_API_BASE_URL}/users/@me/guilds", headers=headers)
        if guilds_response.status_code == status.HTTP_401_UNAUTHORIZED:
            _user_guild_payload_cache.pop(access_token, None)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token")
        if guilds_response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Discord API rate limited while validating dashboard access",
            )
        if guilds_response.status_code >= 500:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Discord API unavailable while validating dashboard access",
            )
        if guilds_response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Discord API error while validating dashboard access: {guilds_response.status_code}",
            )

        guilds = guilds_response.json()
        if isinstance(guilds, list):
            _store_cached_user_guild_payloads(access_token, guilds)
        else:
            logger.warning("Unexpected /users/@me/guilds payload type: %s", type(guilds))
            guilds = []

    for item in guilds:
        guild_id = _parse_guild_id(item)
        if guild_id is not None and guild_id == server_id:
            return item
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No dashboard access to this server")


def _guild_admin_or_owner(guild_payload: dict) -> bool:
    is_owner = bool(guild_payload.get("owner"))
    permissions = int(guild_payload.get("permissions", 0))
    administrator_flag = 1 << 3
    is_admin = bool(permissions & administrator_flag)
    return is_owner or is_admin


async def assert_server_admin_or_owner(
    server_id: int,
    access_token: str,
) -> None:
    guild_payload = await _get_user_guild_payload(access_token=access_token, server_id=server_id)
    if not _guild_admin_or_owner(guild_payload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only server owners or administrators can update this setting",
        )


async def assert_dashboard_access(
    session: AsyncSession,
    server_id: int,
    caller_user_id: int,
    access_token: str,
) -> None:
    guild_payload = await _get_user_guild_payload(access_token=access_token, server_id=server_id)
    if _guild_admin_or_owner(guild_payload):
        return

    user_allowlisted = (
        await session.exec(
            select(DashboardAccessUser).where(
                DashboardAccessUser.server_id == server_id,
                DashboardAccessUser.user_id == caller_user_id,
            )
        )
    ).first()
    if user_allowlisted:
        return

    allowed_roles = (
        await session.exec(
            select(DashboardAccessRole.role_id).where(DashboardAccessRole.server_id == server_id)
        )
    ).all()
    allowed_role_ids = {int(role_id) for role_id in allowed_roles}
    if not allowed_role_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No dashboard access to this server")

    user_role_ids = _get_cached_member_role_ids(server_id=server_id, user_id=caller_user_id)
    if user_role_ids is None:
        member_roles_lock = await _get_member_roles_lock(server_id=server_id, user_id=caller_user_id)
        async with member_roles_lock:
            user_role_ids = _get_cached_member_role_ids(server_id=server_id, user_id=caller_user_id)
            if user_role_ids is None:
                member_payload = await fetch_guild_member(server_id=server_id, user_id=caller_user_id)
                if not member_payload:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No dashboard access to this server")
                user_role_ids = {
                    int(role_id) for role_id in member_payload.get("roles", []) if str(role_id).isdigit()
                }
                _store_cached_member_role_ids(server_id=server_id, user_id=caller_user_id, role_ids=user_role_ids)

    if not user_role_ids.intersection(allowed_role_ids):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No dashboard access to this server")

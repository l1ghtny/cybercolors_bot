from collections import defaultdict

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.dashboard_access import (
    DashboardAccessReadModel,
    DashboardAccessRoleReadModel,
    DashboardAccessUserReadModel,
)
from api.services.discord_guilds import fetch_guild_metadata, fetch_guild_roles
from api.services.moderation_core import build_optional_actor
from src.db.models import DashboardAccessRole, DashboardAccessUser, GlobalUser, Server


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

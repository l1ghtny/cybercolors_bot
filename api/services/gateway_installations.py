from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import Server, ServerGatewayInstallation


@dataclass(frozen=True)
class ServerGatewayMetadata:
    primary_profile: str
    installed_profiles: tuple[str, ...]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def active_installation_server_ids(
    session: AsyncSession,
    *,
    profile_key: str,
    server_ids: set[int] | None = None,
) -> set[int]:
    statement = select(ServerGatewayInstallation.server_id).where(
        ServerGatewayInstallation.profile_key == profile_key,
        ServerGatewayInstallation.active == True,  # noqa: E712
    )
    if server_ids is not None:
        if not server_ids:
            return set()
        statement = statement.where(
            ServerGatewayInstallation.server_id.in_(list(server_ids))
        )
    rows = (await session.exec(statement)).all()
    return {int(server_id) for server_id in rows}


async def has_active_installations(
    session: AsyncSession,
    *,
    profile_key: str,
) -> bool:
    row = (
        await session.exec(
            select(ServerGatewayInstallation.server_id)
            .where(
                ServerGatewayInstallation.profile_key == profile_key,
                ServerGatewayInstallation.active == True,  # noqa: E712
            )
            .limit(1)
        )
    ).first()
    return row is not None


async def gateway_metadata_for_servers(
    session: AsyncSession,
    server_ids: Iterable[int],
) -> dict[int, ServerGatewayMetadata]:
    normalized_ids = {int(server_id) for server_id in server_ids}
    if not normalized_ids:
        return {}

    servers = (
        await session.exec(
            select(Server).where(Server.server_id.in_(list(normalized_ids)))
        )
    ).all()
    installations = (
        await session.exec(
            select(ServerGatewayInstallation).where(
                ServerGatewayInstallation.server_id.in_(list(normalized_ids)),
                ServerGatewayInstallation.active == True,  # noqa: E712
            )
        )
    ).all()
    profiles_by_server: dict[int, list[str]] = {}
    for installation in installations:
        profiles_by_server.setdefault(int(installation.server_id), []).append(
            installation.profile_key
        )

    return {
        int(server.server_id): ServerGatewayMetadata(
            primary_profile=server.bot_profile,
            installed_profiles=tuple(sorted(profiles_by_server.get(int(server.server_id), []))),
        )
        for server in servers
    }


async def record_gateway_presence(
    session: AsyncSession,
    *,
    server_id: int,
    server_name: str | None,
    icon: str | None,
    profile_key: str,
    active: bool,
    observed_at: datetime | None = None,
) -> str:
    now = observed_at or utc_now()
    server = await session.get(Server, int(server_id))
    if server is None:
        server = Server(
            server_id=int(server_id),
            server_name=server_name,
            icon=icon,
            bot_profile=profile_key,
            bot_active=active,
            bot_joined_at=now if active else None,
            bot_left_at=None if active else now,
            bot_presence_updated_at=now,
        )
        session.add(server)
        await session.flush()
    else:
        if server_name:
            server.server_name = server_name
        server.icon = icon

    installation = await session.get(
        ServerGatewayInstallation,
        (int(server_id), profile_key),
    )
    if installation is None:
        installation = ServerGatewayInstallation(
            server_id=int(server_id),
            profile_key=profile_key,
            active=active,
            joined_at=now if active else None,
            left_at=None if active else now,
            presence_updated_at=now,
        )
    else:
        installation.active = active
        installation.presence_updated_at = now
        if active:
            installation.left_at = None
            if installation.joined_at is None:
                installation.joined_at = now
        else:
            installation.left_at = now

    if server.bot_profile == profile_key:
        server.bot_active = active
        server.bot_presence_updated_at = now
        if active:
            server.bot_left_at = None
            if server.bot_joined_at is None:
                server.bot_joined_at = now
        else:
            server.bot_left_at = now

    session.add(server)
    session.add(installation)
    await session.flush()
    return server.bot_profile


async def assign_primary_gateway(
    session: AsyncSession,
    *,
    server_id: int,
    profile_key: str,
) -> Server:
    """Atomically select an active installation as the side-effect owner."""
    server = await session.get(Server, int(server_id))
    if server is None:
        raise ValueError(f"Unknown server: {server_id}")
    installation = await session.get(
        ServerGatewayInstallation,
        (int(server_id), profile_key),
    )
    if installation is None or not installation.active:
        raise ValueError(
            f"Gateway profile {profile_key!r} is not active on server {server_id}"
        )

    server.bot_profile = profile_key
    server.bot_active = True
    server.bot_joined_at = installation.joined_at
    server.bot_left_at = None
    server.bot_presence_updated_at = installation.presence_updated_at
    session.add(server)
    await session.flush()
    return server


async def sync_gateway_presence_snapshot(
    session: AsyncSession,
    *,
    guilds: Iterable[tuple[int, str | None, str | None]],
    profile_key: str,
    observed_at: datetime | None = None,
) -> None:
    now = observed_at or utc_now()
    active_ids: set[int] = set()
    for server_id, server_name, icon in guilds:
        active_ids.add(int(server_id))
        await record_gateway_presence(
            session,
            server_id=server_id,
            server_name=server_name,
            icon=icon,
            profile_key=profile_key,
            active=True,
            observed_at=now,
        )

    active_rows = (
        await session.exec(
            select(ServerGatewayInstallation).where(
                ServerGatewayInstallation.profile_key == profile_key,
                ServerGatewayInstallation.active == True,  # noqa: E712
            )
        )
    ).all()
    for installation in active_rows:
        if int(installation.server_id) in active_ids:
            continue
        server = await session.get(Server, int(installation.server_id))
        await record_gateway_presence(
            session,
            server_id=int(installation.server_id),
            server_name=server.server_name if server else None,
            icon=server.icon if server else None,
            profile_key=profile_key,
            active=False,
            observed_at=now,
        )

from fastapi import Depends, HTTPException, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.auth import get_bearer_access_token
from api.dependencies.current_user import get_current_discord_user_id
from api.services.dashboard_sessions import get_dashboard_session
from api.services.dashboard_access_service import assert_dashboard_access, assert_server_admin_or_owner
from api.services.discord_profiles import cache_server_profile, get_profile
from api.services.rbac_service import assert_user_has_permission
from src.db.database import get_session
from src.db.models import Server


async def assert_server_surface(
    *,
    request: Request,
    session: AsyncSession,
    server_id: int,
) -> None:
    dashboard_session = await get_dashboard_session(request, session)
    assert dashboard_session is not None
    server = await session.get(Server, server_id)
    if server is None:
        return
    cache_server_profile(server_id, server.bot_profile)
    if server.bot_profile == dashboard_session.application_profile:
        return
    canonical_base_url = get_profile(server.bot_profile).dashboard_base_url
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "server_surface_mismatch",
            "message": "This server belongs to a different dashboard application.",
            "canonical_url": f"{canonical_base_url}/dashboard/{server_id}",
        },
    )


async def require_server_dashboard_access(
    server_id: int,
    request: Request = None,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    access_token: str = Depends(get_bearer_access_token),
) -> int:
    if request is not None:
        await assert_server_surface(request=request, session=session, server_id=server_id)
    await assert_dashboard_access(
        session=session,
        server_id=server_id,
        caller_user_id=current_user_id,
        access_token=access_token,
    )
    return current_user_id


async def require_server_admin_or_owner(
    server_id: int,
    access_token: str = Depends(get_bearer_access_token),
) -> None:
    await assert_server_admin_or_owner(server_id=server_id, access_token=access_token)


def require_server_permission(permission_key: str):
    async def dependency(
        server_id: int,
        request: Request = None,
        session: AsyncSession = Depends(get_session),
        current_user_id: int = Depends(get_current_discord_user_id),
        access_token: str = Depends(get_bearer_access_token),
    ) -> int:
        if request is not None:
            await assert_server_surface(request=request, session=session, server_id=server_id)
        await assert_dashboard_access(
            session=session,
            server_id=server_id,
            caller_user_id=current_user_id,
            access_token=access_token,
        )
        await assert_user_has_permission(
            session=session,
            server_id=server_id,
            user_id=current_user_id,
            permission_key=permission_key,
            access_token=access_token,
        )
        return current_user_id

    dependency.__name__ = f"require_server_permission_{permission_key.replace('.', '_')}"
    dependency.permission_key = permission_key
    return dependency

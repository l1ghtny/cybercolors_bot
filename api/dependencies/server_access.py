from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.auth import get_bearer_access_token
from api.dependencies.current_user import get_current_discord_user_id
from api.services.dashboard_access_service import assert_dashboard_access, assert_server_admin_or_owner
from src.db.database import get_session


async def require_server_dashboard_access(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    access_token: str = Depends(get_bearer_access_token),
) -> int:
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

from typing import Annotated

from fastapi import Depends, Header
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_current_discord_user_id
from api.services.dashboard_access_service import assert_dashboard_access, assert_server_admin_or_owner
from src.db.database import get_session


async def require_server_dashboard_access(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    authorization: Annotated[str | None, Header()] = None,
) -> int:
    await assert_dashboard_access(
        session=session,
        server_id=server_id,
        caller_user_id=current_user_id,
        authorization=authorization,
    )
    return current_user_id


async def require_server_admin_or_owner(
    server_id: int,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    await assert_server_admin_or_owner(server_id=server_id, authorization=authorization)

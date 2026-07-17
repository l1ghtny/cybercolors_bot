import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.dashboard_sessions import get_dashboard_discord_access_token
from src.db.database import get_session

ALLOW_LEGACY_BEARER_AUTH = os.getenv("DASHBOARD_ALLOW_LEGACY_BEARER_AUTH", "false").lower() == "true"


def _extract_bearer_access_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    token_type, _, access_token = authorization.partition(" ")
    if token_type.lower() != "bearer" or not access_token:
        return None
    return access_token


async def get_bearer_access_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> str:
    legacy_token = _extract_bearer_access_token(authorization)
    if legacy_token and ALLOW_LEGACY_BEARER_AUTH:
        return legacy_token
    if authorization and legacy_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")
    token = await get_dashboard_discord_access_token(request, session, required=True)
    assert token is not None
    return token


async def get_optional_bearer_access_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> str | None:
    legacy_token = _extract_bearer_access_token(authorization)
    if legacy_token and ALLOW_LEGACY_BEARER_AUTH:
        return legacy_token
    if authorization and legacy_token is None:
        return None
    return await get_dashboard_discord_access_token(request, session, required=False)

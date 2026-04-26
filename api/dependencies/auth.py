from typing import Annotated

from fastapi import Header, HTTPException, status


def _extract_bearer_access_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    token_type, _, access_token = authorization.partition(" ")
    if token_type.lower() != "bearer" or not access_token:
        return None
    return access_token


async def get_bearer_access_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    access_token = _extract_bearer_access_token(authorization)
    if access_token is None:
        if authorization is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header missing",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )
    return access_token


async def get_optional_bearer_access_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str | None:
    return _extract_bearer_access_token(authorization)

import os
from typing import Annotated

import httpx
from fastapi import Header, HTTPException, status

DISCORD_API_BASE_URL = "https://discord.com/api/v10"


async def get_current_discord_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> int:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

    token_type, _, access_token = authorization.partition(" ")
    if token_type.lower() != "bearer" or not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API_BASE_URL}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token")
    payload = response.json()
    return int(payload["id"])


async def get_optional_current_discord_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> int | None:
    if not authorization:
        return None
    token_type, _, access_token = authorization.partition(" ")
    if token_type.lower() != "bearer" or not access_token:
        return None

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API_BASE_URL}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code >= 400:
        return None
    payload = response.json()
    return int(payload["id"])


def resolve_actor_user_id(explicit_user_id: str | None, current_user_id: int | None) -> int:
    if current_user_id is not None:
        return current_user_id
    if explicit_user_id and explicit_user_id.isdigit():
        return int(explicit_user_id)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Actor user id is required (either via Bearer token or request body)",
    )

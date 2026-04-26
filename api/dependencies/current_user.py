import asyncio
import os
from dataclasses import dataclass
from time import monotonic
from typing import Annotated

import httpx
from fastapi import Header, HTTPException, status

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
CURRENT_USER_CACHE_TTL_SECONDS = int(os.getenv("CURRENT_USER_CACHE_TTL_SECONDS", "60"))
CURRENT_USER_CACHE_MAX_ENTRIES = int(os.getenv("CURRENT_USER_CACHE_MAX_ENTRIES", "5000"))


@dataclass
class _CurrentUserCacheEntry:
    user_id: int
    expires_at: float


_current_user_cache: dict[str, _CurrentUserCacheEntry] = {}
_current_user_token_locks: dict[str, asyncio.Lock] = {}
_current_user_token_locks_guard = asyncio.Lock()


async def _get_token_lock(access_token: str) -> asyncio.Lock:
    async with _current_user_token_locks_guard:
        lock = _current_user_token_locks.get(access_token)
        if lock is None:
            lock = asyncio.Lock()
            _current_user_token_locks[access_token] = lock
        return lock


def _get_cached_current_user_id(access_token: str) -> int | None:
    if CURRENT_USER_CACHE_TTL_SECONDS <= 0:
        return None
    cached = _current_user_cache.get(access_token)
    if not cached:
        return None
    if cached.expires_at <= monotonic():
        _current_user_cache.pop(access_token, None)
        return None
    return cached.user_id


def _store_cached_current_user_id(access_token: str, user_id: int) -> None:
    if CURRENT_USER_CACHE_TTL_SECONDS <= 0:
        return

    now = monotonic()
    expired_tokens = [
        token
        for token, cache_item in _current_user_cache.items()
        if cache_item.expires_at <= now
    ]
    for token in expired_tokens:
        _current_user_cache.pop(token, None)

    if len(_current_user_cache) >= CURRENT_USER_CACHE_MAX_ENTRIES:
        _current_user_cache.clear()

    _current_user_cache[access_token] = _CurrentUserCacheEntry(
        user_id=user_id,
        expires_at=now + CURRENT_USER_CACHE_TTL_SECONDS,
    )


async def _fetch_current_user_id_from_discord(access_token: str) -> int:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API_BASE_URL}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token")
    if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discord API rate limited while validating access token",
        )
    if response.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Discord API unavailable while validating access token",
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discord API error while validating access token: {response.status_code}",
        )

    payload = response.json()
    return int(payload["id"])


async def get_current_discord_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> int:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

    token_type, _, access_token = authorization.partition(" ")
    if token_type.lower() != "bearer" or not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")

    cached_user_id = _get_cached_current_user_id(access_token)
    if cached_user_id is not None:
        return cached_user_id

    token_lock = await _get_token_lock(access_token)
    async with token_lock:
        cached_user_id = _get_cached_current_user_id(access_token)
        if cached_user_id is not None:
            return cached_user_id

        user_id = await _fetch_current_user_id_from_discord(access_token)
        _store_cached_current_user_id(access_token, user_id)
        return user_id


async def get_optional_current_discord_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> int | None:
    if not authorization:
        return None
    token_type, _, access_token = authorization.partition(" ")
    if token_type.lower() != "bearer" or not access_token:
        return None

    cached_user_id = _get_cached_current_user_id(access_token)
    if cached_user_id is not None:
        return cached_user_id

    token_lock = await _get_token_lock(access_token)
    async with token_lock:
        cached_user_id = _get_cached_current_user_id(access_token)
        if cached_user_id is not None:
            return cached_user_id

        try:
            user_id = await _fetch_current_user_id_from_discord(access_token)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                return None
            raise

        _store_cached_current_user_id(access_token, user_id)
        return user_id


def resolve_actor_user_id(explicit_user_id: str | None, current_user_id: int | None) -> int:
    if current_user_id is not None:
        return current_user_id
    if explicit_user_id and explicit_user_id.isdigit():
        return int(explicit_user_id)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Actor user id is required (either via Bearer token or request body)",
    )

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Header, Query
from fastapi import Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.auth import (
    AuthGuildModel,
    AuthLoginRequestModel,
    AuthLoginResponseModel,
    AuthUserModel,
)
from api.services.dashboard_access_service import load_dashboard_access_maps
from src.db.database import get_session
from src.db.models import GlobalUser, Server

load_dotenv()

logger = logging.getLogger("uvicorn")

auth = APIRouter(prefix="/auth", tags=["auth"])


test_bot_token = os.getenv("DISCORD_TOKEN_TEST")
bot_token = os.getenv("DISCORD_TOKEN")
# --- Discord OAuth2 Credentials ---
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_TEST_CLIENT_ID = os.getenv("DISCORD_TEST_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_API_BASE_URL = "https://discord.com/api/v10"
AUTH_GUILDS_CACHE_TTL_SECONDS = int(os.getenv("AUTH_GUILDS_CACHE_TTL_SECONDS", "120"))
AUTH_GUILDS_CACHE_MAX_ENTRIES = int(os.getenv("AUTH_GUILDS_CACHE_MAX_ENTRIES", "1000"))
BOT_GUILDS_CACHE_TTL_SECONDS = int(os.getenv("BOT_GUILDS_CACHE_TTL_SECONDS", "120"))


@dataclass
class _UserGuildsCacheEntry:
    payload: list[dict]
    expires_at: float


_user_guilds_cache: dict[int, _UserGuildsCacheEntry] = {}


@dataclass
class _BotGuildsCacheEntry:
    guild_ids: set[int]
    expires_at: float


_bot_guilds_cache: _BotGuildsCacheEntry | None = None


def _get_bot_token_for_auth() -> str:
    token = test_bot_token or bot_token
    if not token:
        raise HTTPException(status_code=500, detail="Discord bot token is not configured")
    return token


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _extract_guild_id(guild: dict) -> int | None:
    raw_id = guild.get("id")
    if raw_id is None or not str(raw_id).isdigit():
        return None
    return int(raw_id)


async def _get_db_active_bot_guild_ids(
    session: AsyncSession,
    guild_ids: set[int],
) -> set[int]:
    if not guild_ids:
        return set()
    rows = (
        await session.exec(
            select(Server.server_id).where(
                Server.server_id.in_(list(guild_ids)),
                Server.bot_active == True,  # noqa: E712
            )
        )
    ).all()
    return {int(server_id) for server_id in rows}


async def _has_any_active_bot_guilds(session: AsyncSession) -> bool:
    row = (
        await session.exec(
            select(Server.server_id).where(Server.bot_active == True).limit(1)  # noqa: E712
        )
    ).first()
    return row is not None


def _get_cached_user_guilds(user_id: int, refresh: bool) -> list[dict] | None:
    if refresh or AUTH_GUILDS_CACHE_TTL_SECONDS <= 0:
        return None

    cached = _user_guilds_cache.get(user_id)
    if not cached:
        return None

    if cached.expires_at <= monotonic():
        _user_guilds_cache.pop(user_id, None)
        return None

    # Return a shallow copy so downstream code doesn't mutate shared cache state.
    return [dict(item) for item in cached.payload]


def _store_cached_user_guilds(user_id: int, payload: list[dict]) -> None:
    if AUTH_GUILDS_CACHE_TTL_SECONDS <= 0:
        return

    now = monotonic()
    expired_user_ids = [
        cached_user_id
        for cached_user_id, cached_value in _user_guilds_cache.items()
        if cached_value.expires_at <= now
    ]
    for expired_user_id in expired_user_ids:
        _user_guilds_cache.pop(expired_user_id, None)

    if len(_user_guilds_cache) >= AUTH_GUILDS_CACHE_MAX_ENTRIES:
        _user_guilds_cache.clear()

    _user_guilds_cache[user_id] = _UserGuildsCacheEntry(
        payload=[dict(item) for item in payload],
        expires_at=now + AUTH_GUILDS_CACHE_TTL_SECONDS,
    )


def _get_cached_bot_guild_ids(refresh: bool) -> set[int] | None:
    if refresh or BOT_GUILDS_CACHE_TTL_SECONDS <= 0:
        return None
    if _bot_guilds_cache is None:
        return None
    if _bot_guilds_cache.expires_at <= monotonic():
        return None
    return set(_bot_guilds_cache.guild_ids)


def _store_cached_bot_guild_ids(guild_ids: set[int]) -> None:
    global _bot_guilds_cache
    if BOT_GUILDS_CACHE_TTL_SECONDS <= 0:
        return
    _bot_guilds_cache = _BotGuildsCacheEntry(
        guild_ids=set(guild_ids),
        expires_at=monotonic() + BOT_GUILDS_CACHE_TTL_SECONDS,
    )


async def _fetch_bot_guild_ids(client: httpx.AsyncClient, bot_headers: dict[str, str]) -> set[int]:
    guild_ids: set[int] = set()
    after: str | None = None
    seen_cursors: set[str] = set()

    while True:
        params: dict[str, str | int] = {"limit": 200}
        if after is not None:
            params["after"] = after

        response = await client.get(
            f"{DISCORD_API_BASE_URL}/users/@me/guilds",
            headers=bot_headers,
            params=params,
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error fetching bot guilds from Discord: {response.text}",
            )

        payload = response.json()
        if not isinstance(payload, list) or not payload:
            break

        page_ids = [int(g["id"]) for g in payload if str(g.get("id", "")).isdigit()]
        guild_ids.update(page_ids)

        if len(payload) < 200 or not page_ids:
            break

        next_after = str(max(page_ids))
        if next_after in seen_cursors:
            break
        seen_cursors.add(next_after)
        after = next_after

    return guild_ids


async def _get_bot_guild_ids(
    client: httpx.AsyncClient,
    bot_headers: dict[str, str],
    refresh: bool,
) -> set[int]:
    cached = _get_cached_bot_guild_ids(refresh=refresh)
    if cached is not None:
        return cached
    guild_ids = await _fetch_bot_guild_ids(client=client, bot_headers=bot_headers)
    _store_cached_bot_guild_ids(guild_ids)
    return guild_ids


async def _apply_bot_presence_snapshot(
    session: AsyncSession,
    bot_guild_ids: set[int],
) -> None:
    now = _naive_utcnow()

    existing_rows = (
        await session.exec(select(Server).where(Server.server_id.in_(list(bot_guild_ids))))
    ).all() if bot_guild_ids else []
    existing_by_id = {int(item.server_id): item for item in existing_rows}

    for guild_id in bot_guild_ids:
        server = existing_by_id.get(guild_id)
        if not server:
            session.add(
                Server(
                    server_id=guild_id,
                    server_name=str(guild_id),
                    bot_active=True,
                    bot_joined_at=now,
                    bot_presence_updated_at=now,
                )
            )
            continue

        server.bot_active = True
        server.bot_left_at = None
        server.bot_presence_updated_at = now
        if server.bot_joined_at is None:
            server.bot_joined_at = now
        session.add(server)

    currently_active_rows = (await session.exec(select(Server).where(Server.bot_active == True))).all()  # noqa: E712
    for server in currently_active_rows:
        if int(server.server_id) in bot_guild_ids:
            continue
        server.bot_active = False
        server.bot_left_at = now
        server.bot_presence_updated_at = now
        session.add(server)

    await session.flush()


async def _sync_bot_presence_from_discord(
    client: httpx.AsyncClient,
    bot_headers: dict[str, str],
    session: AsyncSession,
) -> set[int]:
    bot_guild_ids = await _fetch_bot_guild_ids(client=client, bot_headers=bot_headers)
    _store_cached_bot_guild_ids(bot_guild_ids)
    await _apply_bot_presence_snapshot(session=session, bot_guild_ids=bot_guild_ids)
    return bot_guild_ids


def _to_auth_guild_payload(guild: dict) -> dict:
    payload = dict(guild)
    payload["id"] = str(guild.get("id", ""))
    payload["name"] = str(guild.get("name", ""))
    payload["icon"] = guild.get("icon")
    payload["owner"] = bool(guild.get("owner", False))
    permissions = guild.get("permissions", "0")
    payload["permissions"] = str(permissions) if permissions is not None else "0"
    payload["bot_present"] = True
    payload["dashboard_access"] = True
    return payload


@auth.post("/login", response_model=AuthLoginResponseModel)
async def login(body: AuthLoginRequestModel, session: AsyncSession = Depends(get_session)):
    try:
        code = body.code
        # Get the redirect URI from the frontend request
        client_redirect_uri = body.redirect_uri

        if not code:
            raise HTTPException(status_code=400, detail="Authorization code is required.")

        # Determine which redirect URI to use
        # If the frontend sent one, use it. Otherwise, use the env variable.
        redirect_uri = client_redirect_uri or DISCORD_REDIRECT_URI

        # --- 1. Exchange code for access token ---
        token_data = {
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri, # Use the dynamic URI here
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient() as client:
            token_res = await client.post(f"{DISCORD_API_BASE_URL}/oauth2/token", data=token_data, headers=headers)
            token_res.raise_for_status()
            token_json = token_res.json()
            access_token = token_json["access_token"]

            # --- 2. Fetch user data from Discord ---
            user_headers = {"Authorization": f"Bearer {access_token}"}
            user_res = await client.get(f"{DISCORD_API_BASE_URL}/users/@me", headers=user_headers)
            user_res.raise_for_status()
            user_json = user_res.json()

            discord_id = int(user_json["id"])
            username = user_json["username"]
            avatar = user_json.get("avatar")

            # --- 3. Create or update user in our database ---
            db_user = await session.get(GlobalUser, discord_id)
            if not db_user:
                db_user = GlobalUser(discord_id=discord_id, username=username, avatar_hash=avatar)
                session.add(db_user)
            else:
                db_user.username = username
                db_user.avatar_hash = avatar

            # The session will be committed automatically by the dependency

        # --- 4. Return the access token and user info to the frontend ---
        user_payload = AuthUserModel(
            discord_id=str(db_user.discord_id),
            username=db_user.username,
            avatar_hash=db_user.avatar_hash,
        )
        return {
            "message": "Login successful",
            "user": user_payload,
            "access_token": access_token,
            "token_type": "Bearer"
        }

    except httpx.HTTPStatusError as e:
        # This will now correctly log errors from Discord
        print(f"HTTPX Error: {e.response.text}")
        raise HTTPException(status_code=e.response.status_code,
                            detail=f"Error communicating with Discord: {e.response.text}")
    except Exception as e:
        # This will now correctly log any other unexpected errors
        print(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")


@auth.get("/guilds", response_model=list[AuthGuildModel])
async def get_user_guilds(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
    refresh: bool = Query(default=False),
):
    """
    Fetches the guilds for the authenticated user from Discord and filters them.
    Returns only guilds where:
    - the bot is currently present;
    - and the user is owner/admin or explicitly allowlisted for dashboard access.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token_type, _, access_token = authorization.partition(' ')
    if token_type.lower() != 'bearer' or not access_token:
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    headers = {"Authorization": f"Bearer {access_token}"}
    bot_headers = {"Authorization": f"Bot {_get_bot_token_for_auth()}"}

    async with httpx.AsyncClient() as client:
        try:
            me_res = await client.get(f"{DISCORD_API_BASE_URL}/users/@me", headers=headers)
            me_res.raise_for_status()
            me_json = me_res.json()
            current_user_id = int(me_json["id"])
            request_started_at = monotonic()

            cached_payload = _get_cached_user_guilds(current_user_id, refresh=refresh)
            if cached_payload is not None:
                cached_guild_ids = {
                    guild_id
                    for guild in cached_payload
                    for guild_id in [_extract_guild_id(guild)]
                    if guild_id is not None
                }
                active_cached_ids = await _get_db_active_bot_guild_ids(session, cached_guild_ids)
                filtered_cached_payload = [
                    guild
                    for guild in cached_payload
                    if (guild_id := _extract_guild_id(guild)) is not None and guild_id in active_cached_ids
                ]

                if len(filtered_cached_payload) != len(cached_payload):
                    _store_cached_user_guilds(current_user_id, filtered_cached_payload)

                logger.info(
                    "auth.guilds cache hit user=%s guilds=%s filtered=%s refresh=%s duration_ms=%s",
                    current_user_id,
                    len(cached_payload),
                    len(filtered_cached_payload),
                    refresh,
                    int((monotonic() - request_started_at) * 1000),
                )
                return filtered_cached_payload

            guilds_res = await client.get(f"{DISCORD_API_BASE_URL}/users/@me/guilds", headers=headers)
            guilds_res.raise_for_status()
            guilds_json = guilds_res.json()
            user_guild_ids = {
                guild_id
                for guild in guilds_json
                for guild_id in [_extract_guild_id(guild)]
                if guild_id is not None
            }

            if refresh:
                active_bot_guild_ids = await _sync_bot_presence_from_discord(
                    client=client,
                    bot_headers=bot_headers,
                    session=session,
                )
                active_bot_guild_ids = active_bot_guild_ids.intersection(user_guild_ids)
            else:
                active_bot_guild_ids = await _get_db_active_bot_guild_ids(session, user_guild_ids)
                if not active_bot_guild_ids and user_guild_ids and not await _has_any_active_bot_guilds(session):
                    fallback_bot_guild_ids = await _get_bot_guild_ids(
                        client=client,
                        bot_headers=bot_headers,
                        refresh=False,
                    )
                    if fallback_bot_guild_ids:
                        await _apply_bot_presence_snapshot(session=session, bot_guild_ids=fallback_bot_guild_ids)
                        active_bot_guild_ids = fallback_bot_guild_ids.intersection(user_guild_ids)
                        logger.info(
                            "auth.guilds bootstrapped bot presence from Discord snapshot guilds=%s",
                            len(fallback_bot_guild_ids),
                        )

            # The permissions integer is a bitfield. 8 is the administrator flag.
            ADMINISTRATOR_FLAG = 1 << 3

            authorized_guild_ids: set[int] = set()
            candidate_guilds: list[dict] = []
            candidate_guild_ids: list[int] = []
            for guild in guilds_json:
                guild_id = _extract_guild_id(guild)
                if guild_id is None:
                    continue
                if guild_id not in active_bot_guild_ids:
                    logger.info(
                        'Skipping guild "%s" (%s): bot not present',
                        guild.get("name", "unknown"),
                        guild_id,
                    )
                    continue
                is_owner = bool(guild.get("owner"))
                permissions = int(guild.get("permissions", 0))
                is_admin = bool(permissions & ADMINISTRATOR_FLAG)

                if is_owner or is_admin:
                    authorized_guild_ids.add(guild_id)
                    continue

                candidate_guilds.append(guild)
                candidate_guild_ids.append(guild_id)

            access_users_map, access_roles_map = await load_dashboard_access_maps(session, candidate_guild_ids)

            for guild in candidate_guilds:
                guild_id = int(guild["id"])
                allowed_users = access_users_map.get(guild_id, set())
                if current_user_id in allowed_users:
                    authorized_guild_ids.add(guild_id)
                    continue

                allowed_roles = access_roles_map.get(guild_id, set())
                if not allowed_roles:
                    continue

                member_res = await client.get(
                    f"{DISCORD_API_BASE_URL}/guilds/{guild_id}/members/{current_user_id}",
                    headers=bot_headers,
                )
                if member_res.status_code != 200:
                    logger.info(
                        'Skipping guild "%s" (%s): bot not present or cannot fetch member',
                        guild.get("name", "unknown"),
                        guild_id,
                    )
                    continue

                member_json = member_res.json()
                member_role_ids = {
                    int(role_id) for role_id in member_json.get("roles", []) if str(role_id).isdigit()
                }
                if member_role_ids.intersection(allowed_roles):
                    authorized_guild_ids.add(guild_id)

            authorized_guilds = [
                _to_auth_guild_payload(guild)
                for guild in guilds_json
                if str(guild.get("id", "")).isdigit() and int(guild["id"]) in authorized_guild_ids
            ]

            _store_cached_user_guilds(current_user_id, authorized_guilds)
            logger.info(
                "auth.guilds cache miss user=%s refresh=%s user_guilds=%s bot_active_overlap=%s candidates=%s authorized=%s duration_ms=%s",
                current_user_id,
                refresh,
                len(guilds_json),
                len(active_bot_guild_ids),
                len(candidate_guilds),
                len(authorized_guilds),
                int((monotonic() - request_started_at) * 1000),
            )
            return authorized_guilds

        except httpx.HTTPStatusError as e:
            # Handle cases where the token might be expired or invalid
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Error fetching guilds from Discord: {e.response.text}")


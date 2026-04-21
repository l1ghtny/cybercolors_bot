import logging
import os
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, Header
from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.dashboard_access_service import load_dashboard_access_maps
from src.db.database import get_session
from src.db.models import GlobalUser

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


def _get_bot_token_for_auth() -> str:
    token = test_bot_token or bot_token
    if not token:
        raise HTTPException(status_code=500, detail="Discord bot token is not configured")
    return token


@auth.post("/login")
async def login(request: Request, session: AsyncSession = Depends(get_session)):
    try:
        body = await request.json()
        code = body.get("code")
        # Get the redirect URI from the frontend request
        client_redirect_uri = body.get("redirect_uri")

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
        user_dump = db_user.model_dump()
        user_dump['discord_id'] = str(user_dump["discord_id"])


        return {
            "message": "Login successful",
            "user": user_dump,
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


@auth.get("/guilds")
async def get_user_guilds(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Fetches the guilds for the authenticated user from Discord and filters them.
    Returns only guilds where the user is an owner or has administrator permissions.
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

            guilds_res = await client.get(f"{DISCORD_API_BASE_URL}/users/@me/guilds", headers=headers)
            guilds_res.raise_for_status()
            guilds_json = guilds_res.json()
            guild_ids = [int(guild["id"]) for guild in guilds_json if str(guild.get("id", "")).isdigit()]
            access_users_map, access_roles_map = await load_dashboard_access_maps(session, guild_ids)

            # The permissions integer is a bitfield. 8 is the administrator flag.
            ADMINISTRATOR_FLAG = 1 << 3

            authorized_guilds: list[dict] = []
            for guild in guilds_json:
                guild_id = int(guild["id"])
                is_owner = bool(guild.get("owner"))
                permissions = int(guild.get("permissions", 0))
                is_admin = bool(permissions & ADMINISTRATOR_FLAG)

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
                allowed_users = access_users_map.get(guild_id, set())
                allowed_roles = access_roles_map.get(guild_id, set())
                allowlisted = (current_user_id in allowed_users) or bool(member_role_ids.intersection(allowed_roles))

                if is_owner or is_admin or allowlisted:
                    authorized_guilds.append(guild)

            return authorized_guilds

        except httpx.HTTPStatusError as e:
            # Handle cases where the token might be expired or invalid
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Error fetching guilds from Discord: {e.response.text}")


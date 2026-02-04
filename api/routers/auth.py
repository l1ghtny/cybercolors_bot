import os
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, Header
from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import get_session
from src.db.models import GlobalUser

load_dotenv()
auth = APIRouter(prefix="/auth", tags=["auth"])

# --- Discord OAuth2 Credentials ---
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_API_BASE_URL = "https://discord.com/api/v10"


@auth.post("/login")
async def login(request: Request, session: AsyncSession = Depends(get_session)):
    """
    Handles the final step of the OAuth2 flow.
    Exchanges the code for an access token and returns it along with user data.
    """
    try:
        body = await request.json()
        code = body.get("code")
        if not code:
            raise HTTPException(status_code=400, detail="Authorization code is required.")

        # --- 1. Exchange code for access token ---
        token_data = {
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
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
async def get_user_guilds(authorization: Annotated[str | None, Header()] = None):
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

    async with httpx.AsyncClient() as client:
        try:
            guilds_res = await client.get(f"{DISCORD_API_BASE_URL}/users/@me/guilds", headers=headers)
            guilds_res.raise_for_status()
            guilds_json = guilds_res.json()

            # Filter guilds where the user has admin permissions or is the owner
            # The permissions integer is a bitfield. 8 is the administrator flag.
            ADMINISTRATOR_FLAG = 1 << 3

            authorized_guilds = [
                guild for guild in guilds_json
                if guild["owner"] or (int(guild["permissions"]) & ADMINISTRATOR_FLAG)
            ]

            return authorized_guilds

        except httpx.HTTPStatusError as e:
            # Handle cases where the token might be expired or invalid
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Error fetching guilds from Discord: {e.response.text}")


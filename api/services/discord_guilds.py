import os

import httpx
from fastapi import HTTPException, status

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
TEXT_CHANNEL_TYPES = {0, 5}


def _get_bot_token() -> str:
    token = os.getenv("DISCORD_TOKEN_TEST") or os.getenv("DISCORD_TOKEN")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Discord bot token is not configured",
        )
    return token


async def _discord_get(path: str) -> list[dict] | dict:
    headers = {"Authorization": f"Bot {_get_bot_token()}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{DISCORD_API_BASE_URL}{path}", headers=headers)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Discord API error: {response.text}",
        )
    return response.json()


async def fetch_guild_channels(server_id: int) -> list[dict]:
    channels = await _discord_get(f"/guilds/{server_id}/channels")
    if isinstance(channels, list):
        return channels
    return []


async def fetch_guild_roles(server_id: int) -> list[dict]:
    roles = await _discord_get(f"/guilds/{server_id}/roles")
    if isinstance(roles, list):
        return roles
    return []


async def fetch_channel(server_id: int, channel_id: int) -> dict | None:
    channels = await fetch_guild_channels(server_id)
    for channel in channels:
        if int(channel["id"]) == channel_id:
            return channel
    return None

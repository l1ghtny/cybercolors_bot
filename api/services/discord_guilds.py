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


async def _discord_patch(path: str, payload: dict) -> list[dict] | dict:
    headers = {"Authorization": f"Bot {_get_bot_token()}"}
    async with httpx.AsyncClient() as client:
        response = await client.patch(f"{DISCORD_API_BASE_URL}{path}", headers=headers, json=payload)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Discord API error: {response.text}",
        )
    return response.json()


async def _discord_post(path: str, payload: dict) -> list[dict] | dict:
    headers = {"Authorization": f"Bot {_get_bot_token()}"}
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{DISCORD_API_BASE_URL}{path}", headers=headers, json=payload)
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


async def fetch_guild_metadata(server_id: int) -> dict:
    payload = await _discord_get(f"/guilds/{server_id}?with_counts=true")
    if isinstance(payload, dict):
        return payload
    return {}


async def fetch_guild_member(server_id: int, user_id: int) -> dict | None:
    try:
        payload = await _discord_get(f"/guilds/{server_id}/members/{user_id}")
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return None
        raise
    if isinstance(payload, dict):
        return payload
    return None


async def fetch_channel_message(channel_id: int, message_id: int) -> dict:
    payload = await _discord_get(f"/channels/{channel_id}/messages/{message_id}")
    if isinstance(payload, dict):
        return payload
    return {}


async def update_guild_role_permissions(server_id: int, role_id: int, permissions: int) -> dict:
    payload = await _discord_patch(
        f"/guilds/{server_id}/roles/{role_id}",
        {"permissions": str(permissions)},
    )
    if isinstance(payload, dict):
        return payload
    return {}


async def create_guild_role(server_id: int, name: str) -> dict:
    payload = await _discord_post(
        f"/guilds/{server_id}/roles",
        {
            "name": name,
            "permissions": "0",
            "mentionable": False,
            "hoist": False,
        },
    )
    if isinstance(payload, dict):
        return payload
    return {}


async def create_channel_message(channel_id: int, content: str) -> dict:
    payload = await _discord_post(
        f"/channels/{channel_id}/messages",
        {
            "content": content,
            "allowed_mentions": {"parse": []},
        },
    )
    if isinstance(payload, dict):
        return payload
    return {}

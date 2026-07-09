import os
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
TEXT_CHANNEL_TYPES = {0, 5}
VOICE_CHANNEL_TYPE = 2


def _get_bot_token() -> str:
    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN_TEST") or os.getenv("DISCORD_TOKEN")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Discord bot token is not configured",
        )
    return token


async def _discord_get(path: str, params: dict | None = None) -> list[dict] | dict:
    headers = {"Authorization": f"Bot {_get_bot_token()}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{DISCORD_API_BASE_URL}{path}", headers=headers, params=params)
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



async def _discord_put(path: str, payload: dict | None = None) -> list[dict] | dict:
    headers = {"Authorization": f"Bot {_get_bot_token()}"}
    async with httpx.AsyncClient() as client:
        response = await client.put(f"{DISCORD_API_BASE_URL}{path}", headers=headers, json=payload)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Discord API error: {response.text}",
        )
    if not response.content:
        return {}
    return response.json()

async def _discord_delete(path: str, payload: dict | None = None, reason: str | None = None) -> list[dict] | dict:
    headers = {"Authorization": f"Bot {_get_bot_token()}"}
    if reason:
        headers["X-Audit-Log-Reason"] = quote(reason[:512])
    async with httpx.AsyncClient() as client:
        response = await client.request("DELETE", f"{DISCORD_API_BASE_URL}{path}", headers=headers, json=payload)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Discord API error: {response.text}",
        )
    if not response.content:
        return {}
    return response.json()
async def fetch_guild_bans(server_id: int, limit: int = 1000, after: int | None = None) -> list[dict]:
    params: dict[str, str | int] = {"limit": max(1, min(limit, 1000))}
    if after is not None:
        params["after"] = str(after)
    payload = await _discord_get(f"/guilds/{server_id}/bans", params=params)
    if isinstance(payload, list):
        return payload
    return []


async def fetch_guild_audit_logs(
    server_id: int,
    *,
    limit: int = 100,
    before: int | None = None,
    action_type: int | None = None,
) -> dict:
    params: dict[str, str | int] = {"limit": max(1, min(limit, 100))}
    if before is not None:
        params["before"] = str(before)
    if action_type is not None:
        params["action_type"] = action_type
    payload = await _discord_get(f"/guilds/{server_id}/audit-logs", params=params)
    if isinstance(payload, dict):
        return payload
    return {}

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


async def fetch_current_bot_user() -> dict:
    payload = await _discord_get("/users/@me")
    if isinstance(payload, dict):
        return payload
    return {}


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


async def search_guild_members(server_id: int, query: str, limit: int = 10) -> list[dict]:
    payload = await _discord_get(
        f"/guilds/{server_id}/members/search",
        params={"query": query, "limit": max(1, min(limit, 1000))},
    )
    if isinstance(payload, list):
        return payload
    return []


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


async def create_guild_role(
    server_id: int,
    name: str,
    *,
    permissions: int | str = 0,
    mentionable: bool = False,
    hoist: bool = False,
    color: int | None = None,
) -> dict:
    payload: dict = {
        "name": name,
        "permissions": str(permissions),
        "mentionable": mentionable,
        "hoist": hoist,
    }
    if color is not None:
        payload["color"] = color
    payload = await _discord_post(
        f"/guilds/{server_id}/roles",
        payload,
    )
    if isinstance(payload, dict):
        return payload
    return {}


async def create_guild_voice_channel(
    server_id: int,
    name: str,
    *,
    category_id: int | str | None = None,
) -> dict:
    payload: dict = {
        "name": name,
        "type": VOICE_CHANNEL_TYPE,
    }
    if category_id:
        payload["parent_id"] = str(category_id)
    payload = await _discord_post(
        f"/guilds/{server_id}/channels",
        payload,
    )
    if isinstance(payload, dict):
        return payload
    return {}


async def create_channel_message(
    channel_id: int,
    content: str | None = None,
    embeds: list[dict] | None = None,
) -> dict:
    message_payload: dict = {"allowed_mentions": {"parse": []}}
    if content is not None:
        message_payload["content"] = content
    if embeds:
        message_payload["embeds"] = embeds

    payload = await _discord_post(
        f"/channels/{channel_id}/messages",
        message_payload,
    )
    if isinstance(payload, dict):
        return payload
    return {}


async def delete_channel_message(channel_id: int, message_id: int) -> None:
    await _discord_delete(f"/channels/{channel_id}/messages/{message_id}")


async def delete_channel(channel_id: int, *, reason: str | None = None) -> None:
    await _discord_delete(f"/channels/{channel_id}", reason=reason)


async def create_user_dm_channel(user_id: int) -> dict:
    payload = await _discord_post(
        "/users/@me/channels",
        {"recipient_id": str(user_id)},
    )
    if isinstance(payload, dict):
        return payload
    return {}


async def edit_channel_message(
    channel_id: int,
    message_id: int,
    *,
    content: str | None = None,
    embeds: list[dict] | None = None,
    components: list[dict] | None = None,
) -> dict:
    message_payload: dict = {"allowed_mentions": {"parse": []}}
    if content is not None:
        message_payload["content"] = content
    if embeds is not None:
        message_payload["embeds"] = embeds
    if components is not None:
        message_payload["components"] = components

    payload = await _discord_patch(
        f"/channels/{channel_id}/messages/{message_id}",
        message_payload,
    )
    if isinstance(payload, dict):
        return payload
    return {}


async def create_direct_message(user_id: int, content: str) -> dict:
    channel = await create_user_dm_channel(user_id)
    channel_id = channel.get("id")
    if channel_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Discord API did not return a DM channel id",
        )
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


async def add_guild_member_role(server_id: int, user_id: int, role_id: int) -> None:
    await _discord_put(f"/guilds/{server_id}/members/{user_id}/roles/{role_id}")


async def remove_guild_member_role(server_id: int, user_id: int, role_id: int) -> None:
    await _discord_delete(f"/guilds/{server_id}/members/{user_id}/roles/{role_id}")


async def ban_guild_member(server_id: int, user_id: int, delete_message_seconds: int = 0) -> None:
    await _discord_put(
        f"/guilds/{server_id}/bans/{user_id}",
        {"delete_message_seconds": max(0, min(delete_message_seconds, 604800))},
    )


async def unban_guild_member(server_id: int, user_id: int) -> None:
    await _discord_delete(f"/guilds/{server_id}/bans/{user_id}")


async def kick_guild_member(server_id: int, user_id: int) -> None:
    await _discord_delete(f"/guilds/{server_id}/members/{user_id}")

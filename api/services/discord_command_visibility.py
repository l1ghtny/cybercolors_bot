import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, status

from api.models.discord_command_visibility import (
    DiscordCommandPermissionOverwriteModel,
    DiscordCommandVisibilityApplyResultModel,
    DiscordCommandVisibilityChildModel,
    DiscordCommandVisibilityCommandModel,
    DiscordCommandVisibilityReadModel,
    DiscordCommandVisibilityTargetUpdateModel,
    DiscordCommandVisibilityWriteResponseModel,
)
from api.services.bot_command_catalog import list_bot_commands
from api.services.discord_guilds import DISCORD_API_BASE_URL, _get_bot_token


COMMAND_PERMISSION_SCOPE = "applications.commands.permissions.update"
ADMINISTRATOR = 1 << 3
MANAGE_GUILD = 1 << 5
MANAGE_ROLES = 1 << 28
logger = logging.getLogger(__name__)


@dataclass
class DiscordVisibilityError(Exception):
    code: str
    detail: str
    status_code: int


def _application_id() -> str:
    application_id = os.getenv("DISCORD_CLIENT_ID")
    if not application_id or not application_id.isdigit():
        raise DiscordVisibilityError("discord_api_unavailable", "Discord application ID is not configured", 503)
    return application_id


def _is_test_guild(server_id: int) -> bool:
    return os.getenv("TEST_GUILD_ID", "").strip() == str(server_id)


def _overwrites(payload: Any) -> list[DiscordCommandPermissionOverwriteModel]:
    if not isinstance(payload, list):
        return []
    result: list[DiscordCommandPermissionOverwriteModel] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_type = item.get("type")
        permission_type = {1: "role", 2: "user", 3: "channel", "1": "role", "2": "user", "3": "channel"}.get(raw_type, raw_type)
        if permission_type not in {"role", "user", "channel"} or not str(item.get("id", "")).isdigit():
            continue
        result.append(DiscordCommandPermissionOverwriteModel(
            id=str(item["id"]), type=permission_type, permission=bool(item.get("permission")),
        ))
    return result


def _catalog_by_invoke() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for command in list_bot_commands(locale="en"):
        result[command.invoke.lstrip("/")] = list(command.required_rbac_permissions)
    return result


def _children(command: dict[str, Any], native_target_id: str, catalog: dict[str, list[str]]) -> list[DiscordCommandVisibilityChildModel]:
    children: list[DiscordCommandVisibilityChildModel] = []

    def walk(options: list[dict[str, Any]], prefix: str) -> None:
        for option in options:
            name = str(option.get("name", "")).strip()
            if not name:
                continue
            qualified_name = f"{prefix} {name}"
            nested = option.get("options")
            if isinstance(nested, list) and nested:
                walk([item for item in nested if isinstance(item, dict)], qualified_name)
                continue
            invoke = qualified_name.lstrip("/")
            children.append(DiscordCommandVisibilityChildModel(
                qualified_name=qualified_name,
                description=option.get("description"),
                native_target_id=native_target_id,
                required_rbac_permissions=catalog.get(invoke, []),
            ))

    options = command.get("options")
    if isinstance(options, list):
        walk([item for item in options if isinstance(item, dict)], f"/{command.get('name', '')}")
    return children


async def _discord_get(
    client: httpx.AsyncClient,
    path: str,
    headers: dict[str, str],
    *,
    error_code: str = "discord_api_unavailable",
    error_detail: str = "Discord rejected the request used to load command visibility",
    error_status_code: int | None = None,
) -> Any:
    response = await client.get(f"{DISCORD_API_BASE_URL}{path}", headers=headers)
    if response.status_code >= 400:
        logger.warning(
            "Discord command visibility GET failed path=%s status=%s",
            path,
            response.status_code,
        )
        # A Discord 4xx is an upstream failure from this dashboard's
        # perspective. Do not leak it as our own 403 product-access denial.
        raise DiscordVisibilityError(
            error_code,
            error_detail,
            error_status_code
            if error_status_code is not None
            else (502 if response.status_code < 500 else 503),
        )
    return response.json()


async def _assert_bot_matches_application(client: httpx.AsyncClient, application_id: str) -> None:
    """Fail clearly when the bot and OAuth client are configured for different apps."""
    payload = await _discord_get(
        client,
        "/oauth2/applications/@me",
        {"Authorization": f"Bot {_get_bot_token()}"},
    )
    bot_application_id = str(payload.get("id", "")) if isinstance(payload, dict) else ""
    if not bot_application_id.isdigit():
        raise DiscordVisibilityError("discord_api_unavailable", "Discord did not return the bot application ID", 502)
    if bot_application_id != application_id:
        raise DiscordVisibilityError(
            "discord_application_mismatch",
            "DISCORD_CLIENT_ID does not match the application attached to the configured bot token",
            503,
        )


async def _capabilities(client: httpx.AsyncClient, access_token: str, server_id: int) -> tuple[bool, bool]:
    headers = {"Authorization": f"Bearer {access_token}"}
    oauth = await _discord_get(
        client,
        "/oauth2/@me",
        headers,
        error_code="discord_oauth_reconnect_required",
        error_detail="Discord command-management access expired or was revoked. Reconnect it and try again.",
        error_status_code=401,
    )
    scopes = oauth.get("scopes", []) if isinstance(oauth, dict) else []
    if isinstance(scopes, str):
        scopes = scopes.split()
    scope_granted = COMMAND_PERMISSION_SCOPE in scopes
    guilds = await _discord_get(
        client,
        "/users/@me/guilds",
        headers,
        error_code="discord_oauth_reconnect_required",
        error_detail="Discord command-management access expired or was revoked. Reconnect it and try again.",
        error_status_code=401,
    )
    guild = next((item for item in guilds if str(item.get("id")) == str(server_id)), None) if isinstance(guilds, list) else None
    if not isinstance(guild, dict):
        return scope_granted, False
    permissions = int(guild.get("permissions", 0) or 0)
    native_ok = bool(guild.get("owner")) or bool(permissions & ADMINISTRATOR) or bool((permissions & MANAGE_GUILD) and (permissions & MANAGE_ROLES))
    return scope_granted, native_ok


async def _effective_commands(client: httpx.AsyncClient, application_id: str, server_id: int) -> list[tuple[dict[str, Any], str]]:
    headers = {"Authorization": f"Bot {_get_bot_token()}"}
    global_commands = await _discord_get(client, f"/applications/{application_id}/commands", headers)
    global_commands = global_commands if isinstance(global_commands, list) else []
    commands: dict[tuple[str, str], tuple[dict[str, Any], str]] = {
        (str(item.get("type", 1)), str(item.get("name", ""))): (item, "global")
        for item in global_commands if isinstance(item, dict)
    }
    if _is_test_guild(server_id):
        guild_commands = await _discord_get(client, f"/applications/{application_id}/guilds/{server_id}/commands", headers)
        for item in guild_commands if isinstance(guild_commands, list) else []:
            if isinstance(item, dict):
                commands[(str(item.get("type", 1)), str(item.get("name", "")))] = (item, "guild")
    return list(commands.values())


async def read_visibility(server_id: int, access_token: str) -> DiscordCommandVisibilityReadModel:
    application_id = _application_id()
    async with httpx.AsyncClient() as client:
        await _assert_bot_matches_application(client, application_id)
        scope_granted, native_permissions_sufficient = await _capabilities(client, access_token, server_id)
        commands = await _effective_commands(client, application_id, server_id)
        permissions_payload: Any = []
        if scope_granted:
            permissions_payload = await _discord_get(
                client,
                f"/applications/{application_id}/guilds/{server_id}/commands/permissions",
                {"Authorization": f"Bearer {access_token}"},
                error_code="discord_command_permissions_unavailable",
                error_detail=(
                    "Discord rejected the command-permission read. Reconnect command management "
                    "and confirm you can manage the affected roles and channels."
                ),
            )
    permission_by_target = {
        str(item.get("id")): _overwrites(item.get("permissions"))
        for item in permissions_payload if isinstance(item, dict)
    } if isinstance(permissions_payload, list) else {}
    catalog = _catalog_by_invoke()
    returned: list[DiscordCommandVisibilityCommandModel] = []
    for command, source in commands:
        command_id = str(command.get("id", ""))
        if not command_id.isdigit():
            continue
        invoke = str(command.get("name", ""))
        returned.append(DiscordCommandVisibilityCommandModel(
            command_id=command_id,
            name=invoke,
            discord_type=str(command.get("type", 1)),
            source=source,
            description=command.get("description"),
            default_member_permissions=command.get("default_member_permissions"),
            inherits_application_permissions=command_id not in permission_by_target,
            permissions=permission_by_target.get(command_id, []),
            children=_children(command, command_id, catalog),
            uncatalogued=f"/{invoke}" not in catalog and invoke not in catalog,
        ))
    return DiscordCommandVisibilityReadModel(
        application_id=application_id,
        server_id=str(server_id),
        oauth_scope_granted=scope_granted,
        native_permissions_sufficient=native_permissions_sufficient,
        application_permissions=permission_by_target.get(application_id, []),
        commands=sorted(returned, key=lambda item: (item.name, item.discord_type)),
    )


async def write_visibility(server_id: int, access_token: str, updates: list[DiscordCommandVisibilityTargetUpdateModel]) -> DiscordCommandVisibilityWriteResponseModel:
    current = await read_visibility(server_id, access_token)
    if not current.oauth_scope_granted:
        raise DiscordVisibilityError("discord_oauth_scope_required", "Connect command management before changing Discord visibility", 403)
    if not current.native_permissions_sufficient:
        raise DiscordVisibilityError("discord_native_permissions_required", "Discord Manage Guild and Manage Roles permissions are required", 403)
    valid_command_ids = {command.command_id for command in current.commands}
    for update in updates:
        if update.target_kind == "application":
            if update.target_id != current.application_id:
                raise DiscordVisibilityError("discord_permission_target_invalid", "Application target does not match this bot", 422)
        elif update.target_id not in valid_command_ids:
            raise DiscordVisibilityError("discord_command_not_found", "Command target is not registered for this server", 422)
    results: list[DiscordCommandVisibilityApplyResultModel] = []
    async with httpx.AsyncClient() as client:
        for update in updates:
            payload = {
                "permissions": [
                    {
                        "id": item.id,
                        "type": {"role": 1, "user": 2, "channel": 3}[item.type],
                        "permission": item.permission,
                    }
                    for item in update.permissions
                ]
            }
            for attempt in range(2):
                response = await client.put(
                    f"{DISCORD_API_BASE_URL}/applications/{current.application_id}/guilds/{server_id}/commands/{update.target_id}/permissions",
                    headers={"Authorization": f"Bearer {access_token}"}, json=payload,
                )
                if response.status_code != status.HTTP_429_TOO_MANY_REQUESTS or attempt:
                    break
                retry_after = 1.0
                try:
                    retry_after = min(max(float(response.json().get("retry_after", 1)), 0.1), 5.0)
                except (TypeError, ValueError):
                    pass
                await asyncio.sleep(retry_after)
            if response.status_code < 400:
                body = response.json() if response.content else {}
                results.append(DiscordCommandVisibilityApplyResultModel(
                    target_id=update.target_id, ok=True, permissions=_overwrites(body.get("permissions", [])) if isinstance(body, dict) else update.permissions,
                ))
                continue
            code = "discord_rate_limited" if response.status_code == 429 else "discord_permission_update_rejected"
            results.append(DiscordCommandVisibilityApplyResultModel(
                target_id=update.target_id, ok=False, status=response.status_code, error_code=code,
                detail="Discord rejected this command visibility update",
            ))
    return DiscordCommandVisibilityWriteResponseModel(complete=all(item.ok for item in results), results=results)

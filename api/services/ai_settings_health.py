from datetime import datetime, timezone
from typing import Literal

from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.ai_settings import AIChannelPermissionHealthModel, ServerAISettingsHealthModel
from api.services.ai_settings import get_or_create_server_ai_settings, should_moderate_message_channel
from api.services.discord_guilds import (
    TEXT_CHANNEL_TYPES,
    fetch_current_bot_user,
    fetch_guild_channels,
    fetch_guild_member,
    fetch_guild_roles,
)
from src.db.models import ServerModerationSettings

ADMINISTRATOR = 1 << 3
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
EMBED_LINKS = 1 << 14
READ_MESSAGE_HISTORY = 1 << 16


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _role_permission_map(roles: list[dict]) -> dict[int, int]:
    payload: dict[int, int] = {}
    for role in roles:
        role_id = _int_or_none(role.get("id"))
        permissions = _int_or_none(role.get("permissions"))
        if role_id is not None and permissions is not None:
            payload[role_id] = permissions
    return payload


def _apply_overwrite(permissions: int, overwrite: dict) -> int:
    allow = _int_or_none(overwrite.get("allow")) or 0
    deny = _int_or_none(overwrite.get("deny")) or 0
    permissions &= ~deny
    permissions |= allow
    return permissions


def _overwrite_type(overwrite: dict) -> int:
    value = _int_or_none(overwrite.get("type"))
    return value if value is not None else -1


def _effective_channel_permissions(
    *,
    server_id: int,
    channel: dict,
    bot_user_id: int,
    bot_role_ids: set[int],
    role_permissions: dict[int, int],
) -> int:
    permissions = role_permissions.get(server_id, 0)
    for role_id in bot_role_ids:
        permissions |= role_permissions.get(role_id, 0)

    if permissions & ADMINISTRATOR:
        return permissions | VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS | READ_MESSAGE_HISTORY

    overwrites = channel.get("permission_overwrites") or []
    everyone_overwrite = next(
        (item for item in overwrites if _int_or_none(item.get("id")) == server_id and _overwrite_type(item) == 0),
        None,
    )
    if everyone_overwrite:
        permissions = _apply_overwrite(permissions, everyone_overwrite)

    role_allow = 0
    role_deny = 0
    for overwrite in overwrites:
        if _overwrite_type(overwrite) != 0:
            continue
        role_id = _int_or_none(overwrite.get("id"))
        if role_id not in bot_role_ids:
            continue
        role_allow |= _int_or_none(overwrite.get("allow")) or 0
        role_deny |= _int_or_none(overwrite.get("deny")) or 0
    permissions &= ~role_deny
    permissions |= role_allow

    member_overwrite = next(
        (item for item in overwrites if _int_or_none(item.get("id")) == bot_user_id and _overwrite_type(item) == 1),
        None,
    )
    if member_overwrite:
        permissions = _apply_overwrite(permissions, member_overwrite)

    return permissions


def _read_health(
    *,
    server_id: int,
    channel_id: int,
    channel: dict | None,
    bot_user_id: int | None,
    bot_role_ids: set[int],
    role_permissions: dict[int, int],
) -> AIChannelPermissionHealthModel:
    if channel is None:
        return AIChannelPermissionHealthModel(
            channel_id=str(channel_id),
            purpose="moderation",
            configured=True,
            exists=False,
            ok=False,
            reason="Channel was not found in this server.",
        )
    if bot_user_id is None:
        return AIChannelPermissionHealthModel(
            channel_id=str(channel_id),
            channel_name=channel.get("name"),
            purpose="moderation",
            configured=True,
            exists=True,
            ok=False,
            reason="Could not resolve the bot member in this server.",
        )

    permissions = _effective_channel_permissions(
        server_id=server_id,
        channel=channel,
        bot_user_id=bot_user_id,
        bot_role_ids=bot_role_ids,
        role_permissions=role_permissions,
    )
    can_view = bool(permissions & VIEW_CHANNEL)
    can_read_history = bool(permissions & READ_MESSAGE_HISTORY)
    ok = can_view and can_read_history
    reason = None if ok else "Bot needs View Channel and Read Message History permissions."
    return AIChannelPermissionHealthModel(
        channel_id=str(channel_id),
        channel_name=channel.get("name"),
        purpose="moderation",
        configured=True,
        exists=True,
        ok=ok,
        can_view_channel=can_view,
        can_read_message_history=can_read_history,
        reason=reason,
    )


def _write_health(
    *,
    server_id: int,
    channel_id: int | None,
    channel: dict | None,
    bot_user_id: int | None,
    bot_role_ids: set[int],
    role_permissions: dict[int, int],
    purpose: Literal["mod_log", "ai_review"] = "mod_log",
    missing_reason: str = "Moderation log channel is not configured.",
    not_found_reason: str = "Moderation log channel was not found in this server.",
) -> AIChannelPermissionHealthModel:
    if channel_id is None:
        return AIChannelPermissionHealthModel(
            channel_id=None,
            purpose=purpose,
            configured=False,
            exists=False,
            ok=False,
            can_send_messages=False,
            can_embed_links=False,
            reason=missing_reason,
        )
    if channel is None:
        return AIChannelPermissionHealthModel(
            channel_id=str(channel_id),
            purpose=purpose,
            configured=True,
            exists=False,
            ok=False,
            can_send_messages=False,
            can_embed_links=False,
            reason=not_found_reason,
        )
    if bot_user_id is None:
        return AIChannelPermissionHealthModel(
            channel_id=str(channel_id),
            channel_name=channel.get("name"),
            purpose=purpose,
            configured=True,
            exists=True,
            ok=False,
            can_send_messages=False,
            can_embed_links=False,
            reason="Could not resolve the bot member in this server.",
        )

    permissions = _effective_channel_permissions(
        server_id=server_id,
        channel=channel,
        bot_user_id=bot_user_id,
        bot_role_ids=bot_role_ids,
        role_permissions=role_permissions,
    )
    can_view = bool(permissions & VIEW_CHANNEL)
    can_read_history = bool(permissions & READ_MESSAGE_HISTORY)
    can_send = bool(permissions & SEND_MESSAGES)
    can_embed = bool(permissions & EMBED_LINKS)
    ok = can_view and can_send and can_embed
    reason = None if ok else "Bot needs View Channel, Send Messages, and Embed Links permissions."
    return AIChannelPermissionHealthModel(
        channel_id=str(channel_id),
        channel_name=channel.get("name"),
        purpose=purpose,
        configured=True,
        exists=True,
        ok=ok,
        can_view_channel=can_view,
        can_read_message_history=can_read_history,
        can_send_messages=can_send,
        can_embed_links=can_embed,
        reason=reason,
    )


def _channel_map(channels: list[dict]) -> dict[int, dict]:
    payload: dict[int, dict] = {}
    for channel in channels:
        channel_id = _int_or_none(channel.get("id"))
        if channel_id is not None:
            payload[channel_id] = channel
    return payload


def _moderation_channel_ids(server_id: int, settings, channels: list[dict]) -> list[int]:
    if not settings.moderation_enabled or settings.moderation_channel_mode == "none":
        return []
    if settings.moderation_channel_mode == "selected":
        return [int(channel_id) for channel_id in settings.moderation_included_channel_ids or [] if str(channel_id).isdigit()]
    if settings.moderation_channel_mode == "exclude_selected":
        excluded = {str(channel_id) for channel_id in settings.moderation_excluded_channel_ids or []}
        return [
            int(channel["id"])
            for channel in channels
            if _int_or_none(channel.get("id")) is not None
            and channel.get("type") in TEXT_CHANNEL_TYPES
            and str(channel["id"]) not in excluded
            and should_moderate_message_channel(settings, channel_id=int(channel["id"]))
        ]
    return [
        int(channel["id"])
        for channel in channels
        if _int_or_none(channel.get("id")) is not None
        and channel.get("type") in TEXT_CHANNEL_TYPES
        and should_moderate_message_channel(settings, channel_id=int(channel["id"]))
    ]


async def build_ai_settings_health(session: AsyncSession, server_id: int) -> ServerAISettingsHealthModel:
    settings = await get_or_create_server_ai_settings(session, server_id)
    mod_settings = await session.get(ServerModerationSettings, server_id)

    channels = await fetch_guild_channels(server_id)
    roles = await fetch_guild_roles(server_id)
    role_permissions = _role_permission_map(roles)
    channels_by_id = _channel_map(channels)

    bot_user_id = None
    bot_role_ids: set[int] = set()
    bot_user = await fetch_current_bot_user()
    raw_bot_user_id = bot_user.get("id")
    if raw_bot_user_id is not None and str(raw_bot_user_id).isdigit():
        bot_user_id = int(raw_bot_user_id)
        bot_member = await fetch_guild_member(server_id=server_id, user_id=bot_user_id)
        if bot_member:
            bot_role_ids = {int(role_id) for role_id in bot_member.get("roles", []) if str(role_id).isdigit()}

    moderation_health = [
        _read_health(
            server_id=server_id,
            channel_id=channel_id,
            channel=channels_by_id.get(channel_id),
            bot_user_id=bot_user_id,
            bot_role_ids=bot_role_ids,
            role_permissions=role_permissions,
        )
        for channel_id in _moderation_channel_ids(server_id, settings, channels)
    ]

    mod_log_channel_id = mod_settings.mod_log_channel_id if mod_settings else None
    mod_log_health = _write_health(
        server_id=server_id,
        channel_id=mod_log_channel_id,
        channel=channels_by_id.get(mod_log_channel_id) if mod_log_channel_id is not None else None,
        bot_user_id=bot_user_id,
        bot_role_ids=bot_role_ids,
        role_permissions=role_permissions,
    )
    ai_review_channel_id = settings.moderation_review_channel_id or mod_log_channel_id
    ai_review_health = _write_health(
        server_id=server_id,
        channel_id=ai_review_channel_id,
        channel=channels_by_id.get(ai_review_channel_id) if ai_review_channel_id is not None else None,
        bot_user_id=bot_user_id,
        bot_role_ids=bot_role_ids,
        role_permissions=role_permissions,
        purpose="ai_review",
        missing_reason="AI moderation suggestions channel is not configured.",
        not_found_reason="AI moderation suggestions channel was not found in this server.",
    )

    warnings: list[str] = []
    if any(not item.ok for item in moderation_health):
        warnings.append("One or more AI moderation channels are not readable by the bot.")
    if not ai_review_health.ok:
        warnings.append("AI moderation review messages may not be sent because the suggestions channel is not writable.")

    return ServerAISettingsHealthModel(
        server_id=str(server_id),
        ok=not warnings,
        checked_at=_now(),
        moderation_enabled=settings.moderation_enabled,
        moderation_channel_mode=settings.moderation_channel_mode,
        moderation_channels=moderation_health,
        mod_log_channel=mod_log_health,
        ai_review_channel=ai_review_health,
        warnings=warnings,
    )

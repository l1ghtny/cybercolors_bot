from datetime import datetime, timezone

import discord

from src.modules.logs_setup import logger
from src.modules.localization.service import tr

logger = logger.logging.getLogger("bot")


def _truncate(value: str, limit: int = 900) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return f"{value.isoformat()}Z"


async def send_mod_log_message(
    guild: discord.Guild,
    mod_log_channel_id: int | None,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
) -> bool:
    if not mod_log_channel_id:
        return False
    if content is None and embed is None:
        return False

    channel = guild.get_channel(mod_log_channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(mod_log_channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            logger.warning(
                "Cannot resolve moderation log channel %s in guild %s: %s",
                mod_log_channel_id,
                guild.id,
                error,
            )
            return False

    send_method = getattr(channel, "send", None)
    if send_method is None:
        logger.warning(
            "Configured moderation log channel %s in guild %s is not messageable.",
            mod_log_channel_id,
            guild.id,
        )
        return False

    try:
        await send_method(content, embed=embed, allowed_mentions=discord.AllowedMentions.none())
        return True
    except (discord.Forbidden, discord.HTTPException) as error:
        logger.warning(
            "Failed to send moderation log in channel %s (guild %s): %s",
            mod_log_channel_id,
            guild.id,
            error,
        )
        return False


def build_unmute_log_message(
    *,
    target_user_id: int,
    target_display: str,
    moderator_user_id: int | None,
    moderator_display: str | None,
    reason: str,
    removed_role: bool,
    closed_actions: int,
    is_auto: bool = False,
    locale: str | None = None,
) -> str:
    action_name = tr(locale, "modlog.action_auto_unmute") if is_auto else tr(locale, "modlog.action_unmute")
    lines = [
        f"**{tr(locale, 'modlog.action_label')}:** `{action_name}`",
        f"**{tr(locale, 'modlog.target_label')}:** <@{target_user_id}> (`{_truncate(target_display, 120)}`, `{target_user_id}`)",
    ]
    if moderator_user_id is not None:
        lines.append(
            f"**{tr(locale, 'modlog.moderator_label')}:** <@{moderator_user_id}> "
            f"(`{_truncate(moderator_display or tr(locale, 'modlog.unknown'), 120)}`, `{moderator_user_id}`)"
        )
    lines.extend(
        [
            f"**{tr(locale, 'modlog.reason_label')}:** {_truncate(reason, 1000)}",
            f"**{tr(locale, 'modlog.removed_role_label')}:** `{removed_role}`",
            f"**{tr(locale, 'modlog.closed_actions_label')}:** `{closed_actions}`",
            f"**{tr(locale, 'modlog.logged_at_label')}:** `{_format_dt(datetime.now(timezone.utc).replace(tzinfo=None))}`",
        ]
    )
    message = tr(locale, "modlog.header") + "\n" + "\n".join(lines)
    return _truncate(message, 1900)


def build_action_revert_log_embed(
    *,
    server_id: int,
    action_type: str,
    action_id: str,
    action_url: str,
    target_user_id: int,
    target_display: str | None,
    moderator_user_id: int | None,
    moderator_display: str | None,
    reason: str,
    reverted: bool,
    locale: str | None = None,
    is_auto: bool = False,
) -> discord.Embed:
    action_name = tr(locale, "modlog.action_auto_revert") if is_auto else tr(locale, "modlog.action_revert")
    embed = discord.Embed(
        title=f"{tr(locale, 'modlog.title')}: {action_name}",
        url=action_url,
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name=tr(locale, "modlog.target_label"),
        value=f"<@{target_user_id}> (`{_truncate(target_display or tr(locale, 'modlog.unknown'), 120)}`, `{target_user_id}`)",
        inline=True,
    )
    if moderator_user_id is not None:
        embed.add_field(
            name=tr(locale, "modlog.moderator_label"),
            value=f"<@{moderator_user_id}> (`{_truncate(moderator_display or tr(locale, 'modlog.unknown'), 120)}`, `{moderator_user_id}`)",
            inline=True,
        )
    embed.add_field(
        name=tr(locale, "modlog.original_action_label"),
        value=f"[{action_type} #{action_id[:8]}]({action_url})",
        inline=False,
    )
    embed.add_field(name=tr(locale, "modlog.reason_label"), value=_truncate(reason, 1024), inline=False)
    embed.add_field(name=tr(locale, "modlog.reverted_label"), value=f"`{reverted}`", inline=True)
    embed.set_footer(text=f"{tr(locale, 'modlog.action_id_label')}: {action_id} | Server ID: {server_id}")
    return embed


_MONITORING_EVENT_KEYS = {
    "auto_monitor": "modlog.monitoring_event_auto_monitor",
    "rejoin": "modlog.monitoring_event_rejoin",
    "message": "modlog.monitoring_event_message",
    "image": "modlog.monitoring_event_image",
    "voice_join": "modlog.monitoring_event_voice_join",
    "thread_create": "modlog.monitoring_event_thread_create",
    "bot_command": "modlog.monitoring_event_bot_command",
    "ai_interaction": "modlog.monitoring_event_ai_interaction",
}


def _format_monitoring_metadata(metadata: dict | None, locale: str | None = None) -> str:
    if not metadata:
        return tr(locale, "modlog.none")
    lines: list[str] = []
    if metadata.get("reason"):
        lines.append(f"{tr(locale, 'modlog.reason_label')}: {_truncate(str(metadata['reason']), 300)}")
    if metadata.get("message_count"):
        lines.append(
            f"{tr(locale, 'modlog.monitoring_message_count')}: {metadata.get('message_count')} / {metadata.get('threshold')}"
        )
    if metadata.get("command_name"):
        lines.append(f"{tr(locale, 'modlog.monitoring_command')}: `/{metadata.get('command_name')}`")
    if metadata.get("channel_name"):
        lines.append(f"{tr(locale, 'modlog.channel_label')}: {_truncate(str(metadata.get('channel_name')), 120)}")
    if metadata.get("thread_name"):
        lines.append(f"{tr(locale, 'modlog.monitoring_thread')}: {_truncate(str(metadata.get('thread_name')), 120)}")
    attachments = metadata.get("attachments") or []
    if attachments:
        names = [item.get("filename") for item in attachments if item.get("filename")]
        if names:
            lines.append(f"{tr(locale, 'modlog.monitoring_attachments')}: {_truncate(', '.join(names), 300)}")
    if metadata.get("jump_url"):
        lines.append(f"{tr(locale, 'modlog.source_label')}: [Discord]({metadata.get('jump_url')})")
    return "\n".join(lines) if lines else tr(locale, "modlog.none")


def build_monitoring_activity_log_embed(
    *,
    server_id: int,
    event_type: str,
    user_id: int,
    user_display: str | None,
    channel_id: int | None,
    message_id: int | None,
    message_content: str | None,
    metadata: dict | None,
    locale: str | None = None,
) -> discord.Embed:
    event_label = tr(locale, _MONITORING_EVENT_KEYS.get(event_type, "modlog.monitoring_event_unknown"))
    embed = discord.Embed(
        title=f"{tr(locale, 'modlog.monitoring_title')}: {event_label}",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name=tr(locale, "modlog.target_label"),
        value=f"<@{user_id}> (`{_truncate(user_display or tr(locale, 'modlog.unknown'), 120)}`, `{user_id}`)",
        inline=False,
    )
    if channel_id is not None:
        embed.add_field(name=tr(locale, "modlog.channel_label"), value=f"<#{channel_id}> (`{channel_id}`)", inline=True)
    if message_id is not None:
        embed.add_field(name=tr(locale, "modlog.message_label"), value=f"`{message_id}`", inline=True)
    if message_content:
        embed.add_field(
            name=tr(locale, "modlog.message_content_label"),
            value=_truncate(message_content, 1024),
            inline=False,
        )
    embed.add_field(
        name=tr(locale, "modlog.details_label"),
        value=_truncate(_format_monitoring_metadata(metadata, locale), 1024),
        inline=False,
    )
    embed.set_footer(text=f"{tr(locale, 'modlog.server_id_label')}: {server_id}")
    return embed

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
    content: str,
) -> bool:
    if not mod_log_channel_id:
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
        await send_method(content, allowed_mentions=discord.AllowedMentions.none())
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

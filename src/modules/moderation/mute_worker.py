import discord

from src.db.database import get_async_session
from src.db.models import ServerModerationSettings
from src.modules.logs_setup import logger
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.mod_log import build_unmute_log_message, send_mod_log_message
from src.modules.moderation.mute_management import get_expired_active_mutes

logger = logger.logging.getLogger("bot")


async def process_expired_mutes(client: discord.Client) -> tuple[int, int]:
    """
    Removes mute role for expired mute actions.
    Returns (processed_count, failed_count).
    """
    processed = 0
    failed = 0
    locale_cache: dict[int, str] = {}

    async with get_async_session() as session:
        expired_actions = await get_expired_active_mutes(session, limit=500)
        if not expired_actions:
            return processed, failed

        for action in expired_actions:
            guild = client.get_guild(action.server_id)
            if guild is None:
                action.is_active = False
                session.add(action)
                processed += 1
                continue

            settings = await session.get(ServerModerationSettings, action.server_id)
            if not settings or not settings.mute_role_id:
                action.is_active = False
                session.add(action)
                processed += 1
                continue

            mute_role = guild.get_role(settings.mute_role_id)
            if mute_role is None:
                action.is_active = False
                session.add(action)
                processed += 1
                continue

            member = guild.get_member(action.target_user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(action.target_user_id)
                except discord.NotFound:
                    member = None
                except discord.HTTPException as error:
                    logger.warning("Failed fetching member %s in guild %s: %s", action.target_user_id, guild.id, error)

            if member and mute_role in member.roles:
                try:
                    await member.remove_roles(
                        mute_role,
                        reason=f"Auto-unmute: mute action {action.id} expired",
                    )
                except (discord.Forbidden, discord.HTTPException) as error:
                    failed += 1
                    logger.warning("Auto-unmute failed for member %s in guild %s: %s", action.target_user_id, guild.id, error)
                    continue
                removed_role = True
            else:
                removed_role = False

            action.is_active = False
            session.add(action)
            processed += 1

            if settings.mod_log_channel_id:
                locale = locale_cache.get(action.server_id)
                if locale is None:
                    locale = await get_server_locale(action.server_id)
                    locale_cache[action.server_id] = locale
                content = build_unmute_log_message(
                    target_user_id=action.target_user_id,
                    target_display=member.display_name if member else str(action.target_user_id),
                    moderator_user_id=None,
                    moderator_display=None,
                    reason=tr(locale, "modlog.reason_mute_expired"),
                    removed_role=removed_role,
                    closed_actions=1,
                    is_auto=True,
                    locale=locale,
                )
                await send_mod_log_message(
                    guild=guild,
                    mod_log_channel_id=settings.mod_log_channel_id,
                    content=content,
                )

        await session.commit()

    return processed, failed

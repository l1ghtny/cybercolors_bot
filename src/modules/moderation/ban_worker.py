import discord

from api.services.moderation_actions_service import _dashboard_action_url
from src.db.database import get_async_session
from src.db.models import GlobalUser, ServerModerationSettings
from src.modules.logs_setup import logger
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.mod_log import build_action_revert_log_embed, send_mod_log_message
from src.modules.moderation.mute_management import get_expired_active_bans

logger = logger.logging.getLogger("bot")


async def process_expired_bans(client: discord.Client) -> tuple[int, int]:
    """Unbans users for expired native Discord ban actions."""
    processed = 0
    failed = 0
    locale_cache: dict[int, str] = {}

    async with get_async_session() as session:
        expired_actions = await get_expired_active_bans(session, limit=500)
        if not expired_actions:
            return processed, failed

        for action in expired_actions:
            guild = client.get_guild(action.server_id)
            if guild is None:
                action.is_active = False
                session.add(action)
                processed += 1
                continue

            try:
                await guild.unban(
                    discord.Object(id=action.target_user_id),
                    reason=f"Auto-unban: ban action {action.id} expired",
                )
                reverted = True
            except discord.NotFound:
                reverted = False
            except (discord.Forbidden, discord.HTTPException) as error:
                failed += 1
                logger.warning("Auto-unban failed for user %s in guild %s: %s", action.target_user_id, guild.id, error)
                continue

            action.is_active = False
            session.add(action)
            processed += 1

            settings = await session.get(ServerModerationSettings, action.server_id)
            if settings and settings.mod_log_channel_id:
                locale = locale_cache.get(action.server_id)
                if locale is None:
                    locale = await get_server_locale(action.server_id)
                    locale_cache[action.server_id] = locale
                target = await session.get(GlobalUser, action.target_user_id)
                embed = build_action_revert_log_embed(
                    server_id=action.server_id,
                    action_type="ban",
                    action_id=str(action.id),
                    action_url=_dashboard_action_url(action.server_id, action.id),
                    target_user_id=action.target_user_id,
                    target_display=target.username if target else None,
                    moderator_user_id=None,
                    moderator_display=None,
                    reason=tr(locale, "modlog.reason_ban_expired"),
                    reverted=reverted,
                    locale=locale,
                    is_auto=True,
                )
                await send_mod_log_message(
                    guild=guild,
                    mod_log_channel_id=settings.mod_log_channel_id,
                    embed=embed,
                )

        await session.commit()

    return processed, failed

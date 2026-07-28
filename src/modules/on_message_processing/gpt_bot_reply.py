import discord

from src.modules.chat_bot.create_response import AIAnswerTimeoutError
from src.modules.chat_bot.message_processing import check_bot_mention, check_for_channel, decide_on_response
from src.modules.localization.service import get_server_locale, tr
from src.modules.logs_setup import logger
from src.modules.monitoring.activity import record_ai_conversation_activity

logger = logger.logging.getLogger("bot")

NO_AI_MENTIONS = discord.AllowedMentions.none()


async def look_for_bot_reply(message, client):
    if await check_bot_mention(message, client) is not True:
        return

    is_approved, _approved_channel = await check_for_channel(message, client)
    if not is_approved:
        return

    try:
        await record_ai_conversation_activity(message)
    except Exception:
        logger.exception(
            "Failed to record AI conversation activity in guild %s channel %s message %s",
            getattr(getattr(message, "guild", None), "id", None),
            getattr(getattr(message, "channel", None), "id", None),
            getattr(message, "id", None),
        )
    locale = await _message_locale(message)
    if "jailbreak" in (message.content or "").lower():
        await message.reply(tr(locale, "ai_reply.jailbreak"), allowed_mentions=NO_AI_MENTIONS)
        return

    logger.info(
        "Requesting AI reply in guild %s channel %s message %s",
        getattr(getattr(message, "guild", None), "id", None),
        getattr(getattr(message, "channel", None), "id", None),
        getattr(message, "id", None),
    )
    try:
        async with message.channel.typing():
            bot_response, token_total = await decide_on_response(message, client, locale=locale)
    except AIAnswerTimeoutError:
        logger.warning(
            "AI answer timed out in guild %s channel %s message %s",
            getattr(getattr(message, "guild", None), "id", None),
            getattr(getattr(message, "channel", None), "id", None),
            getattr(message, "id", None),
        )
        await _send_ai_reply_safely(message, tr(locale, "ai_reply.timeout"), locale=locale)
        return
    except Exception:
        logger.exception(
            "AI answer failed in guild %s channel %s message %s",
            getattr(getattr(message, "guild", None), "id", None),
            getattr(getattr(message, "channel", None), "id", None),
            getattr(message, "id", None),
        )
        await _send_ai_reply_safely(message, tr(locale, "ai_reply.failure"), locale=locale)
        return

    if bot_response is None:
        await _send_ai_reply_safely(message, tr(locale, "ai_reply.provider_unavailable"), locale=locale)
        return

    logger.info(
        "got AI response in guild %s channel %s message %s tokens=%s",
        getattr(getattr(message, "guild", None), "id", None),
        getattr(getattr(message, "channel", None), "id", None),
        getattr(message, "id", None),
        token_total,
    )
    await _send_ai_reply_safely(message, bot_response, locale=locale)


async def _message_locale(message) -> str:
    guild_id = getattr(getattr(message, "guild", None), "id", None)
    if guild_id is None:
        return "en"
    try:
        return await get_server_locale(int(guild_id))
    except Exception:
        logger.exception("Failed to load server locale for guild %s", guild_id)
        return "en"


async def _send_ai_reply_safely(message, content: str, *, locale: str | None = None) -> None:
    try:
        await message.reply(content, allowed_mentions=NO_AI_MENTIONS)
    except discord.HTTPException:
        embed = discord.Embed(
            colour=discord.Colour.dark_blue(),
            description=(content or "")[:4000],
            title=tr(locale, "ai_reply.long_answer_title"),
        )
        logger.info("SENDING EMBED")
        await message.reply(embed=embed, allowed_mentions=NO_AI_MENTIONS)

import discord

from src.modules.chat_bot.create_response import AIAnswerTimeoutError
from src.modules.chat_bot.message_processing import check_bot_mention, check_for_channel, decide_on_response
from src.modules.localization.service import get_server_locale, tr
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")

NO_AI_MENTIONS = discord.AllowedMentions.none()


async def look_for_bot_reply(message, client):
    if await check_bot_mention(message, client) is not True:
        return

    is_approved, _approved_channel = await check_for_channel(message, client)
    if not is_approved:
        return

    locale = await _message_locale(message)
    if "jailbreak" in (message.content or "").lower():
        await message.reply(tr(locale, "ai_reply.jailbreak"), allowed_mentions=NO_AI_MENTIONS)
        return

    original_reply = await message.reply(tr(locale, "ai_reply.thinking"), allowed_mentions=NO_AI_MENTIONS)
    logger.info("looking for AI reply to %s", message.content)
    try:
        bot_response, token_total = await decide_on_response(message, client, locale=locale)
    except AIAnswerTimeoutError:
        logger.warning(
            "AI answer timed out in guild %s channel %s message %s",
            getattr(getattr(message, "guild", None), "id", None),
            getattr(getattr(message, "channel", None), "id", None),
            getattr(message, "id", None),
        )
        await _edit_ai_reply_safely(original_reply, tr(locale, "ai_reply.timeout"), locale=locale)
        return
    except Exception:
        logger.exception(
            "AI answer failed in guild %s channel %s message %s",
            getattr(getattr(message, "guild", None), "id", None),
            getattr(getattr(message, "channel", None), "id", None),
            getattr(message, "id", None),
        )
        await _edit_ai_reply_safely(original_reply, tr(locale, "ai_reply.failure"), locale=locale)
        return

    if bot_response is None:
        await _edit_ai_reply_safely(original_reply, tr(locale, "ai_reply.provider_unavailable"), locale=locale)
        return

    logger.info(
        "got AI response in guild %s channel %s message %s tokens=%s",
        getattr(getattr(message, "guild", None), "id", None),
        getattr(getattr(message, "channel", None), "id", None),
        getattr(message, "id", None),
        token_total,
    )
    await _edit_ai_reply_safely(original_reply, bot_response, locale=locale)


async def _message_locale(message) -> str:
    guild_id = getattr(getattr(message, "guild", None), "id", None)
    if guild_id is None:
        return "en"
    try:
        return await get_server_locale(int(guild_id))
    except Exception:
        logger.exception("Failed to load server locale for guild %s", guild_id)
        return "en"


async def _edit_ai_reply_safely(original_reply, content: str, *, locale: str | None = None) -> None:
    try:
        await original_reply.edit(content=content, allowed_mentions=NO_AI_MENTIONS)
    except discord.HTTPException:
        embed = discord.Embed(
            colour=discord.Colour.dark_blue(),
            description=(content or "")[:4000],
            title=tr(locale, "ai_reply.long_answer_title"),
        )
        logger.info("SENDING EMBED")
        await original_reply.edit(embed=embed, content=None, allowed_mentions=NO_AI_MENTIONS)

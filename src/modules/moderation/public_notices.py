import discord

from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def send_public_action_notice(interaction: discord.Interaction, content: str) -> bool:
    """Post a moderation action notice in the channel where the command was invoked."""
    channel = interaction.channel
    send_method = getattr(channel, "send", None)
    if send_method is None:
        return False

    try:
        await send_method(content, allowed_mentions=discord.AllowedMentions.none())
        return True
    except (discord.Forbidden, discord.HTTPException) as error:
        guild_id = interaction.guild.id if interaction.guild else None
        channel_id = getattr(channel, "id", None)
        logger.warning(
            "Failed to send public moderation notice in guild %s channel %s: %s",
            guild_id,
            channel_id,
            error,
        )
        return False
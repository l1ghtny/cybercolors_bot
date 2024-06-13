from modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def delete_server_links(message, message_lower):
    if 'https://discord.gg/' in message_lower:
        await message.reply(f'{message.author.mention}, вообще-то постить ссылки на другие сервера у нас запрещено. БОНК')
        await message.delete()


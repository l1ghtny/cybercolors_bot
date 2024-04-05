import datetime

import discord

from modules.chat_bot.message_processing import check_bot_mention, check_for_channel, decide_on_response
from modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def look_for_bot_reply(message, client, server_id, cursor, conn):
    if check_bot_mention(message, client) is True:
        is_approved, approved_channel = check_for_channel(message, client)
        if is_approved:
            if "jailbreak" in message.content.lower():
                await message.reply('В боте стоит защита от jailbreak, я сейчас админа позову')
            else:
                original_reply = await message.reply('Я думаю...')
                logger.info('looking for reply to %s', f'{message.content}')
                bot_response, token_total = await decide_on_response(message, client)
                if bot_response is not None:
                    logger.info('got response')
                    try:
                        await original_reply.edit(content=bot_response)
                    except discord.HTTPException:
                        embed = discord.Embed(colour=discord.Colour.dark_blue(), description=bot_response,
                                              title="Длинный ответ:")
                        logger.info('SENDING EMBED')
                        await original_reply.edit(embed=embed, content=None)
                else:
                    await original_reply.edit(content='***Ошибка:*** Open AI сейчас не доступен, попробуй ещё раз')
                query = 'INSERT INTO "public".count_tokens (datetime_added, reply_link, token_amount, server_id) VALUES (%s,%s,%s,%s)'
                current_time = datetime.datetime.utcnow()
                values = (current_time, message.jump_url, token_total, server_id,)
                cursor.execute(query, values)
                conn.commit()
        else:
            return
    conn.close()

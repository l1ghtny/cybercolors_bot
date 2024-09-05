import datetime
import random

import discord
import requests

from src.misc_files import basevariables
# from modules.error_handling.error_notification import send_error_message
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def check_birthday_new(client):
    key = basevariables.t_key
    list_timezones = await get_all_timezones(key)
    zones = list_timezones['zones']
    if list_timezones['status'] == 'OK':
        conn, cursor = await basevariables.access_db_regular()
        query = 'SELECT * from "public".users as users inner join "public".servers as servers using(server_id)'
        cursor.execute(query)
        values = cursor.fetchall()
        conn.close()
        for item in values:
            guild_id = item['server_id']
            guild_role_id = item['role_id']
            logger.info(f'guild_role_id: {guild_role_id}')
            guild = client.get_guild(guild_id)
            guild_role = discord.utils.get(guild.roles, id=guild_role_id)
            logger.info(f'guild_role: {guild_role.name}')
            user_id = item['user_id']
            user_timezone_name = item['timezone']
            user = client.get_user(user_id)
            member = guild.get_member(user_id)
            if member is not None:
                if user_timezone_name is not None:
                    user_time = await get_user_time(user_timezone_name, zones)
                    formatted = user_time
                    today = datetime.date.today()
                    t_year = today.year
                    table_month = item['month']
                    table_day = item['day']
                    bd_date = datetime.datetime(t_year, table_month, table_day, hour=0, minute=0)
                    json_date = datetime.datetime.fromtimestamp(formatted, datetime.timezone.utc)
                    json_date_from_timestamp = datetime.datetime.utcnow()
                    channel_id = item['channel_id']
                    channel = client.get_channel(channel_id)
                    logger.info(f'{user.name} др: {bd_date}')
                    logger.info(f'{user.name} проверено в: {json_date}')
                    logger.info(f'{user.name} дата по timestamp: {json_date_from_timestamp}')
                    if json_date.date() == bd_date.date() and json_date.hour == bd_date.hour:
                        conn, cursor = await basevariables.access_db_regular()
                        query2 = 'SELECT * from "public".congratulations where server_id=%s'
                        values2 = (guild_id,)
                        cursor.execute(query2, values2)
                        greetings = cursor.fetchall()
                        greetings_text = []
                        for rows in greetings:
                            greetings_text.append(rows['bot_message'])
                        message_text = random.choice(greetings_text)
                        embed_description = eval(f'{message_text}')
                        embed = discord.Embed(colour=discord.Colour.dark_gold(), description=embed_description)
                        await channel.send(embed=embed)
                        query3 = 'UPDATE "public".users SET role_added_at=%s WHERE user_id=%s AND server_id=%s'
                        current_time = datetime.datetime.utcnow()
                        values3 = (current_time, user_id, guild_id,)
                        cursor.execute(query3, values3)
                        conn.commit()
                        conn.close()
                        await member.add_roles(guild_role)
                        logger.info('dr')
                        logger.info('  ')
                    else:
                        logger.info('ne dr')
                        logger.info('  ')
                else:
                    logger.info(f'{user_id} не указал свой часовой пояс, проверить невозможно')
                    logger.info('  ')
            else:
                logger.info(f'{user_id} is not a member of the server "{guild.name}"')
                logger.info('  ')
        logger.info('the end')
    else:
        logger.error('TimezoneDB returned not OK')
        message = 'TimezoneDB returned not OK'
        module = 'birthdays'
        # await send_error_message(client, message, module)


async def get_all_timezones(key):
    request = f'http://api.timezonedb.com/v2.1/list-time-zone?key={key}&format=json'
    response = requests.get(request).json()
    return response


async def get_user_time(timezone, zones):
    for item in zones:
        if item['zoneName'] == timezone:
            return item['timestamp']

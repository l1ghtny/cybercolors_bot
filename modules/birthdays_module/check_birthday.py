import datetime
import random

import discord
import requests

from misc_files import basevariables
from misc_files.blocking_script import run_blocking
from modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def check_birthday(client):
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
        user = client.get_user(user_id)
        member = guild.get_member(user_id)
        if member is not None:
            if item['timezone'] is not None:
                key = basevariables.t_key
                timezone = item['timezone']
                response = await run_blocking(client, current_user_datetime, key, timezone)
                time_json = response.json()
                not_formatted = time_json['timestamp']
                formatted = time_json['formatted']
                today = datetime.date.today()
                t_year = today.year
                table_month = item['month']
                table_day = item['day']
                bd_date = datetime.datetime(t_year, table_month, table_day, hour=0, minute=0)
                json_date = datetime.datetime.fromisoformat(formatted)
                json_date_from_timestamp = datetime.datetime.utcfromtimestamp(not_formatted)
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
                else:
                    logger.info('ne dr')
            else:
                logger.info(f'{user_id} не указал свой часовой пояс, проверить невозможно')
        else:
            logger.info(f'{user_id} is not a member of the server "{guild.name}"')
    logger.info('the end')


def current_user_datetime(key, timezone):
    request = f'http://vip.timezonedb.com/v2.1/get-time-zone?key={key}&format=json&by=zone&zone={timezone}'
    response = requests.get(request)
    return response

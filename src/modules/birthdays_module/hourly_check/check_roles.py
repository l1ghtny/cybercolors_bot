import datetime

import discord

from src.misc_files import basevariables
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def check_roles(client):
    conn, cursor = await basevariables.access_db_regular()
    query_last = 'SELECT * from "public".users inner join "public".servers using(server_id)'
    cursor.execute(query_last)
    users_check_roles = cursor.fetchall()
    for i in users_check_roles:
        role_time = i['role_added_at']
        role_guild_id = i['server_id']
        role_user_id = i['user_id']
        server_role_id = i['role_id']
        if role_time is not None:
            user_id = i['user_id']
            user = client.get_user(user_id)
            current_time_now = datetime.datetime.utcnow()
            timedelta = current_time_now - role_time
            current_guild = client.get_guild(role_guild_id)
            current_member = current_guild.get_member(role_user_id)
            current_role = discord.utils.get(current_guild.roles, id=server_role_id)
            logger.info(f'timedelta in days: {timedelta.days}')
            if timedelta.days >= 1:
                logger.info('checked role is older than 1 day')
                await current_member.remove_roles(current_role)
                query_last_for_sure = 'UPDATE "public".users SET role_added_at=%s WHERE server_id=%s AND user_id=%s'
                role_added_at = None
                values_last = (role_added_at, role_guild_id, role_user_id,)
                cursor.execute(query_last_for_sure, values_last)
                conn.commit()
                logger.info(f'role removed from user {user.name}')
            else:
                logger.info(f'role {current_role.name} on user {user.name} is not older than 1 day')
        else:
            logger.info('no role is given')
    conn.close()

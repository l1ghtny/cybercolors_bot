from src.misc_files import basevariables
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def create_voice_channel(member, before, after):
    conn, cursor = await basevariables.access_db_basic()
    query = 'SELECT * from "public".voice_temp WHERE server_id=%s'
    server_id = member.guild.id
    values = (server_id,)
    cursor.execute(query, values)
    temp_channels_info = cursor.fetchall()
    temp_channels = []
    for i in temp_channels_info:
        temp_channels.append(i['voice_channel_id'])
    logger.info(temp_channels)

    possible_channel_name = f"Канал имени {member.display_name}"
    if after.channel:
        if after.channel.id == 1099061215801639073:
            temp_channel = await after.channel.clone(name=possible_channel_name)
            await member.move_to(temp_channel)
            query2 = 'INSERT into "public".voice_temp (server_id, voice_channel_id) values (%s,%s)'
            values2 = (server_id, temp_channel.id,)
            cursor.execute(query2, values2)
            conn.commit()
            logger.info('Temp voice channel created')

    if before.channel:
        if before.channel.id in temp_channels:
            if len(before.channel.members) == 0:
                await before.channel.delete()
                await basevariables.delete_channel_id(before.channel.id, server_id, conn, cursor)
                logger.info('Temp voice channel deleted')
    conn.close()

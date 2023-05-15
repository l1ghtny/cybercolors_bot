from misc_files import basevariables


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

    possible_channel_name = f"Канал имени {member.display_name}"
    if after.channel:
        if after.channel.id == 1099044684116017222:
            temp_channel = await after.channel.clone(name=possible_channel_name)
            await member.move_to(temp_channel)
            query2 = 'INSERT into "public".voice_temp (server_id, voice_channel_id) values (%s,%s)'
            values2 = (server_id, temp_channel.id,)
            cursor.execute(query2, values2)
            conn.commit()

    if before.channel:
        if before.channel.id in temp_channels:
            if len(before.channel.members) == 0:
                await before.channel.delete()
                await basevariables.delete_channel_id(before.channel.id, server_id, conn, cursor)
    conn.close()

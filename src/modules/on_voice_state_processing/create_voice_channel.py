from sqlmodel import select

from src.db.database import get_session
from src.db.models import VoiceChannel
from src.misc_files import basevariables
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def create_voice_channel(member, before, after):
    server_id = member.guild.id
    async with get_session() as session:
        temp_channels_info = await session.exec(select(VoiceChannel).where(VoiceChannel.server_id == member.guild.id)).all()

        temp_channels = []
        for i in temp_channels_info:
            temp_channels.append(i.voice_channel_id)
        logger.info(f'Temp Channels operational: {temp_channels}')

        possible_channel_name = f"Канал имени {member.display_name}"
        if after.channel:
            if after.channel.id == 1099061215801639073:
                temp_channel = await after.channel.clone(name=possible_channel_name)
                await member.move_to(temp_channel)
                new_channel = VoiceChannel(server_id=server_id, channel_id=temp_channel.id)
                session.add(new_channel)
                await session.commit()
                logger.info('Temp voice channel created')

        if before.channel:
            if before.channel.id in temp_channels:
                if len(before.channel.members) == 0:
                    await before.channel.delete()
                    await basevariables.delete_channel_id(before.channel.id, server_id)
                    logger.info('Temp voice channel deleted')

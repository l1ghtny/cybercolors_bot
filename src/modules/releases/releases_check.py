import discord

from src.misc_files import github_api
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def check_new_releases(client):
    channel_id = 1068896806156632084
    sanya_channel_id = 1099032346507890748
    # zds_guild_id = 478278763239702538
    release_date, release_title, release_text = await github_api.get_release_notes()
    if release_title is not None and release_text is not None and release_date is not None:
        channel = client.get_channel(channel_id)
        channel_main = client.get_channel(sanya_channel_id)
        embed = discord.Embed(
            title=f'{release_title}',
            colour=discord.Colour.from_rgb(3, 144, 252)
        )
        embed.add_field(name='Описание релиза', value=f'{release_text}')
        embed.add_field(name='Дата релиза (Мск):', value=f'{release_date}')
        await channel.send(embed=embed)
        await channel_main.send(embed=embed)
    else:
        logger.info('No new releases')

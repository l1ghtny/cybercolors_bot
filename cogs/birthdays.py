import discord
from discord import app_commands
from discord.ext import commands
import main
import basevariables

tree = app_commands.CommandTree(main.client)


class Cog1(commands.Cog):
    def __init__(self, client: main.client):
        self.client = client


# Here we should have a way to import commands to the main file. However, for now I haven't found a way to do that
# on discord.py 2.0 with client defines as a class


async def setup(client: discord.Client) -> None:
    await client.add_cog(Cog1(client))

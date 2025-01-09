import os

import discord
from dotenv import load_dotenv

load_dotenv()

async def check_roles(interaction: discord.Interaction):
    required_role_ids_str = os.getenv('required_role_ids')
    required_role_ids = [int(role_id) for role_id in required_role_ids_str.split(',')]
    for role_id in required_role_ids:
        if any(role.id == role_id for role in interaction.user.roles):
            return True
    return False
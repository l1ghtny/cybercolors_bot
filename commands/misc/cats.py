import os
import shutil

import requests
import random
import string
import discord
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import io
from io import BytesIO


async def get_a_cat():
    r = requests.get(url='https://cataas.com/cat', stream=True)
    name = random.choice(string.ascii_lowercase)
    fp = open(f'{name}.png', 'wb')
    fp.write(r.content)
    fp.close()
    return name


async def cat_command(interaction):
    name = await get_a_cat()
    await interaction.response.send_message(file=discord.File(fp=f"{name}.png", filename="cat.png"))
    os.remove(f'{name}.png')





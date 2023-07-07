import os

import discord
import requests
import json
from dotenv import load_dotenv
from midjourney_api import TNL

from modules.image_generation.midjourney_misc import get_image_new
from modules.logs_setup import logger

logger = logger.logging.getLogger("bot")

load_dotenv()


class ProgrammableButton(discord.ui.Button['Midjourney']):
    def __init__(self, button_name, button_message_id, current_message):
        super().__init__(style=discord.ButtonStyle.green, label=button_name)
        self.name = button_name
        self.id = button_message_id
        self.message = current_message

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        token = os.getenv("midjourney_token")
        tnl = TNL(token)

        response = tnl.button(button=self.name, button_message_id=self.id)
        message_id = response['messageId']
        print('updating the message')
        await update_message(self.message, message_id)


async def update_message(message, message_id):
    image_url, buttons, button_message_id, prompt, description = await get_image_new(message, message_id)
    view = MidjourneyButtonsView(button_message_id, message, buttons)
    await message.edit(content=f'Ссылка на изображение: {image_url}', embed=None, view=view)


class MidjourneyButtonsView(discord.ui.View):

    def __init__(self, button_message_id, current_message, buttons):
        super().__init__(timeout=None)
        self.id = button_message_id
        self.message = current_message
        self.buttons = buttons

        for item in self.buttons:
            if item == "Web":
                print(f'{item} - does not match')
            elif item == "🔍 Custom Zoom":
                print(f'{item} - does not match')
            else:
                self.add_item(ProgrammableButton(item, self.id, self.message))

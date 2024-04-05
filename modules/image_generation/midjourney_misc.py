import asyncio
import os
import time

from dotenv import load_dotenv
import requests
import discord

from modules.logs_setup import logger

logger = logger.logging.getLogger("bot")

load_dotenv()


async def get_image_status_new(message_id):
    token = os.getenv("midjourney_token")
    tnl = TNL(token)

    try:
        response = tnl.get_message_and_progress(message_id, expire_mins=12)
        progress = response
    except requests.exceptions.JSONDecodeError:
        progress = None
    print(progress)
    return progress


async def get_image_new(message, message_id):
    while await get_image_status_new(message_id) is None:
        print(f'id:{message_id}, No progress, retrying in 5')
        await asyncio.sleep(5)
    while "response" not in (progress := await get_image_status_new(message_id)) or progress['progress'] < 100:
        if "progressImageUrl" not in progress:
            progress_bar = progress['progress']
            print('current progress:', progress_bar, 'message_id:', message_id)
            await message.edit(content=f'Текущий прогресс = {progress_bar}%', view=None)
            await asyncio.sleep(5)
        elif progress['progress'] == "incomplete":
            image_url = None
            buttons = None
            button_message_id = None
            prompt = 'Incomplete'
            description = None
            return image_url, buttons, button_message_id, prompt, description
        else:
            progress_bar = progress['progress']
            link = progress["progressImageUrl"]
            await message.edit(content=f'Текущий прогресс: {progress_bar}%. Картинка в прогрессе: {link}', view=None)
            await asyncio.sleep(5)
    else:
        token = os.getenv("midjourney_token")
        tnl = TNL(token)

        response = tnl.get_message_and_progress(message_id=message_id, expire_mins=12)
        image_urls = response['response']["imageUrls"]
        description = response['response']['description']
        image_url = response['response']['imageUrl']
        prompt = response['response']['content']
        buttons = response['response']['buttons']
        button_message_id = response['response']['buttonMessageId']
        return image_url, buttons, button_message_id, prompt, description

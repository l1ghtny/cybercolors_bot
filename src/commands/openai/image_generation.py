import os
import requests
from dotenv import load_dotenv

from src.modules.image_generation.midjourney_misc import get_image_new
from src.modules.logs_setup import logger
from src.views.midjourney.image_buttons import MidjourneyButtonsView

logger = logger.logging.getLogger("bot")

load_dotenv()


async def midjourney_settings(interaction):
    token = os.getenv("midjourney_token")
    await interaction.response.defer(thinking=True)
    url = "https://api.thenextleg.io/v2/settings"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    response = requests.request("GET", url, headers=headers).json()
    print(response)
    if 'success' in response:
        message = await interaction.followup.send('Всё успешно отправлено, ждём ответа')
        message_id = response['messageId']
        image_url, buttons, button_message_id, prompt = await get_image_new(message, message_id)
        view = MidjourneyButtonsView(button_message_id, message, buttons, interaction.user)
        await message.edit(content=f'Ссылка на общий план: {image_url} \n Запрос: {prompt}', embed=None, view=view)

    elif 'isNaughty' in response:
        phrase = response['phrase']
        await interaction.followup.send(
            f'{interaction.user.mention}, бот считает, что ты хорни, веди себя прилично \n Ему не понравилось: "{phrase}"')
    else:
        await interaction.followup.send(
            'Чет сломалось, хер его знает, пока что обработку ошибок я не настраивал')


async def new_image(interaction, prompt):
    await interaction.response.defer(thinking=True)
    token = os.getenv("midjourney_token")
    tnl = TNL(token)
    response = tnl.imagine(prompt=prompt)

    if 'success' in response:
        if response['success'] is True:
            message = await interaction.followup.send('Всё успешно отправлено, ждём ответа')
            message_id = response['messageId']
            image_url, buttons, button_message_id, prompt, description = await get_image_new(message, message_id)
            view = MidjourneyButtonsView(button_message_id, message, buttons, interaction.user)
            await message.edit(content=f'Ссылка на общий план: {image_url} \n Запрос: {prompt}', embed=None, view=view)

    elif 'isNaughty' in response:
        phrase = response['phrase']
        await interaction.followup.send(
            f'{interaction.user.mention}, бот считает, что ты хочешь чего-то нехорошего, веди себя прилично \n Ему не понравилось: "{phrase}"')
    else:
        await interaction.followup.send(
            'Чет сломалось, хер его знает, пока что обработку ошибок я не настраивал')


async def image_2_image(interaction, prompt, image_link):
    await interaction.response.defer(thinking=True)
    token = os.getenv("midjourney_token")
    tnl = TNL(token)
    response = tnl.img2img(prompt, image_link)

    if response['success'] is True:
        message = await interaction.followup.send('Всё успешно отправлено, ждём ответа')
        message_id = response['messageId']
        image_url, buttons, button_message_id, prompt, description = await get_image_new(message, message_id)
        view = MidjourneyButtonsView(button_message_id, message, buttons, interaction.user)
        if description is None:
            await message.edit(content=f'Ссылка на общий план: {image_url} \n Запрос: {prompt}', embed=None, view=view)
        else:
            await message.edit(content=f'Ссылка на общий план: {image_url} \n Запрос: {prompt} \n Ответ от Midjourney:', embed=None, view=view)

    elif 'isNaughty' in response:
        phrase = response['phrase']
        await interaction.followup.send(
            f'{interaction.user.mention}, бот считает, что ты хорни, веди себя прилично \n Ему не понравилось: "{phrase}"')
    else:
        await interaction.followup.send(
            'Чет сломалось, хер его знает, пока что обработку ошибок я не настраивал')


import os
from io import BytesIO

import openai
from dotenv import load_dotenv
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")

load_dotenv()
openai.organization = "org-dTq0wzkkXgmTQ1GIDabM4fva"
openai.api_key = os.getenv("OPENAI_API_KEY")


def create_image(prompt):
    response = openai.Image.create(
        prompt=prompt,
        n=1,
        size='1024x1024'
    )
    return response


async def one_image_generation(prompt):
    response = create_image(prompt)
    image = response['data'][0]['url']
    return image


def create_variation(image):
    response = openai.Image.create_variation(
        image=image,
        n=1,
        size='1024x1024'
    )
    return response


async def one_variation_create(image):
    byte_stream = BytesIO()
    image.save(byte_stream, format='PNG')
    byte_array = byte_stream.getvalue()
    response = create_variation(byte_array)
    image = response['data'][0]['url']
    return image

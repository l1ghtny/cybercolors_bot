from __future__ import annotations

import io
import logging
from urllib.parse import quote

import aiohttp
import discord

logger = logging.getLogger(__name__)

CATAAS_BASE_URL = "https://cataas.com"
CAT_FETCH_ATTEMPTS = 3
CAT_FETCH_TIMEOUT_SECONDS = 10
CAT_UNAVAILABLE_MESSAGE = "Не удалось загрузить котика. Попробуйте ещё раз чуть позже."


class CatImageUnavailable(RuntimeError):
    """Raised when CATAAS does not return a valid image."""


def _image_filename(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "cat.jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "cat.png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "cat.gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "cat.webp"
    return None


async def _fetch_cat_image(text: str | None = None) -> discord.File:
    url = f"{CATAAS_BASE_URL}/cat"
    params = None
    if text is not None:
        url = f"{url}/says/{quote(text, safe='')}"
        params = {"fontColor": "#FFFFFF"}

    timeout = aiohttp.ClientTimeout(total=CAT_FETCH_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout, headers={"Accept": "image/*"}) as session:
        for attempt in range(1, CAT_FETCH_ATTEMPTS + 1):
            try:
                async with session.get(url, params=params) as response:
                    data = await response.read()
                    filename = _image_filename(data)
                    if response.status == 200 and filename is not None:
                        return discord.File(io.BytesIO(data), filename=filename)
                    logger.warning(
                        "CATAAS returned an invalid image on attempt %s/%s: "
                        "status=%s content_type=%s body=%r",
                        attempt,
                        CAT_FETCH_ATTEMPTS,
                        response.status,
                        response.headers.get("Content-Type"),
                        data[:200],
                    )
            except (aiohttp.ClientError, TimeoutError):
                logger.warning(
                    "CATAAS request failed on attempt %s/%s",
                    attempt,
                    CAT_FETCH_ATTEMPTS,
                    exc_info=True,
                )

    raise CatImageUnavailable("CATAAS did not return a valid image")


async def _send_cat(interaction: discord.Interaction, text: str | None = None) -> None:
    await interaction.response.defer()
    try:
        image = await _fetch_cat_image(text)
    except CatImageUnavailable:
        await interaction.edit_original_response(content=CAT_UNAVAILABLE_MESSAGE)
        return
    await interaction.edit_original_response(attachments=[image])


async def get_a_cat() -> discord.File:
    return await _fetch_cat_image()


async def cat_command(interaction: discord.Interaction) -> None:
    await _send_cat(interaction)


async def get_a_cat_with_text(text: str) -> discord.File:
    return await _fetch_cat_image(text)


async def cat_command_text(interaction: discord.Interaction, text: str) -> None:
    await _send_cat(interaction, text)

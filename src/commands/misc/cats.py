from __future__ import annotations

import html
import io
import logging
import textwrap
import unicodedata
from urllib.parse import quote

import aiohttp
import discord

logger = logging.getLogger(__name__)

CATAAS_BASE_URL = "https://cataas.com"
CAT_FETCH_ATTEMPTS = 3
CAT_FETCH_TIMEOUT_SECONDS = 10
CAT_UNAVAILABLE_MESSAGE = "Не удалось загрузить котика. Попробуйте ещё раз чуть позже."
CAT_CAPTION_IMAGE_WIDTH = 1000
CAT_CAPTION_MAX_LENGTH = 96
CAT_CAPTION_TARGET_LINE_LENGTH = 32
CAT_CAPTION_MAX_LINES = 3
CAT_CAPTION_LINE_HEIGHT = 1.15
CAT_CAPTION_HORIZONTAL_PADDING = 80
CAT_CAPTION_MIN_FONT_SIZE = 14
CAT_CAPTION_MAX_FONT_SIZE = 30


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


def _caption_visual_units(text: str) -> float:
    narrow_characters = set(" !'.,:;Iijl|1")
    wide_characters = set("MW@#%ЖШЩМЮФжшщмюф")
    visual_units = 0.0
    for character in text:
        if unicodedata.combining(character):
            continue
        if character in narrow_characters:
            visual_units += 0.35
        elif character in wide_characters or unicodedata.east_asian_width(character) in {"F", "W"}:
            visual_units += 1.0
        else:
            visual_units += 0.65
    return visual_units


def _normalize_caption(text: str) -> str:
    caption = " ".join(text.split())
    if len(caption) <= CAT_CAPTION_MAX_LENGTH:
        return caption

    clipped = caption[: CAT_CAPTION_MAX_LENGTH - 1].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return f"{clipped}…"


def _wrap_caption(text: str) -> list[str]:
    line_count = min(
        CAT_CAPTION_MAX_LINES,
        max(1, (len(text) + CAT_CAPTION_TARGET_LINE_LENGTH - 1) // CAT_CAPTION_TARGET_LINE_LENGTH),
    )
    line_width = max(1, (len(text) + line_count - 1) // line_count)
    while line_width <= len(text):
        lines = textwrap.wrap(
            text,
            width=line_width,
            break_long_words=True,
            break_on_hyphens=False,
        )
        if len(lines) <= line_count:
            return lines
        line_width += 1
    return [text]


def _caption_font_size(lines: str | list[str]) -> int:
    if isinstance(lines, str):
        lines = [lines]
    widest_line = max((_caption_visual_units(line) for line in lines), default=1.0)
    available_width = CAT_CAPTION_IMAGE_WIDTH - CAT_CAPTION_HORIZONTAL_PADDING
    fitted_size = int(available_width / max(widest_line, 1.0))
    return max(CAT_CAPTION_MIN_FONT_SIZE, min(CAT_CAPTION_MAX_FONT_SIZE, fitted_size))


def _caption_svg_text(lines: list[str]) -> str:
    escaped_lines = [html.escape(line).replace(".", "&#46;") for line in lines]
    if len(escaped_lines) == 1:
        return escaped_lines[0]

    first_offset = -((len(escaped_lines) - 1) * CAT_CAPTION_LINE_HEIGHT / 2)
    spans = []
    for index, line in enumerate(escaped_lines):
        offset = first_offset if index == 0 else CAT_CAPTION_LINE_HEIGHT
        spans.append(
            f'<tspan x="50%" dy="{offset:g}em" stroke="black" stroke-width="2" '
            f'paint-order="stroke">{line}</tspan>'
        )
    return "".join(spans)


async def _fetch_cat_image(text: str | None = None) -> discord.File:
    url = f"{CATAAS_BASE_URL}/cat"
    params = None
    if text is not None:
        caption = _normalize_caption(text)
        if caption:
            lines = _wrap_caption(caption)
            url = f"{url}/says/{quote(_caption_svg_text(lines), safe='')}"
            params = {
                "fontColor": "#FFFFFF",
                "fontSize": _caption_font_size(lines),
                "width": CAT_CAPTION_IMAGE_WIDTH,
            }

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

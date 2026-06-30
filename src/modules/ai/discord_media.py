import re
from collections.abc import Iterable

from src.modules.ai.models import AIImageInput


CUSTOM_EMOJI_PATTERN = re.compile(r"<(?P<animated>a?):(?P<name>[A-Za-z0-9_]{1,64}):(?P<id>\d{15,25})>")
MAX_AI_IMAGE_BYTES = 8 * 1024 * 1024
MAX_AI_IMAGES_PER_MESSAGE = 6
SUPPORTED_IMAGE_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def ai_images_from_discord_message(
    message,
    *,
    include_attachments: bool = True,
    include_custom_emojis: bool = True,
    limit: int = MAX_AI_IMAGES_PER_MESSAGE,
) -> list[AIImageInput]:
    images: list[AIImageInput] = []
    if include_attachments:
        images.extend(_attachment_images(getattr(message, "attachments", []) or []))
    if include_custom_emojis:
        images.extend(custom_emoji_images_from_text(getattr(message, "content", "") or ""))
    return images[: max(int(limit), 0)]


def custom_emoji_images_from_text(content: str) -> list[AIImageInput]:
    images: list[AIImageInput] = []
    seen_ids: set[str] = set()
    for match in CUSTOM_EMOJI_PATTERN.finditer(content or ""):
        emoji_id = match.group("id")
        if emoji_id in seen_ids:
            continue
        seen_ids.add(emoji_id)
        animated = bool(match.group("animated"))
        extension = "gif" if animated else "png"
        name = match.group("name")
        images.append(
            AIImageInput(
                url=f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}",
                source="custom_emoji",
                label=f":{name}:",
                content_type="image/gif" if animated else "image/png",
                detail="low",
            )
        )
    return images


def image_context_lines(images: Iterable[AIImageInput]) -> list[str]:
    lines: list[str] = []
    for index, image in enumerate(images, start=1):
        parts = [f"{index}. {image.source}"]
        if image.label:
            parts.append(f"label={image.label}")
        if image.content_type:
            parts.append(f"type={image.content_type}")
        if image.size is not None:
            parts.append(f"size={image.size} bytes")
        parts.append(f"url={image.url}")
        lines.append(" | ".join(parts))
    return lines


def append_image_context(content: str, images: list[AIImageInput]) -> str:
    if not images:
        return content
    lines = image_context_lines(images)
    return f"{content}\n\nVisual inputs:\n" + "\n".join(lines)


def _attachment_images(attachments) -> list[AIImageInput]:
    images: list[AIImageInput] = []
    for attachment in attachments:
        content_type = getattr(attachment, "content_type", None)
        if not content_type or content_type.lower().split(";", 1)[0] not in SUPPORTED_IMAGE_TYPES:
            continue
        size = getattr(attachment, "size", None)
        if size is not None and int(size) > MAX_AI_IMAGE_BYTES:
            continue
        url = getattr(attachment, "url", None) or getattr(attachment, "proxy_url", None)
        if not url:
            continue
        images.append(
            AIImageInput(
                url=str(url),
                source="attachment",
                label=getattr(attachment, "filename", None),
                content_type=content_type,
                size=int(size) if size is not None else None,
                detail="low",
            )
        )
    return images

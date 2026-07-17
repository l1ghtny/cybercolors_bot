import asyncio
import base64
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from src.modules.ai.models import AIImageInput


CUSTOM_EMOJI_PATTERN = re.compile(r"<(?P<animated>a?):(?P<name>[A-Za-z0-9_]{1,64}):(?P<id>\d{15,25})>")
IMAGE_URL_PATTERN = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
MAX_AI_IMAGE_BYTES = 8 * 1024 * 1024
MAX_AI_IMAGES_PER_MESSAGE = 6
MAX_AI_TOTAL_IMAGE_BYTES = 16 * 1024 * 1024
AI_ATTACHMENT_READ_TIMEOUT_SECONDS = 5.0
AI_ATTACHMENT_TOTAL_TIMEOUT_SECONDS = 8.0
SUPPORTED_IMAGE_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
AIImageDetail = Literal["low", "high", "auto"]
IMAGE_TYPES_BY_EXTENSION = {
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@dataclass(slots=True)
class PreparedDiscordImages:
    images: list[AIImageInput]
    attachment_statuses: dict[str, dict[str, Any]]

    @property
    def media_unavailable(self) -> bool:
        return any(bool(status.get("media_unavailable")) for status in self.attachment_statuses.values())


def ai_images_from_discord_message(
    message,
    *,
    include_attachments: bool = True,
    include_custom_emojis: bool = True,
    limit: int = MAX_AI_IMAGES_PER_MESSAGE,
    detail: AIImageDetail = "low",
) -> list[AIImageInput]:
    images: list[AIImageInput] = []
    if include_attachments:
        images.extend(_attachment_images(getattr(message, "attachments", []) or [], detail=detail))
    if include_custom_emojis:
        images.extend(custom_emoji_images_from_text(getattr(message, "content", "") or ""))
    images.extend(image_urls_from_text(getattr(message, "content", "") or "", detail=detail))
    return _dedupe_images(images)[: max(int(limit), 0)]


async def prepare_ai_images_from_discord_message(
    message,
    *,
    include_attachments: bool = True,
    include_custom_emojis: bool = True,
    limit: int = MAX_AI_IMAGES_PER_MESSAGE,
    per_image_max_bytes: int = MAX_AI_IMAGE_BYTES,
    total_max_bytes: int = MAX_AI_TOTAL_IMAGE_BYTES,
    read_timeout_seconds: float = AI_ATTACHMENT_READ_TIMEOUT_SECONDS,
    total_timeout_seconds: float = AI_ATTACHMENT_TOTAL_TIMEOUT_SECONDS,
    detail: AIImageDetail = "low",
) -> PreparedDiscordImages:
    """Read trusted Discord attachments into memory while leaving arbitrary URLs remote."""
    images: list[AIImageInput] = []
    statuses: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    max_images = max(int(limit), 0)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(float(total_timeout_seconds), 0.0)

    if include_attachments:
        for attachment in getattr(message, "attachments", []) or []:
            source_url = getattr(attachment, "url", None) or getattr(attachment, "proxy_url", None)
            content_type = _attachment_content_type(attachment, str(source_url or ""))
            if content_type not in SUPPORTED_IMAGE_TYPES:
                continue

            key = _attachment_key(attachment, source_url)
            if len(images) >= max_images:
                statuses[key] = _attachment_status(attachment, "image_limit_exceeded", unavailable=True)
                continue
            remaining_seconds = min(
                max(float(read_timeout_seconds), 0.0),
                max(deadline - loop.time(), 0.0),
            )
            image, status, actual_size = await _prepare_attachment_image(
                attachment,
                content_type=content_type,
                source_url=str(source_url) if source_url else None,
                per_image_max_bytes=max(int(per_image_max_bytes), 0),
                remaining_total_bytes=max(int(total_max_bytes) - total_bytes, 0),
                timeout_seconds=remaining_seconds,
                detail=detail,
            )
            statuses[key] = status
            if image is not None:
                images.append(image)
                total_bytes += actual_size

    content = getattr(message, "content", "") or ""
    if include_custom_emojis:
        images.extend(custom_emoji_images_from_text(content))
    images.extend(image_urls_from_text(content, detail=detail))
    return PreparedDiscordImages(
        images=_dedupe_images(images)[:max_images],
        attachment_statuses=statuses,
    )


async def _prepare_attachment_image(
    attachment,
    *,
    content_type: str,
    source_url: str | None,
    per_image_max_bytes: int,
    remaining_total_bytes: int,
    timeout_seconds: float,
    detail: AIImageDetail,
) -> tuple[AIImageInput | None, dict[str, Any], int]:
    declared_size = _attachment_size(attachment)
    if declared_size is not None and declared_size > per_image_max_bytes:
        return None, _attachment_status(attachment, "image_too_large", unavailable=True), 0
    if declared_size is not None and declared_size > remaining_total_bytes:
        return None, _attachment_status(attachment, "total_size_exceeded", unavailable=True), 0
    if timeout_seconds <= 0:
        return None, _attachment_status(attachment, "download_timeout", unavailable=True), 0

    reader = getattr(attachment, "read", None)
    if reader is None:
        return None, _attachment_status(attachment, "download_unavailable", unavailable=True), 0

    try:
        raw_data = await asyncio.wait_for(reader(use_cached=True), timeout=timeout_seconds)
        data = bytes(raw_data)
    except TimeoutError:
        return None, _attachment_status(attachment, "download_timeout", unavailable=True), 0
    except Exception:
        return None, _attachment_status(attachment, "download_failed", unavailable=True), 0

    actual_size = len(data)
    if actual_size == 0:
        return None, _attachment_status(attachment, "empty_file", unavailable=True), 0
    if actual_size > per_image_max_bytes:
        return None, _attachment_status(attachment, "image_too_large", unavailable=True), 0
    if actual_size > remaining_total_bytes:
        return None, _attachment_status(attachment, "total_size_exceeded", unavailable=True), 0
    if not _matches_declared_image_type(data, content_type):
        return None, _attachment_status(attachment, "content_type_mismatch", unavailable=True), 0

    encoded = base64.b64encode(data).decode("ascii")
    image = AIImageInput(
        url=f"data:{content_type};base64,{encoded}",
        source="attachment",
        source_url=source_url,
        label=getattr(attachment, "filename", None),
        content_type=content_type,
        size=actual_size,
        detail=detail,
    )
    status = _attachment_status(
        attachment,
        "available_inline",
        unavailable=False,
        actual_size=actual_size,
    )
    return image, status, actual_size


def _attachment_key(attachment, source_url: object | None) -> str:
    attachment_id = getattr(attachment, "id", None)
    return str(attachment_id if attachment_id is not None else source_url or id(attachment))


def _attachment_size(attachment) -> int | None:
    raw_size = getattr(attachment, "size", None)
    if raw_size is None:
        return None
    try:
        return max(int(raw_size), 0)
    except (TypeError, ValueError):
        return None


def _attachment_status(
    attachment,
    status: str,
    *,
    unavailable: bool,
    actual_size: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "media_status": status,
        "media_unavailable": unavailable,
    }
    if actual_size is not None:
        result["media_bytes"] = actual_size
    return result


def _matches_declared_image_type(data: bytes, content_type: str) -> bool:
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


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


def image_urls_from_text(content: str, *, detail: AIImageDetail = "low") -> list[AIImageInput]:
    images: list[AIImageInput] = []
    seen_urls: set[str] = set()
    for match in IMAGE_URL_PATTERN.finditer(content or ""):
        url = _clean_url(match.group(0))
        if url in seen_urls:
            continue
        content_type = _image_content_type_from_url(url)
        if content_type is None:
            continue
        seen_urls.add(url)
        images.append(
            AIImageInput(
                url=url,
                source="image_url",
                label=_image_label_from_url(url),
                content_type=content_type,
                detail=detail,
            )
        )
    return images


def image_context_lines(
    images: Iterable[AIImageInput],
    *,
    include_labels: bool = True,
    include_urls: bool = True,
) -> list[str]:
    lines: list[str] = []
    for index, image in enumerate(images, start=1):
        parts = [f"{index}. {image.source}"]
        if include_labels and image.label:
            parts.append(f"label={image.label}")
        if image.content_type:
            parts.append(f"type={image.content_type}")
        if image.size is not None:
            parts.append(f"size={image.size} bytes")
        context_url = image.source_url or (None if image.url.startswith("data:") else image.url)
        if include_urls and context_url:
            parts.append(f"url={context_url}")
        elif image.url.startswith("data:"):
            parts.append("transport=inline")
        lines.append(" | ".join(parts))
    return lines


def append_image_context(
    content: str,
    images: list[AIImageInput],
    *,
    include_labels: bool = True,
    include_urls: bool = True,
) -> str:
    if not images:
        return content
    lines = image_context_lines(
        images,
        include_labels=include_labels,
        include_urls=include_urls,
    )
    return f"{content}\n\nVisual inputs:\n" + "\n".join(lines)


def _attachment_images(attachments, *, detail: AIImageDetail = "low") -> list[AIImageInput]:
    images: list[AIImageInput] = []
    for attachment in attachments:
        url = getattr(attachment, "url", None) or getattr(attachment, "proxy_url", None)
        if not url:
            continue
        content_type = _attachment_content_type(attachment, str(url))
        if content_type not in SUPPORTED_IMAGE_TYPES:
            continue
        size = getattr(attachment, "size", None)
        if size is not None and int(size) > MAX_AI_IMAGE_BYTES:
            continue
        images.append(
            AIImageInput(
                url=str(url),
                source="attachment",
                source_url=str(url),
                label=getattr(attachment, "filename", None),
                content_type=content_type,
                size=int(size) if size is not None else None,
                detail=detail,
            )
        )
    return images


def _dedupe_images(images: list[AIImageInput]) -> list[AIImageInput]:
    deduped: list[AIImageInput] = []
    seen_sources: set[str] = set()
    for image in images:
        source_key = image.source_url or image.url
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        deduped.append(image)
    return deduped


def _attachment_content_type(attachment, url: str) -> str | None:
    raw_content_type = getattr(attachment, "content_type", None)
    if raw_content_type:
        return raw_content_type.lower().split(";", 1)[0].strip()

    filename = getattr(attachment, "filename", None)
    for candidate in (filename, urlparse(url).path):
        if not candidate:
            continue
        lowered = str(candidate).lower()
        for extension, content_type in IMAGE_TYPES_BY_EXTENSION.items():
            if lowered.endswith(extension):
                return content_type
    return None


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?)]}")


def _image_content_type_from_url(url: str) -> str | None:
    path = urlparse(url).path.lower()
    for extension, content_type in IMAGE_TYPES_BY_EXTENSION.items():
        if path.endswith(extension):
            return content_type
    return None


def _image_label_from_url(url: str) -> str | None:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return name or None

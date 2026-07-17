import asyncio
import base64
from types import SimpleNamespace

from src.modules.ai.discord_media import (
    ai_images_from_discord_message,
    custom_emoji_images_from_text,
    image_context_lines,
    image_urls_from_text,
    prepare_ai_images_from_discord_message,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image"


class ReadableAttachment(SimpleNamespace):
    def __init__(self, *, data: bytes = PNG_BYTES, **kwargs):
        super().__init__(**kwargs)
        self.data = data
        self.read_calls = 0

    async def read(self, *, use_cached: bool = False) -> bytes:
        assert use_cached is True
        self.read_calls += 1
        return self.data


def test_custom_emoji_images_from_text_builds_discord_cdn_urls():
    images = custom_emoji_images_from_text("hello <:party:123456789012345678> <a:dance:234567890123456789>")

    assert [image.label for image in images] == [":party:", ":dance:"]
    assert images[0].url == "https://cdn.discordapp.com/emojis/123456789012345678.png"
    assert images[0].content_type == "image/png"
    assert images[1].url == "https://cdn.discordapp.com/emojis/234567890123456789.gif"
    assert images[1].content_type == "image/gif"


def test_ai_images_from_discord_message_filters_to_supported_images():
    message = SimpleNamespace(
        content="look <:party:123456789012345678>",
        attachments=[
            SimpleNamespace(
                id=1,
                filename="photo.png",
                content_type="image/png",
                size=1024,
                url="https://cdn.discordapp.com/attachments/1/photo.png",
            ),
            SimpleNamespace(
                id=2,
                filename="clip.mp4",
                content_type="video/mp4",
                size=1024,
                url="https://cdn.discordapp.com/attachments/1/clip.mp4",
            ),
            SimpleNamespace(
                id=3,
                filename="huge.jpg",
                content_type="image/jpeg",
                size=9 * 1024 * 1024,
                url="https://cdn.discordapp.com/attachments/1/huge.jpg",
            ),
        ],
    )

    images = ai_images_from_discord_message(message)

    assert [image.source for image in images] == ["attachment", "custom_emoji"]
    assert images[0].label == "photo.png"
    assert images[1].label == ":party:"


def test_ai_images_from_discord_message_infers_image_type_from_filename():
    message = SimpleNamespace(
        content="what is this?",
        attachments=[
            SimpleNamespace(
                id=1,
                filename="photo.jpg",
                content_type=None,
                size=2048,
                url="https://cdn.discordapp.com/attachments/1/photo.jpg?ex=abc",
            ),
            SimpleNamespace(
                id=2,
                filename="archive.zip",
                content_type=None,
                size=2048,
                url="https://cdn.discordapp.com/attachments/1/archive.zip",
            ),
        ],
    )

    images = ai_images_from_discord_message(message)

    assert len(images) == 1
    assert images[0].label == "photo.jpg"
    assert images[0].content_type == "image/jpeg"


def test_image_urls_from_text_extracts_direct_discord_gif_links():
    images = image_urls_from_text(
        "https://cdn.discordapp.com/attachments/479003269780340736/1517111288927621251/doc_2026-05-10_08-40.gif"
    )

    assert len(images) == 1
    assert images[0].source == "image_url"
    assert images[0].content_type == "image/gif"
    assert images[0].label == "doc_2026-05-10_08-40.gif"


def test_ai_images_from_discord_message_includes_direct_image_links_and_dedupes():
    url = "https://media.discordapp.net/attachments/1/photo.webp?ex=abc"
    message = SimpleNamespace(
        content=f"look {url} {url}",
        attachments=[
            SimpleNamespace(
                id=1,
                filename="photo.webp",
                content_type="image/webp",
                size=1024,
                url=url,
            )
        ],
    )

    images = ai_images_from_discord_message(message)

    assert len(images) == 1
    assert images[0].source == "attachment"
    assert images[0].url == url


def test_prepare_ai_images_downloads_discord_attachment_into_data_url():
    attachment_url = "https://cdn.discordapp.com/attachments/1/photo.png"
    external_url = "https://example.com/reference.webp"
    attachment = ReadableAttachment(
        id=1,
        filename="photo.png",
        content_type="image/png",
        size=len(PNG_BYTES),
        url=attachment_url,
    )
    message = SimpleNamespace(
        content=f"compare {attachment_url} with {external_url}",
        attachments=[attachment],
    )

    result = asyncio.run(
        prepare_ai_images_from_discord_message(
            message,
            include_custom_emojis=False,
            detail="high",
        )
    )

    assert attachment.read_calls == 1
    assert len(result.images) == 2
    inline_image, remote_image = result.images
    assert inline_image.source == "attachment"
    assert inline_image.source_url == attachment_url
    assert inline_image.url.startswith("data:image/png;base64,")
    assert inline_image.detail == "high"
    assert base64.b64decode(inline_image.url.split(",", 1)[1]) == PNG_BYTES
    assert remote_image.source == "image_url"
    assert remote_image.url == external_url
    assert remote_image.detail == "high"
    assert result.attachment_statuses["1"] == {
        "media_status": "available_inline",
        "media_unavailable": False,
        "media_bytes": len(PNG_BYTES),
    }
    assert result.media_unavailable is False

    context = "\n".join(image_context_lines(result.images))
    assert "data:image/png;base64" not in context
    assert attachment_url in context


def test_prepare_ai_images_continues_when_discord_attachment_download_fails():
    class FailingAttachment(ReadableAttachment):
        async def read(self, *, use_cached: bool = False) -> bytes:
            assert use_cached is True
            self.read_calls += 1
            raise RuntimeError("expired Discord CDN URL")

    attachment = FailingAttachment(
        id=2,
        filename="photo.png",
        content_type="image/png",
        size=1024,
        url="https://cdn.discordapp.com/attachments/1/expired.png",
    )
    message = SimpleNamespace(
        content="see https://example.com/still-remote.jpg",
        attachments=[attachment],
    )

    result = asyncio.run(prepare_ai_images_from_discord_message(message, include_custom_emojis=False))

    assert [image.url for image in result.images] == ["https://example.com/still-remote.jpg"]
    assert result.attachment_statuses["2"] == {
        "media_status": "download_failed",
        "media_unavailable": True,
    }
    assert result.media_unavailable is True


def test_prepare_ai_images_enforces_declared_size_and_mime_signature():
    oversized = ReadableAttachment(
        id=3,
        filename="large.png",
        content_type="image/png",
        size=100,
        url="https://cdn.discordapp.com/attachments/1/large.png",
    )
    wrong_type = ReadableAttachment(
        id=4,
        filename="fake.png",
        content_type="image/png",
        size=8,
        data=b"not-png!",
        url="https://cdn.discordapp.com/attachments/1/fake.png",
    )
    message = SimpleNamespace(content="", attachments=[oversized, wrong_type])

    result = asyncio.run(
        prepare_ai_images_from_discord_message(
            message,
            include_custom_emojis=False,
            per_image_max_bytes=50,
            total_max_bytes=50,
        )
    )

    assert result.images == []
    assert oversized.read_calls == 0
    assert wrong_type.read_calls == 1
    assert result.attachment_statuses["3"]["media_status"] == "image_too_large"
    assert result.attachment_statuses["4"]["media_status"] == "content_type_mismatch"
    assert result.media_unavailable is True


def test_prepare_ai_images_enforces_total_size_and_timeout_budgets():
    first = ReadableAttachment(
        id=5,
        filename="first.png",
        content_type="image/png",
        size=len(PNG_BYTES),
        url="https://cdn.discordapp.com/attachments/1/first.png",
    )
    second = ReadableAttachment(
        id=6,
        filename="second.png",
        content_type="image/png",
        size=len(PNG_BYTES),
        url="https://cdn.discordapp.com/attachments/1/second.png",
    )
    message = SimpleNamespace(content="", attachments=[first, second])

    total_limited = asyncio.run(
        prepare_ai_images_from_discord_message(
            message,
            include_custom_emojis=False,
            total_max_bytes=len(PNG_BYTES) + 1,
        )
    )

    assert len(total_limited.images) == 1
    assert first.read_calls == 1
    assert second.read_calls == 0
    assert total_limited.attachment_statuses["6"]["media_status"] == "total_size_exceeded"

    timed_out = asyncio.run(
        prepare_ai_images_from_discord_message(
            SimpleNamespace(content="", attachments=[second]),
            include_custom_emojis=False,
            total_timeout_seconds=0,
        )
    )

    assert second.read_calls == 0
    assert timed_out.images == []
    assert timed_out.attachment_statuses["6"]["media_status"] == "download_timeout"

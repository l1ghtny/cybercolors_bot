from types import SimpleNamespace

from src.modules.ai.discord_media import ai_images_from_discord_message, custom_emoji_images_from_text


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

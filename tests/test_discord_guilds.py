import asyncio

from api.services import discord_guilds


async def _create_channel_message_embed_scenario(captured: list[dict]) -> None:
    async def fake_discord_post(path: str, payload: dict) -> dict:
        captured.append({"path": path, "payload": payload})
        return {"id": "message-id"}

    original = discord_guilds._discord_post
    discord_guilds._discord_post = fake_discord_post
    try:
        result = await discord_guilds.create_channel_message(
            channel_id=123,
            embeds=[{"title": "Moderation log"}],
        )
    finally:
        discord_guilds._discord_post = original

    assert result == {"id": "message-id"}


def test_create_channel_message_sends_embed_payload_without_content():
    captured: list[dict] = []
    asyncio.run(_create_channel_message_embed_scenario(captured))

    assert captured == [
        {
            "path": "/channels/123/messages",
            "payload": {
                "allowed_mentions": {"parse": []},
                "embeds": [{"title": "Moderation log"}],
            },
        }
    ]

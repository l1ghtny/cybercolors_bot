import asyncio

from fastapi import HTTPException, status

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
            components=[
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "style": 4,
                            "label": "Revert",
                            "custom_id": "mod-action:revert:action-id",
                        }
                    ],
                }
            ],
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
                "allowed_mentions": {"parse": [], "replied_user": False},
                "embeds": [{"title": "Moderation log"}],
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": 4,
                                "label": "Revert",
                                "custom_id": "mod-action:revert:action-id",
                            }
                        ],
                    }
                ],
            },
        }
    ]


async def _create_channel_reply_scenario(
    captured: list[dict],
    *,
    notify_replied_user: bool = False,
) -> None:
    async def fake_discord_post(path: str, payload: dict) -> dict:
        captured.append({"path": path, "payload": payload})
        return {"id": "456"}

    original = discord_guilds._discord_post
    discord_guilds._discord_post = fake_discord_post
    try:
        await discord_guilds.create_channel_message(
            channel_id=123,
            content="A reply",
            reply_to_message_id=789,
            notify_replied_user=notify_replied_user,
        )
    finally:
        discord_guilds._discord_post = original


def test_create_channel_message_can_reply_without_notifying_author():
    captured: list[dict] = []
    asyncio.run(_create_channel_reply_scenario(captured))

    assert captured == [
        {
            "path": "/channels/123/messages",
            "payload": {
                "allowed_mentions": {"parse": [], "replied_user": False},
                "content": "A reply",
                "message_reference": {
                    "message_id": "789",
                    "fail_if_not_exists": True,
                },
            },
        }
    ]


def test_create_channel_message_can_notify_replied_to_author():
    captured: list[dict] = []
    asyncio.run(
        _create_channel_reply_scenario(captured, notify_replied_user=True)
    )

    assert captured[0]["payload"]["allowed_mentions"] == {
        "parse": [],
        "replied_user": True,
    }


def test_create_channel_message_uses_multipart_for_media(monkeypatch):
    captured: list[dict] = []

    async def fake_discord_post_multipart(path: str, payload: dict, files: list[tuple[str, bytes, str]]):
        captured.append({"path": path, "payload": payload, "files": files})
        return {"id": "media-message"}

    monkeypatch.setattr(discord_guilds, "_discord_post_multipart", fake_discord_post_multipart)
    result = asyncio.run(
        discord_guilds.create_channel_message(
            channel_id=123,
            content="Announcement",
            files=[("banner.png", b"png-data", "image/png")],
        )
    )

    assert result == {"id": "media-message"}
    assert captured == [
        {
            "path": "/channels/123/messages",
            "payload": {
                "allowed_mentions": {"parse": [], "replied_user": False},
                "content": "Announcement",
            },
            "files": [("banner.png", b"png-data", "image/png")],
        }
    ]


async def _overwrite_rate_limit_scenario(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    sleeps: list[float] = []

    async def fake_put(path: str, payload: dict) -> dict:
        calls.append((path, payload))
        if len(calls) == 1:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail='Discord API error: {"retry_after": 0}',
            )
        return {}

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(discord_guilds, "_discord_put", fake_put)
    monkeypatch.setattr(discord_guilds.asyncio, "sleep", fake_sleep)

    await discord_guilds.update_channel_role_overwrite(
        channel_id=123,
        role_id=456,
        allow=7,
        deny=8,
    )

    assert calls == [
        ("/channels/123/permissions/456", {"allow": "7", "deny": "8", "type": 0}),
        ("/channels/123/permissions/456", {"allow": "7", "deny": "8", "type": 0}),
    ]
    assert sleeps == [0.1]


def test_channel_role_overwrite_retries_rate_limits(monkeypatch):
    asyncio.run(_overwrite_rate_limit_scenario(monkeypatch))

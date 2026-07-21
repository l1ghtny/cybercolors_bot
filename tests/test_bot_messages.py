import asyncio

import pytest
from fastapi import HTTPException, status
from fastapi.routing import APIRoute

from api.api_main import app
from api.models.bot_messages import BotMessageCreateModel
from api.services.bot_messages import send_bot_message
from src.db.models import BotMessageAuditEvent, GlobalUser, ServerSecuritySettings


class FakeSession:
    def __init__(self, *, paused: bool = False):
        self.paused = paused
        self.added: list[object] = []
        self.commit_count = 0

    async def get(self, model, key):
        if model is ServerSecuritySettings:
            return ServerSecuritySettings(server_id=key, public_bot_responses_paused=True) if self.paused else None
        if model is GlobalUser:
            return GlobalUser(discord_id=key, username="moderator")
        return None

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        return None

    async def commit(self):
        self.commit_count += 1


async def _send_scenario(
    *,
    paused: bool = False,
    sender_error: Exception | None = None,
    session: FakeSession | None = None,
):
    session = session or FakeSession(paused=paused)
    sender_calls: list[dict] = []

    async def channel_fetcher(server_id: int, channel_id: int):
        return {"id": str(channel_id), "guild_id": str(server_id), "type": 0}

    async def message_fetcher(channel_id: int, message_id: int):
        return {"id": str(message_id), "channel_id": str(channel_id)}

    async def sender(**kwargs):
        sender_calls.append(kwargs)
        if sender_error is not None:
            raise sender_error
        return {"id": "777"}

    result = await send_bot_message(
        session,
        server_id=123,
        actor_user_id=456,
        body=BotMessageCreateModel(
            channel_id="789",
            content="Hello from Modral",
            reply_to_message_id="654",
        ),
        source="dashboard",
        sender=sender,
        channel_fetcher=channel_fetcher,
        message_fetcher=message_fetcher,
    )
    return session, sender_calls, result


def test_send_bot_message_replies_and_records_successful_audit():
    session, sender_calls, result = asyncio.run(_send_scenario())

    assert sender_calls == [
        {
            "channel_id": 789,
            "content": "Hello from Modral",
            "reply_to_message_id": 654,
        }
    ]
    audit = next(item for item in session.added if isinstance(item, BotMessageAuditEvent))
    assert audit.status == "sent"
    assert audit.discord_message_id == 777
    assert audit.reply_to_message_id == 654
    assert audit.actor_user_id == 456
    assert session.commit_count == 2
    assert result.jump_url == "https://discord.com/channels/123/789/777"


def test_send_bot_message_records_discord_failure():
    error = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing Access")
    session = FakeSession()
    with pytest.raises(HTTPException) as raised:
        asyncio.run(_send_scenario(sender_error=error, session=session))

    assert raised.value is error
    audit = next(item for item in session.added if isinstance(item, BotMessageAuditEvent))
    assert audit.status == "failed"
    assert audit.error_text == "Missing Access"
    assert session.commit_count == 2


def test_send_bot_message_honors_public_response_pause():
    with pytest.raises(HTTPException) as raised:
        asyncio.run(_send_scenario(paused=True))

    assert raised.value.status_code == status.HTTP_423_LOCKED


def test_bot_message_payload_rejects_blank_or_overlong_content():
    with pytest.raises(ValueError):
        BotMessageCreateModel(channel_id="123", content="   ")
    with pytest.raises(ValueError):
        BotMessageCreateModel(channel_id="123", content="x" * 2001)


def _route_permissions(path: str, method: str) -> set[str]:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return {
                dependency.call.permission_key
                for dependency in route.dependant.dependencies
                if hasattr(dependency.call, "permission_key")
            }
    raise AssertionError(f"Route not found: {method} {path}")


def test_bot_message_routes_require_explicit_permissions():
    path = "/servers/{server_id}/bot-messages"
    assert _route_permissions(path, "POST") == {"communications.send_as_bot"}
    assert _route_permissions(path, "GET") == {"audit.timeline.view"}

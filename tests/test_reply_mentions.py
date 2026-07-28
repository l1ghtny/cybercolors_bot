import asyncio
from types import SimpleNamespace

from src.db.models import Replies, Triggers
from src.modules.on_message_processing import replies as replies_module
from src.modules.on_message_processing.reply_matcher import (
    compile_guild_reply_matcher,
    invalidate_reply_matcher,
)

from src.modules.on_message_processing.replies import check_for_replies, send_reply


class FakeMessage:
    content = "hello"

    def __init__(self):
        self.calls: list[dict] = []
        self.guild = SimpleNamespace(id=1)
        self.channel = SimpleNamespace(id=10, parent_id=None)
        self.author = SimpleNamespace(id=20, roles=[])

    async def reply(self, content: str, **kwargs):
        self.calls.append({"content": content, **kwargs})


def test_automatic_reply_pings_only_selected_explicit_users_and_roles():
    message = FakeMessage()

    asyncio.run(send_reply(
        message,
        "Hello <@42>, <@43>, and <@&84> @everyone",
        False,
        allowed_user_ids=frozenset({"42", "99"}),
        allowed_role_ids=frozenset({"84", "98"}),
    ))

    call = message.calls[0]
    allowed_mentions = call["allowed_mentions"]
    assert call["mention_author"] is False
    assert allowed_mentions.everyone is False
    assert allowed_mentions.replied_user is False
    assert [user.id for user in allowed_mentions.users] == [42]
    assert [role.id for role in allowed_mentions.roles] == [84]


def test_automatic_reply_keeps_raw_mentions_silent_by_default():
    message = FakeMessage()

    asyncio.run(send_reply(message, "Hello <@42> and <@&84>", False))

    allowed_mentions = message.calls[0]["allowed_mentions"]
    assert allowed_mentions.users is False
    assert allowed_mentions.roles is False


def test_message_handling_suppresses_repeated_matches_during_reply_cooldown(monkeypatch):
    invalidate_reply_matcher()
    reply = Replies(
        server_id=1,
        bot_reply="Automatic answer",
        created_by_id=2,
        cooldown_seconds=10,
    )
    trigger = Triggers(
        message="hello",
        reply_id=reply.id,
        source="representative",
    )
    matcher = compile_guild_reply_matcher(1, None, [], [(trigger, reply)])

    async def get_matcher(_server_id):
        return matcher

    monkeypatch.setattr(replies_module, "get_reply_matcher", get_matcher)
    message = FakeMessage()

    first = asyncio.run(check_for_replies(message))
    second = asyncio.run(check_for_replies(message))

    assert first == (True, 1)
    assert second == (False, 1)
    assert [call["content"] for call in message.calls] == ["Automatic answer"]

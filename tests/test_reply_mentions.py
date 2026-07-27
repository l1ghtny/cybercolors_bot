import asyncio

from src.modules.on_message_processing.replies import send_reply


class FakeMessage:
    content = "hello"

    def __init__(self):
        self.calls: list[dict] = []

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

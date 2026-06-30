import asyncio

import pytest

from src.modules.ai.models import AIMessage
from src.modules.chat_bot.create_response import AIAnswerTimeoutError, _create_ai_response
from src.modules.localization.service import tr


class FakeSessionContext:
    def __init__(self, session="session"):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeGuild:
    id = 123


class FakeAuthor:
    id = 456


class FakeChannel:
    id = 789


class FakeMessage:
    guild = FakeGuild()
    author = FakeAuthor()
    channel = FakeChannel()
    id = 111
    content = "hello"
    attachments = []


def test_create_ai_response_times_out(monkeypatch):
    import src.modules.chat_bot.create_response as create_response

    class SlowAI:
        async def answer(self, *_args, **_kwargs):
            await asyncio.sleep(0.05)

    monkeypatch.setenv("AI_ANSWER_TIMEOUT_SECONDS", "0.001")
    monkeypatch.setattr(create_response, "get_async_session", lambda: FakeSessionContext())
    monkeypatch.setattr(create_response, "ai_main_class", SlowAI())

    with pytest.raises(AIAnswerTimeoutError):
        asyncio.run(
            _create_ai_response(
                content="hello",
                message=FakeMessage(),
                conversation=[AIMessage(role="user", content="previous")],
            )
        )


def test_create_ai_response_logs_success(monkeypatch):
    import src.modules.chat_bot.create_response as create_response
    from src.modules.ai.models import AIResponse

    class FakeLogSession:
        def __init__(self):
            self.added = None
            self.committed = False

        def add(self, item):
            self.added = item

        async def flush(self):
            return None

        async def commit(self):
            self.committed = True

        async def rollback(self):
            return None

    class SuccessfulAI:
        async def answer(self, *_args, **_kwargs):
            return AIResponse(
                content="hello back",
                model="test-model",
                provider="fake",
                total_tokens=9,
                tool_call_count=1,
                id="resp-1",
            )

    session = FakeLogSession()
    monkeypatch.setattr(create_response, "get_async_session", lambda: FakeSessionContext(session))
    monkeypatch.setattr(create_response, "ai_main_class", SuccessfulAI())

    content, tokens = asyncio.run(
        _create_ai_response(
            content="hello",
            message=FakeMessage(),
            conversation=[AIMessage(role="user", content="previous")],
        )
    )

    assert content == "hello back"
    assert tokens == 9
    assert session.committed is True
    assert session.added is not None
    assert session.added.status == "success"
    assert session.added.message_id == 111
    assert session.added.total_tokens == 9
    assert session.added.tool_call_count == 1


def test_decide_on_response_localizes_reply_thread_limit(monkeypatch):
    import src.modules.chat_bot.message_processing as message_processing

    class FakeClient:
        user = type("BotUser", (), {"id": 999})()

    async def fake_count_replies(_message):
        return message_processing.REPLY_THREAD_LIMIT + 1, []

    monkeypatch.setattr(message_processing, "check_replies", lambda _message: True)
    monkeypatch.setattr(message_processing, "count_replies", fake_count_replies)

    content, tokens = asyncio.run(
        message_processing.decide_on_response(FakeMessage(), FakeClient(), locale="en")
    )

    assert "up to 8 messages" in content
    assert tokens == 0


def test_decide_on_response_localizes_multi_user_reply_thread(monkeypatch):
    import src.modules.chat_bot.message_processing as message_processing

    class FakeClient:
        user = type("BotUser", (), {"id": 999})()

    async def fake_count_replies(_message):
        return 1, [{"author": 111, "content": "hello"}]

    monkeypatch.setattr(message_processing, "check_replies", lambda _message: True)
    monkeypatch.setattr(message_processing, "count_replies", fake_count_replies)

    content, tokens = asyncio.run(
        message_processing.decide_on_response(FakeMessage(), FakeClient(), locale="ru")
    )

    assert "одним участником" in content
    assert tokens == 0


def test_look_for_bot_reply_edits_placeholder_on_failure(monkeypatch):
    import src.modules.on_message_processing.gpt_bot_reply as gpt_bot_reply

    class FakeReply:
        def __init__(self):
            self.edits = []

        async def edit(self, **kwargs):
            self.edits.append(kwargs)

    class FakeBotUser:
        pass

    class FakeMessageForReply:
        id = 111
        content = "@bot hello"
        guild = FakeGuild()
        channel = FakeChannel()

        def __init__(self):
            self.reply_message = FakeReply()
            self.replies = []

        async def reply(self, content, **kwargs):
            self.replies.append({"content": content, **kwargs})
            return self.reply_message

    async def fake_check_bot_mention(_message, _client):
        return True

    async def fake_check_for_channel(_message, _client):
        return True, _message.channel

    async def fake_decide_on_response(_message, _client, **_kwargs):
        raise RuntimeError("provider failed")

    async def fake_get_server_locale(_server_id):
        return "en"

    message = FakeMessageForReply()
    monkeypatch.setattr(gpt_bot_reply, "check_bot_mention", fake_check_bot_mention)
    monkeypatch.setattr(gpt_bot_reply, "check_for_channel", fake_check_for_channel)
    monkeypatch.setattr(gpt_bot_reply, "decide_on_response", fake_decide_on_response)
    monkeypatch.setattr(gpt_bot_reply, "get_server_locale", fake_get_server_locale)

    asyncio.run(gpt_bot_reply.look_for_bot_reply(message, client=FakeBotUser()))

    assert message.replies == [
        {
            "content": tr("en", "ai_reply.thinking"),
            "allowed_mentions": gpt_bot_reply.NO_AI_MENTIONS,
        }
    ]
    assert message.reply_message.edits == [
        {
            "content": tr("en", "ai_reply.failure"),
            "allowed_mentions": gpt_bot_reply.NO_AI_MENTIONS,
        }
    ]

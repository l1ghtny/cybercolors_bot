import asyncio

from src.modules.ai.answer_logging import log_ai_answer_attempt
from src.modules.ai.models import AIImageInput, AIMessage, AIResponse, AssistantInput


class FakeLogSession:
    def __init__(self):
        self.added = None
        self.flushed = False
        self.committed = False
        self.rolled_back = False

    def add(self, item):
        self.added = item

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def test_log_ai_answer_attempt_persists_success_metadata():
    session = FakeLogSession()
    assistant_input = AssistantInput(
        content="What do you know about me?",
        server_id=123,
        author_user_id=456,
        channel_id=789,
        conversation=[AIMessage(role="assistant", content="previous")],
        images=[
            AIImageInput(
                url="https://cdn.discordapp.com/emojis/123456789012345678.png",
                source="custom_emoji",
            )
        ],
        metadata={"message_id": 111},
    )
    response = AIResponse(
        content="You are the admin.",
        model="test-model",
        provider="fake",
        total_tokens=42,
        tool_call_count=2,
        id="resp-1",
    )

    asyncio.run(
        log_ai_answer_attempt(
            session=session,
            assistant_input=assistant_input,
            status="success",
            started_at=0,
            response=response,
        )
    )

    assert session.added is not None
    assert session.flushed is True
    assert session.committed is True
    assert session.rolled_back is False
    assert session.added.server_id == 123
    assert session.added.channel_id == 789
    assert session.added.message_id == 111
    assert session.added.author_user_id == 456
    assert session.added.status == "success"
    assert session.added.provider == "fake"
    assert session.added.model == "test-model"
    assert session.added.response_id == "resp-1"
    assert session.added.total_tokens == 42
    assert session.added.tool_call_count == 2
    assert session.added.visual_input_count == 1
    assert session.added.conversation_message_count == 1
    assert session.added.request_content == "What do you know about me?"
    assert session.added.response_content == "You are the admin."


def test_log_ai_answer_attempt_persists_error_metadata():
    session = FakeLogSession()
    assistant_input = AssistantInput(content="hello", server_id=123, metadata={"message_id": "222"})
    error = RuntimeError("provider failed")

    asyncio.run(
        log_ai_answer_attempt(
            session=session,
            assistant_input=assistant_input,
            status="error",
            started_at=0,
            error=error,
        )
    )

    assert session.added.status == "error"
    assert session.added.message_id == 222
    assert session.added.error_type == "RuntimeError"
    assert session.added.error_message == "provider failed"
    assert session.committed is True

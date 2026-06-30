import asyncio
from types import SimpleNamespace

from src.modules.ai.models import AIImageInput, AIMessage, AIRequest
from src.modules.ai.providers import OpenAIProvider


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            output_text="ok",
            usage=SimpleNamespace(total_tokens=7),
            output=[],
            id="resp-1",
        )


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


def test_openai_provider_formats_multimodal_message_content():
    client = FakeClient()
    provider = OpenAIProvider(client=client)
    image = AIImageInput(
        url="https://cdn.discordapp.com/emojis/123456789012345678.png",
        source="custom_emoji",
        label=":party:",
        content_type="image/png",
    )

    response = asyncio.run(
        provider.complete(
            AIRequest(
                task="assistant",
                model="test-model",
                system_prompt="Answer.",
                messages=[AIMessage(role="user", content="What is this?", images=[image])],
            )
        )
    )

    assert response.content == "ok"
    assert response.total_tokens == 7
    assert client.responses.kwargs is not None
    message = client.responses.kwargs["input"][0]
    assert message["role"] == "user"
    assert message["content"] == [
        {"type": "input_text", "text": "What is this?"},
        {
            "type": "input_image",
            "image_url": "https://cdn.discordapp.com/emojis/123456789012345678.png",
            "detail": "low",
        },
    ]

from typing import Protocol

from openai import APIError, AsyncOpenAI, RateLimitError

from src.modules.ai.models import AIRequest, AIResponse


class AIProvider(Protocol):
    provider_name: str

    async def complete(self, request: AIRequest) -> AIResponse:
        ...


class AIProviderError(RuntimeError):
    pass


class OpenAIProvider:
    provider_name = "openai"

    def __init__(self, client: AsyncOpenAI | None = None):
        self.client = client or AsyncOpenAI()

    async def complete(self, request: AIRequest) -> AIResponse:
        input_messages = [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in request.messages
        ]
        create_kwargs = {
            "model": request.model,
            "instructions": request.system_prompt,
            "input": input_messages,
        }
        if request.max_output_tokens is not None:
            create_kwargs["max_output_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            create_kwargs["temperature"] = request.temperature

        try:
            response = await self.client.responses.create(**create_kwargs)
        except (APIError, RateLimitError) as exc:
            raise AIProviderError(str(exc)) from exc

        content = getattr(response, "output_text", None)
        usage = getattr(response, "usage", None)
        total_tokens = getattr(usage, "total_tokens", 0) if usage is not None else 0
        return AIResponse(
            content=content,
            model=request.model,
            provider=self.provider_name,
            total_tokens=int(total_tokens or 0),
            raw=response,
        )

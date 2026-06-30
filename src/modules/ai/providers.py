import json
from typing import Any, Protocol

from openai import APIError, AsyncOpenAI, RateLimitError

from src.modules.ai.models import AIMessage, AIRequest, AIResponse, AIToolCall


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
        input_messages: list[dict[str, Any]] = []
        if request.tool_results:
            input_messages.extend(
                {
                    "type": "function_call_output",
                    "call_id": tool_result.call_id,
                    "output": (
                        tool_result.output
                        if isinstance(tool_result.output, str)
                        else json.dumps(tool_result.output, ensure_ascii=True, default=str)
                    ),
                }
                for tool_result in request.tool_results
            )
        else:
            input_messages.extend(
                {
                    "role": message.role,
                    "content": self._message_content(message),
                }
                for message in request.messages
            )
        create_kwargs = {
            "model": request.model,
            "instructions": request.system_prompt,
            "input": input_messages,
        }
        if request.max_output_tokens is not None:
            create_kwargs["max_output_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            create_kwargs["temperature"] = request.temperature
        if request.previous_response_id is not None:
            create_kwargs["previous_response_id"] = request.previous_response_id
        response_tools: list[dict[str, Any]] = []
        if request.enable_web_search:
            response_tools.append({"type": "web_search"})
        if request.tools:
            response_tools.extend(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                    "strict": False,
                }
                for tool in request.tools
            )
        if response_tools:
            create_kwargs["tools"] = response_tools
            create_kwargs["tool_choice"] = "auto"
            create_kwargs["parallel_tool_calls"] = False
        if request.max_tool_calls is not None:
            create_kwargs["max_tool_calls"] = request.max_tool_calls

        try:
            response = await self.client.responses.create(**create_kwargs)
        except (APIError, RateLimitError) as exc:
            raise AIProviderError(str(exc)) from exc

        content = getattr(response, "output_text", None)
        usage = getattr(response, "usage", None)
        total_tokens = getattr(usage, "total_tokens", 0) if usage is not None else 0
        tool_calls = self._tool_calls(response)
        return AIResponse(
            content=content,
            model=request.model,
            provider=self.provider_name,
            total_tokens=int(total_tokens or 0),
            tool_call_count=len(tool_calls),
            raw=response,
            tool_calls=tool_calls,
            id=getattr(response, "id", None),
        )

    @staticmethod
    def _message_content(message: AIMessage) -> str | list[dict[str, Any]]:
        if not message.images:
            return message.content
        content: list[dict[str, Any]] = [{"type": "input_text", "text": message.content or ""}]
        for image in message.images:
            item: dict[str, Any] = {
                "type": "input_image",
                "image_url": image.url,
            }
            if image.detail:
                item["detail"] = image.detail
            content.append(item)
        return content

    @staticmethod
    def _tool_calls(response) -> list[AIToolCall]:
        calls: list[AIToolCall] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "function_call":
                continue
            arguments: dict[str, Any] = {}
            raw_arguments = getattr(item, "arguments", "") or "{}"
            try:
                parsed_arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                parsed_arguments = {}
            if isinstance(parsed_arguments, dict):
                arguments = parsed_arguments
            calls.append(
                AIToolCall(
                    id=getattr(item, "call_id", None) or getattr(item, "id", ""),
                    name=getattr(item, "name", ""),
                    arguments=arguments,
                )
            )
        return calls

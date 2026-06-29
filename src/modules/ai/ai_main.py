import json
import os
from typing import Any

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.discord_guilds import fetch_channel
from src.modules.ai.context import ChannelFetcher, MemberProfileVisibility, build_ai_context, context_to_prompt_block
from src.modules.ai.models import (
    AIMessage,
    AIRequest,
    AIResponse,
    AssistantInput,
    DEFAULT_AI_MODEL,
    MessageModerationInput,
    ModerationVerdict,
)
from src.modules.ai.providers import AIProvider, OpenAIProvider
from src.modules.ai.tools import AIToolRegistry, build_default_tool_registry


MODERATION_SYSTEM_PROMPT = """
You are CyberColors' AI moderation reviewer for a Discord server.
Review the message against the provided server rules and member context.
Return JSON only with these keys:
flagged: boolean
severity: one of none, low, medium, high
categories: array of short strings
reason: short moderator-facing explanation
suggested_action: one of none, watch, warn, mute, kick, ban, manual_review
rule_ids: array of relevant moderation rule ids

Do not take action. Only decide whether a human moderator should review it.
If context is missing, say so in the reason and stay conservative.
""".strip()


MODERATION_STRICTNESS_GUIDANCE = {
    "low": "Only flag clear violations, obvious spam, explicit harassment, or direct rule breaks. Do not flag borderline messages.",
    "standard": "Flag likely violations and suspicious patterns. Avoid punishing ambiguous messages, but send plausible issues to human review.",
    "high": "Flag borderline cases for human review when the message plausibly violates rules or the member context makes it suspicious.",
}


def moderation_system_prompt(strictness: str = "standard") -> str:
    normalized = strictness if strictness in MODERATION_STRICTNESS_GUIDANCE else "standard"
    return (
        f"{MODERATION_SYSTEM_PROMPT}\n\n"
        f"Strictness: {normalized}. {MODERATION_STRICTNESS_GUIDANCE[normalized]}"
    )


ASSISTANT_SYSTEM_PROMPT = """
You are CyberColors, a Discord server assistant.
Answer naturally and concisely. Use provided server context when it is relevant.
Do not invent server facts, admin facts, birthdays, moderation history, or rules.
If the context does not contain the answer, say that you do not have enough server data.
Do not reveal internal moderation cases, notes, monitoring status, or private moderation workspace data.
""".strip()


class AIMain:
    def __init__(
        self,
        provider: AIProvider | None = None,
        model: str | None = None,
        tool_registry: AIToolRegistry | None = None,
        channel_fetcher: ChannelFetcher | None = None,
    ):
        self._provider = provider
        self.ai_model = model or os.getenv("AI_MODEL", DEFAULT_AI_MODEL)
        self.tool_registry = tool_registry or build_default_tool_registry()
        self.channel_fetcher = channel_fetcher or fetch_channel

    @property
    def provider(self) -> AIProvider:
        if self._provider is None:
            self._provider = OpenAIProvider()
        return self._provider

    async def check_message(
        self,
        message: str | MessageModerationInput | Any,
        *,
        session: AsyncSession | None = None,
        include_member_profile: bool = True,
        moderation_strictness: str = "standard",
    ) -> ModerationVerdict:
        moderation_input = self._normalize_moderation_input(message)
        context_block = await self._build_context_block(
            session=session,
            server_id=moderation_input.server_id,
            user_id=moderation_input.author_user_id,
            channel_id=moderation_input.channel_id,
            include_member_profile=include_member_profile,
            member_profile_visibility="moderation",
        )
        request = AIRequest(
            task="moderation",
            model=self.ai_model,
            system_prompt=moderation_system_prompt(moderation_strictness),
            messages=[
                AIMessage(
                    role="user",
                    content=(
                        "Context:\n"
                        f"{context_block}\n\n"
                        "Message metadata:\n"
                        f"{json.dumps(self._moderation_metadata(moderation_input), ensure_ascii=True)}\n\n"
                        "Message content:\n"
                        f"{moderation_input.content}"
                    ),
                )
            ],
            max_output_tokens=600,
            metadata={"task": "moderation", "strictness": moderation_strictness},
        )
        response = await self.provider.complete(request)
        return self._parse_moderation_verdict(response)

    async def answer(
        self,
        assistant_input: str | AssistantInput,
        *,
        session: AsyncSession | None = None,
        include_member_profile: bool = False,
    ) -> AIResponse:
        normalized = (
            AssistantInput(content=assistant_input)
            if isinstance(assistant_input, str)
            else assistant_input
        )
        context_block = await self._build_context_block(
            session=session,
            server_id=normalized.server_id,
            user_id=normalized.author_user_id,
            channel_id=normalized.channel_id,
            include_member_profile=include_member_profile,
            member_profile_visibility="public_answer",
        )
        messages = list(normalized.conversation)
        messages.append(
            AIMessage(
                role="user",
                content=(
                    "Context:\n"
                    f"{context_block}\n\n"
                    "User message:\n"
                    f"{normalized.content}"
                ),
            )
        )
        request = AIRequest(
            task="assistant",
            model=self.ai_model,
            system_prompt=ASSISTANT_SYSTEM_PROMPT,
            messages=messages,
            max_output_tokens=1200,
            metadata={"task": "assistant"},
        )
        return await self.provider.complete(request)

    async def _build_context_block(
        self,
        *,
        session: AsyncSession | None,
        server_id: int | None,
        user_id: int | None,
        channel_id: int | None,
        include_member_profile: bool,
        member_profile_visibility: MemberProfileVisibility,
    ) -> str:
        try:
            context = await build_ai_context(
                session=session,
                server_id=server_id,
                user_id=user_id,
                channel_id=channel_id,
                include_rules=True,
                include_member_profile=include_member_profile,
                member_profile_visibility=member_profile_visibility,
                channel_fetcher=self.channel_fetcher,
            )
        except HTTPException as exc:
            return f"Context lookup failed: {exc.detail}"
        return context_to_prompt_block(context)

    @staticmethod
    def _normalize_moderation_input(message: str | MessageModerationInput | Any) -> MessageModerationInput:
        if isinstance(message, MessageModerationInput):
            return message
        if isinstance(message, str):
            return MessageModerationInput(content=message)

        author = getattr(message, "author", None)
        guild = getattr(message, "guild", None)
        channel = getattr(message, "channel", None)
        author_display_name = None
        if author is not None:
            author_display_name = getattr(author, "display_name", None) or getattr(author, "name", None)
        return MessageModerationInput(
            content=getattr(message, "content", "") or "",
            server_id=getattr(guild, "id", None),
            author_user_id=getattr(author, "id", None),
            channel_id=getattr(channel, "id", None),
            message_id=getattr(message, "id", None),
            author_display_name=author_display_name,
        )

    @staticmethod
    def _moderation_metadata(message: MessageModerationInput) -> dict[str, str | None]:
        return {
            "server_id": str(message.server_id) if message.server_id is not None else None,
            "author_user_id": str(message.author_user_id) if message.author_user_id is not None else None,
            "channel_id": str(message.channel_id) if message.channel_id is not None else None,
            "message_id": str(message.message_id) if message.message_id is not None else None,
            "author_display_name": message.author_display_name,
        }

    @staticmethod
    def _parse_moderation_verdict(response: AIResponse) -> ModerationVerdict:
        content = response.content or "{}"
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return ModerationVerdict(
                flagged=True,
                severity="low",
                categories=["parse_error"],
                reason="AI moderation response was not valid JSON.",
                suggested_action="manual_review",
                raw_response=response,
            )

        severity = payload.get("severity") if payload.get("severity") in {"none", "low", "medium", "high"} else "none"
        suggested_action = (
            payload.get("suggested_action")
            if payload.get("suggested_action") in {"none", "watch", "warn", "mute", "kick", "ban", "manual_review"}
            else "none"
        )
        return ModerationVerdict(
            flagged=bool(payload.get("flagged", False)),
            severity=severity,
            categories=[str(item) for item in payload.get("categories", []) if item],
            reason=str(payload.get("reason", "")),
            suggested_action=suggested_action,
            rule_ids=[str(item) for item in payload.get("rule_ids", []) if item],
            raw_response=response,
        )


ai_main_class = AIMain()

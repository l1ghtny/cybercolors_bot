import asyncio
import os

from src.db.database import get_async_session
from src.modules.ai import ai_main_class
from src.modules.ai.answer_logging import answer_log_started_at, log_ai_answer_attempt
from src.modules.ai.discord_media import ai_images_from_discord_message
from src.modules.ai.models import AIMessage, AssistantInput

DEFAULT_AI_ANSWER_TIMEOUT_SECONDS = 480


class AIAnswerTimeoutError(TimeoutError):
    pass


def _answer_timeout_seconds() -> float:
    raw_value = os.getenv("AI_ANSWER_TIMEOUT_SECONDS")
    if not raw_value:
        return DEFAULT_AI_ANSWER_TIMEOUT_SECONDS
    try:
        timeout = float(raw_value)
    except ValueError:
        return DEFAULT_AI_ANSWER_TIMEOUT_SECONDS
    return max(timeout, 0.001)


async def create_one_response(message, client):
    from src.modules.chat_bot.message_processing import remove_bot_mention
    content = await remove_bot_mention(message, client)
    content = _expand_message_mentions(content, message=message, client=client)
    return await _create_ai_response(
        content=content,
        message=message,
        conversation=[],
    )


async def create_response_to_dialog(message_list, message=None):
    conversation = [
        AIMessage(role=item["role"], content=item["content"], images=item.get("images") or [])
        for item in message_list
        if item.get("role") in {"user", "assistant"} and (item.get("content") or item.get("images"))
    ]
    current_images = []
    if conversation and conversation[-1].role == "user":
        latest_message = conversation.pop()
        content = latest_message.content
        current_images = latest_message.images
    else:
        content = ""
    if message is not None:
        content = _expand_message_mentions(content, message=message, client=None)
    return await _create_ai_response(
        content=content,
        message=message,
        conversation=conversation,
        images=current_images,
    )


async def _create_ai_response(
    *,
    content: str,
    message,
    conversation: list[AIMessage],
    images: list | None = None,
) -> tuple[str | None, int]:
    guild = getattr(message, "guild", None)
    author = getattr(message, "author", None)
    channel = getattr(message, "channel", None)
    assistant_input = AssistantInput(
        content=content,
        server_id=getattr(guild, "id", None),
        author_user_id=getattr(author, "id", None),
        channel_id=getattr(channel, "id", None),
        conversation=conversation,
        images=images if images is not None else (ai_images_from_discord_message(message) if message is not None else []),
        metadata={"message_id": getattr(message, "id", None)},
    )
    started_at = answer_log_started_at()
    async with get_async_session() as session:
        try:
            response = await asyncio.wait_for(
                ai_main_class.answer(
                    assistant_input,
                    session=session,
                    include_member_profile=True,
                    enable_tools=True,
                ),
                timeout=_answer_timeout_seconds(),
            )
        except asyncio.TimeoutError as exc:
            await log_ai_answer_attempt(
                session=session,
                assistant_input=assistant_input,
                status="timeout",
                started_at=started_at,
                error=exc,
            )
            raise AIAnswerTimeoutError("AI answer generation timed out") from exc
        except Exception as exc:
            await log_ai_answer_attempt(
                session=session,
                assistant_input=assistant_input,
                status="error",
                started_at=started_at,
                error=exc,
            )
            raise
        await log_ai_answer_attempt(
            session=session,
            assistant_input=assistant_input,
            status="success" if response.content is not None else "empty_response",
            started_at=started_at,
            response=response,
        )
    return response.content, response.total_tokens


def _expand_message_mentions(content: str, *, message, client) -> str:
    expanded = content
    bot_user = getattr(client, "user", None) if client is not None else None
    for user in getattr(message, "mentions", []) or []:
        if bot_user is not None and user == bot_user:
            continue
        user_id = getattr(user, "id", None)
        if user_id is None:
            continue
        display_name = getattr(user, "display_name", None) or getattr(user, "global_name", None)
        username = getattr(user, "name", None)
        label_parts = [part for part in (display_name, username) if part]
        label = " / ".join(dict.fromkeys(label_parts)) or str(user_id)
        replacement = f"@{label} (user_id: {user_id})"
        expanded = expanded.replace(f"<@{user_id}>", replacement)
        expanded = expanded.replace(f"<@!{user_id}>", replacement)
    return expanded

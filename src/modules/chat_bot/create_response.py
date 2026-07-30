import asyncio
import os

from src.db.models import ServerAISettings
from src.db.database import get_async_session
from src.modules.ai import ai_main_class
from src.modules.ai.answer_logging import answer_log_started_at, log_ai_answer_attempt
from src.modules.ai.discord_media import ai_images_from_discord_message
from src.modules.ai.models import AIMessage, AssistantInput
from src.modules.ai.tool_access import AI_COMPANION_TOOL_NAME_SET, default_ai_companion_tool_names

DEFAULT_AI_ANSWER_TIMEOUT_SECONDS = 60


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


async def create_one_response(message, client, *, locale: str | None = None):
    from src.modules.chat_bot.message_processing import remove_bot_mention
    content = await remove_bot_mention(message, client)
    content = _expand_message_mentions(content, message=message, client=client)
    return await _create_ai_response(
        content=content,
        message=message,
        conversation=[],
        locale=locale,
    )


async def create_response_to_dialog(
    message_list,
    message=None,
    *,
    reply_context: dict | None = None,
    locale: str | None = None,
):
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
        reply_context=reply_context,
        locale=locale,
    )


async def _create_ai_response(
    *,
    content: str,
    message,
    conversation: list[AIMessage],
    images: list | None = None,
    reply_context: dict | None = None,
    locale: str | None = None,
) -> tuple[str | None, int]:
    guild = getattr(message, "guild", None)
    author = getattr(message, "author", None)
    channel = getattr(message, "channel", None)
    role_ids, permission_names, is_owner, is_administrator = _requester_access_context(message)
    assistant_input = AssistantInput(
        content=content,
        server_id=getattr(guild, "id", None),
        author_user_id=getattr(author, "id", None),
        author_role_ids=role_ids,
        author_permission_names=permission_names,
        author_is_owner=is_owner,
        author_is_administrator=is_administrator,
        locale=locale,
        channel_id=getattr(channel, "id", None),
        reply_to_message_id=(reply_context or {}).get("message_id"),
        reply_to_author_user_id=(reply_context or {}).get("author"),
        reply_to_author_display_name=(reply_context or {}).get("author_display_name"),
        reply_to_author_is_bot=bool((reply_context or {}).get("author_is_bot", False)),
        conversation=conversation,
        images=(
            images
            if images is not None
            else (ai_images_from_discord_message(message, detail="high") if message is not None else [])
        ),
        metadata={"message_id": getattr(message, "id", None)},
    )
    started_at = answer_log_started_at()
    async with get_async_session() as session:
        session_get = getattr(session, "get", None)
        settings = (
            await session_get(ServerAISettings, assistant_input.server_id)
            if assistant_input.server_id is not None and callable(session_get)
            else None
        )
        configured_tool_names = (
            settings.answer_enabled_tools
            if settings is not None
            else default_ai_companion_tool_names()
        )
        enabled_tool_names = set(configured_tool_names or []) & AI_COMPANION_TOOL_NAME_SET
        try:
            response = await asyncio.wait_for(
                ai_main_class.answer(
                    assistant_input,
                    session=session,
                    include_member_profile=True,
                    enable_tools=True,
                    enabled_tool_names=enabled_tool_names,
                    command_guidance_mode=(
                        settings.answer_command_guidance_mode
                        if settings is not None
                        else "personalized"
                    ),
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


def _requester_access_context(message) -> tuple[list[int], list[str], bool, bool]:
    author = getattr(message, "author", None)
    guild = getattr(message, "guild", None)
    role_ids = [
        int(role.id)
        for role in (getattr(author, "roles", None) or [])
        if getattr(role, "id", None) is not None
    ]
    permissions = getattr(author, "guild_permissions", None)
    permission_names: list[str] = []
    if permissions is not None:
        to_dict = getattr(permissions, "to_dict", None)
        if callable(to_dict):
            permission_names = sorted(name for name, allowed in to_dict().items() if allowed)
        else:
            try:
                permission_names = sorted(name for name, allowed in permissions if allowed)
            except TypeError:
                permission_names = []
    author_id = getattr(author, "id", None)
    owner_id = getattr(guild, "owner_id", None)
    is_owner = author_id is not None and owner_id is not None and int(author_id) == int(owner_id)
    is_administrator = "administrator" in permission_names
    return role_ids, permission_names, is_owner, is_administrator


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

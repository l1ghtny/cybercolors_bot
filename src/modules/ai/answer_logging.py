from time import monotonic
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import AIAnswerLog
from src.modules.ai.models import AIResponse, AssistantInput
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")

MAX_LOGGED_CONTENT_CHARS = 8000


def answer_log_started_at() -> float:
    return monotonic()


async def log_ai_answer_attempt(
    *,
    session: AsyncSession,
    assistant_input: AssistantInput,
    status: str,
    started_at: float,
    response: AIResponse | None = None,
    error: BaseException | None = None,
) -> None:
    if not hasattr(session, "add"):
        return

    log = AIAnswerLog(
        server_id=assistant_input.server_id,
        channel_id=assistant_input.channel_id,
        message_id=_metadata_int(assistant_input.metadata, "message_id"),
        author_user_id=assistant_input.author_user_id,
        status=status,
        provider=response.provider if response is not None else None,
        model=response.model if response is not None else None,
        response_id=response.id if response is not None else None,
        total_tokens=response.total_tokens if response is not None else 0,
        tool_call_count=response.tool_call_count if response is not None else 0,
        visual_input_count=len(assistant_input.images),
        conversation_message_count=len(assistant_input.conversation),
        request_content=_truncate(assistant_input.content),
        response_content=_truncate(response.content) if response is not None else None,
        error_type=type(error).__name__ if error is not None else None,
        error_message=_truncate(str(error)) if error is not None else None,
        duration_ms=max(int((monotonic() - started_at) * 1000), 0),
    )

    try:
        session.add(log)
        if hasattr(session, "flush"):
            await session.flush()
        if hasattr(session, "commit"):
            await session.commit()
    except Exception:
        if hasattr(session, "rollback"):
            await session.rollback()
        logger.exception(
            "Failed to log AI answer attempt in guild %s channel %s message %s",
            assistant_input.server_id,
            assistant_input.channel_id,
            _metadata_int(assistant_input.metadata, "message_id"),
        )


def _truncate(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= MAX_LOGGED_CONTENT_CHARS:
        return value
    return f"{value[:MAX_LOGGED_CONTENT_CHARS]}...[truncated]"


def _metadata_int(metadata: dict[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

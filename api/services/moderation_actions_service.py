from datetime import datetime
import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionCreate, ModerationActionRead
from api.models.moderation_cases import DeletedMessageCreateModel, DeletedMessageReadModel
from api.services.discord_guilds import create_channel_message, fetch_guild_channels
from api.services.moderation_core import build_actor, naive_utcnow, to_deleted_message_read, to_moderation_history
from api.services.moderation_queries import (
    query_deleted_messages,
    query_deleted_messages_for_action,
    query_moderation_actions,
)
from src.db.models import (
    DeletedMessage,
    GlobalUser,
    ModerationAction,
    ModerationActionDeletedMessageLink,
    ModerationRule,
    ServerModerationSettings,
)
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists

logger = logging.getLogger("api.moderation")


def _truncate(value: str, limit: int = 600) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return f"{value.isoformat()}Z"


async def _resolve_username(session: AsyncSession, user_id: int) -> str | None:
    user = await session.get(GlobalUser, user_id)
    if not user:
        return None
    return user.username


async def _send_action_to_mod_log(
    session: AsyncSession,
    action: ModerationAction,
) -> None:
    settings = await session.get(ServerModerationSettings, action.server_id)
    if not settings or not settings.mod_log_channel_id:
        return

    moderator_username = await _resolve_username(session, action.moderator_user_id)
    target_username = await _resolve_username(session, action.target_user_id)
    lines = [
        f"**Action:** `{action.action_type.value}`",
        f"**Target:** <@{action.target_user_id}> (`{target_username or 'unknown'}`, `{action.target_user_id}`)",
        f"**Moderator:** <@{action.moderator_user_id}> (`{moderator_username or 'unknown'}`, `{action.moderator_user_id}`)",
        f"**Reason:** {_truncate(action.reason, limit=1000)}",
    ]
    if action.commentary:
        lines.append(f"**Commentary:** {_truncate(action.commentary, limit=1000)}")
    if action.rule_id:
        lines.append(f"**Rule ID:** `{action.rule_id}`")
    if action.expires_at:
        lines.append(f"**Expires At:** `{_format_dt(action.expires_at)}`")
    lines.append(f"**Action ID:** `{action.id}`")
    message = "[MODERATION LOG]\n" + "\n".join(lines)
    if len(message) > 1900:
        message = _truncate(message, limit=1900)

    try:
        await create_channel_message(channel_id=settings.mod_log_channel_id, content=message)
    except Exception as error:
        logger.warning(
            "Failed to send moderation action log to channel %s for server %s: %s",
            settings.mod_log_channel_id,
            action.server_id,
            error,
        )


async def create_action(
    session: AsyncSession,
    action: ModerationActionCreate,
    moderator_user_id: int,
) -> ModerationAction:
    mock_user = type(
        "MockUser",
        (),
        {
            "id": action.target_user_id,
            "name": action.target_user_name,
            "joined_at": action.target_user_joined_at,
            "nick": action.target_user_server_nickname,
        },
    )()
    mock_server = type("MockServer", (), {"id": action.server_id, "name": action.server_name})()

    await check_if_server_exists(mock_server, session)
    await check_if_user_exists(mock_user, mock_server, session)

    resolved_commentary = action.commentary.strip() if action.commentary else None
    resolved_reason = action.reason.strip() if action.reason else None
    resolved_rule_id = None

    if action.rule_id is not None:
        rule = await session.get(ModerationRule, action.rule_id)
        if not rule or not rule.is_active or rule.server_id != action.server_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid moderation rule for this server",
            )
        resolved_rule_id = rule.id
        base_reason = f"{rule.code} {rule.title}".strip() if rule.code else rule.title
        resolved_reason = f"{base_reason}\nКомментарий: {resolved_commentary}" if resolved_commentary else base_reason

    if not resolved_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either reason or rule_id must be provided",
        )

    db_action = ModerationAction(
        action_type=action.action_type,
        moderator_user_id=moderator_user_id,
        reason=resolved_reason,
        rule_id=resolved_rule_id,
        commentary=resolved_commentary,
        expires_at=action.expires_at,
        target_user_id=action.target_user_id,
        server_id=action.server_id,
    )
    session.add(db_action)
    await session.flush()
    await session.refresh(db_action)
    await _send_action_to_mod_log(session=session, action=db_action)
    return db_action


async def get_user_history_by_search(
    session: AsyncSession,
    server_id: int,
    search: str,
) -> list[ModerationActionRead]:
    if search.isdigit():
        target_user_id = int(search)
    else:
        user = (await session.exec(select(GlobalUser).where(GlobalUser.username == search))).one_or_none()
        if not user:
            return []
        target_user_id = user.discord_id

    actions = await query_moderation_actions(
        session=session,
        server_id=server_id,
        target_user_id=target_user_id,
    )
    return to_moderation_history(actions)


async def get_server_history(
    session: AsyncSession,
    server_id: int,
    target_user_id: str | None = None,
    limit: int = 500,
) -> list[ModerationActionRead]:
    actions = await query_moderation_actions(
        session=session,
        server_id=server_id,
        target_user_id=int(target_user_id) if target_user_id else None,
        limit=limit,
    )
    return to_moderation_history(actions)


async def _get_channel_names(server_id: int) -> dict[int, str]:
    try:
        channels = await fetch_guild_channels(server_id)
        return {int(ch["id"]): ch.get("name", "") for ch in channels}
    except Exception:
        return {}


async def add_deleted_message_for_action(
    session: AsyncSession,
    action_id: UUID,
    body: DeletedMessageCreateModel,
    linked_by_user_id: int,
) -> DeletedMessageReadModel:
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    server_id = action.server_id
    await build_actor(session, server_id, linked_by_user_id, require_membership=True)

    author_user_id = int(body.author_user_id) if body.author_user_id else None
    deleted_by_user_id = int(body.deleted_by_user_id) if body.deleted_by_user_id else None
    if author_user_id:
        await build_actor(session, server_id, author_user_id)
    if deleted_by_user_id:
        await build_actor(session, server_id, deleted_by_user_id)

    deleted_message = DeletedMessage(
        server_id=server_id,
        message_id=int(body.message_id),
        channel_id=int(body.channel_id),
        author_user_id=author_user_id,
        content=body.content,
        attachments_json=body.attachments_json,
        deleted_at=body.deleted_at or naive_utcnow(),
        deleted_by_user_id=deleted_by_user_id,
    )
    session.add(deleted_message)
    await session.flush()
    await session.refresh(deleted_message)

    session.add(
        ModerationActionDeletedMessageLink(
            moderation_action_id=action_id,
            deleted_message_id=deleted_message.id,
            linked_by_user_id=linked_by_user_id,
        )
    )
    await session.flush()
    return await to_deleted_message_read(deleted_message, session)


async def link_existing_deleted_message_to_action(
    session: AsyncSession,
    action_id: UUID,
    deleted_message_id: UUID,
    linked_by_user_id: int,
) -> DeletedMessageReadModel:
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    deleted_message = await session.get(DeletedMessage, deleted_message_id)
    if not deleted_message or deleted_message.server_id != action.server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deleted message not found")

    await build_actor(session, action.server_id, linked_by_user_id, require_membership=True)

    existing_link = (
        await session.exec(
            select(ModerationActionDeletedMessageLink).where(
                ModerationActionDeletedMessageLink.moderation_action_id == action_id,
                ModerationActionDeletedMessageLink.deleted_message_id == deleted_message_id,
            )
        )
    ).first()
    if not existing_link:
        session.add(
            ModerationActionDeletedMessageLink(
                moderation_action_id=action_id,
                deleted_message_id=deleted_message_id,
                linked_by_user_id=linked_by_user_id,
            )
        )
        await session.flush()

    channel_names = await _get_channel_names(action.server_id)
    return await to_deleted_message_read(
        deleted_message,
        session,
        channel_name=channel_names.get(deleted_message.channel_id),
    )


async def get_deleted_messages_for_action(
    session: AsyncSession,
    action_id: UUID,
) -> list[DeletedMessageReadModel]:
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    deleted_messages = await query_deleted_messages_for_action(session=session, action_id=action_id)
    channel_names = await _get_channel_names(action.server_id)
    return [
        await to_deleted_message_read(item, session, channel_name=channel_names.get(item.channel_id))
        for item in deleted_messages
    ]


async def browse_deleted_messages_for_server(
    session: AsyncSession,
    server_id: int,
    author_user_id: str | None = None,
    channel_id: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[DeletedMessageReadModel]:
    messages = await query_deleted_messages(
        session=session,
        server_id=server_id,
        author_user_id=int(author_user_id) if author_user_id else None,
        channel_id=int(channel_id) if channel_id else None,
        since=since,
        limit=limit,
    )
    channel_names = await _get_channel_names(server_id)
    return [
        await to_deleted_message_read(item, session, channel_name=channel_names.get(item.channel_id))
        for item in messages
    ]

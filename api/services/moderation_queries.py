from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import (
    DeletedMessage,
    ModerationAction,
    ModerationActionDeletedMessageLink,
    ModerationActionRuleCitation,
)


async def query_deleted_messages(
    session: AsyncSession,
    server_id: int,
    author_user_id: int | None = None,
    channel_id: int | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[DeletedMessage]:
    statement = select(DeletedMessage).where(DeletedMessage.server_id == server_id)
    if author_user_id is not None:
        statement = statement.where(DeletedMessage.author_user_id == author_user_id)
    if channel_id is not None:
        statement = statement.where(DeletedMessage.channel_id == channel_id)
    if since is not None:
        statement = statement.where(DeletedMessage.deleted_at >= since)

    statement = statement.order_by(DeletedMessage.deleted_at.desc()).limit(limit)
    return (await session.exec(statement)).all()


async def query_deleted_messages_for_action(
    session: AsyncSession,
    action_id: UUID,
) -> list[DeletedMessage]:
    statement = (
        select(DeletedMessage)
        .join(
            ModerationActionDeletedMessageLink,
            ModerationActionDeletedMessageLink.deleted_message_id == DeletedMessage.id,
        )
        .where(ModerationActionDeletedMessageLink.moderation_action_id == action_id)
        .order_by(DeletedMessage.deleted_at.desc())
    )
    return (await session.exec(statement)).all()


async def query_moderation_actions(
    session: AsyncSession,
    server_id: int,
    target_user_id: int | None = None,
    limit: int | None = None,
) -> list[ModerationAction]:
    statement = select(ModerationAction).where(ModerationAction.server_id == server_id)
    if target_user_id is not None:
        statement = statement.where(ModerationAction.target_user_id == target_user_id)
    statement = statement.options(
        selectinload(ModerationAction.global_user_moderator),
        selectinload(ModerationAction.global_user_target),
        selectinload(ModerationAction.rule),
        selectinload(ModerationAction.case),
        selectinload(ModerationAction.rule_citations).selectinload(ModerationActionRuleCitation.rule),
    ).order_by(ModerationAction.created_at.desc())
    if limit is not None:
        statement = statement.limit(limit)
    return (await session.exec(statement)).all()

import json
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionRead
from api.models.moderation_cases import (
    DeletedMessageAttachmentModel,
    DeletedMessageReadModel,
    ModerationActorModel,
    ModerationCaseReadModel,
    ModerationCaseUserReadModel,
)
from api.models.user_profiles import NicknameRecordModel
from src.db.models import (
    DeletedMessage,
    GlobalUser,
    ModerationAction,
    ModerationCase,
    ModerationCaseActionLink,
    ModerationCaseUser,
    PastNickname,
    Server,
    User,
)


def naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_or_create_server_record(server_id: int, session: AsyncSession) -> Server:
    server = await session.get(Server, server_id)
    if server:
        return server
    server = Server(server_id=server_id, server_name=str(server_id))
    session.add(server)
    await session.flush()
    return server


async def get_or_create_user_membership(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    username: str | None = None,
    server_nickname: str | None = None,
) -> tuple[GlobalUser, User]:
    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        global_user = GlobalUser(discord_id=user_id, username=username)
        session.add(global_user)
        await session.flush()
    elif username and global_user.username != username:
        global_user.username = username
        session.add(global_user)

    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    if not membership:
        membership = User(
            user_id=user_id,
            server_id=server_id,
            server_nickname=server_nickname,
            is_member=True,
        )
        session.add(membership)
        await session.flush()
    else:
        if server_nickname:
            membership.server_nickname = server_nickname
        membership.is_member = True
        session.add(membership)

    return global_user, membership


def to_nickname_record(item: PastNickname) -> NicknameRecordModel:
    return NicknameRecordModel(
        id=str(item.id),
        user_id=str(item.user_id),
        server_id=str(item.server_id) if item.server_id is not None else None,
        server_name=item.server_name,
        nickname=item.discord_name,
        recorded_at=item.recorded_at,
    )


async def get_nickname_history(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    limit: int,
) -> list[PastNickname]:
    server = await session.get(Server, server_id)
    base = select(PastNickname).where(PastNickname.user_id == user_id)
    if server and server.server_name:
        base = base.where(
            or_(
                PastNickname.server_id == server_id,
                (PastNickname.server_id.is_(None) & (PastNickname.server_name == server.server_name)),
            )
        )
    else:
        base = base.where(PastNickname.server_id == server_id)

    rows = (await session.exec(base.order_by(PastNickname.recorded_at.desc()).limit(limit))).all()
    if rows:
        return rows

    return (
        await session.exec(
            select(PastNickname)
            .where(PastNickname.user_id == user_id)
            .order_by(PastNickname.recorded_at.desc())
            .limit(limit)
        )
    ).all()


async def get_case_or_404(server_id: int, case_id: UUID, session: AsyncSession) -> ModerationCase:
    moderation_case = await session.get(ModerationCase, case_id)
    if not moderation_case or moderation_case.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation case not found")
    return moderation_case


async def build_actor(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    require_membership: bool = False,
) -> ModerationActorModel:
    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")

    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    if require_membership and not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} is not a member of server {server_id}",
        )

    display_name = (
        membership.server_nickname
        if membership and membership.server_nickname
        else (global_user.username or str(user_id))
    )
    return ModerationActorModel(
        user_id=str(user_id),
        username=global_user.username,
        server_nickname=membership.server_nickname if membership else None,
        display_name=display_name,
        avatar_hash=global_user.avatar_hash,
    )


async def build_optional_actor(
    session: AsyncSession,
    server_id: int,
    user_id: int | None,
) -> ModerationActorModel | None:
    if user_id is None:
        return None
    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        return ModerationActorModel(
            user_id=str(user_id),
            username=None,
            server_nickname=None,
            display_name=str(user_id),
            avatar_hash=None,
        )
    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    return ModerationActorModel(
        user_id=str(user_id),
        username=global_user.username,
        server_nickname=membership.server_nickname if membership else None,
        display_name=(
            membership.server_nickname
            if membership and membership.server_nickname
            else (global_user.username or str(user_id))
        ),
        avatar_hash=global_user.avatar_hash,
    )


async def to_case_read(moderation_case: ModerationCase, session: AsyncSession) -> ModerationCaseReadModel:
    target_user = await build_actor(session, moderation_case.server_id, moderation_case.target_user_id)
    opened_by = await build_actor(session, moderation_case.server_id, moderation_case.opened_by_user_id)
    closed_by = await build_optional_actor(session, moderation_case.server_id, moderation_case.closed_by_user_id)

    case_user_links = (
        await session.exec(
            select(ModerationCaseUser)
            .where(ModerationCaseUser.case_id == moderation_case.id)
            .order_by(ModerationCaseUser.added_at.asc())
        )
    ).all()
    case_users: list[ModerationCaseUserReadModel] = []
    for link in case_user_links:
        case_users.append(
            ModerationCaseUserReadModel(
                id=str(link.id),
                role=link.role,
                added_at=link.added_at,
                added_by=await build_actor(session, moderation_case.server_id, link.added_by_user_id),
                user=await build_actor(session, moderation_case.server_id, link.user_id),
            )
        )

    linked_actions = (
        await session.exec(
            select(ModerationCaseActionLink.moderation_action_id).where(
                ModerationCaseActionLink.case_id == moderation_case.id
            )
        )
    ).all()

    return ModerationCaseReadModel(
        id=str(moderation_case.id),
        server_id=str(moderation_case.server_id),
        title=moderation_case.title,
        summary=moderation_case.summary,
        status=moderation_case.status,
        created_at=moderation_case.created_at,
        closed_at=moderation_case.closed_at,
        target_user=target_user,
        opened_by=opened_by,
        closed_by=closed_by,
        users=case_users,
        linked_action_ids=[str(action_id) for action_id in linked_actions],
    )


async def to_deleted_message_read(
    deleted_message: DeletedMessage,
    session: AsyncSession,
    channel_name: str | None = None,
) -> DeletedMessageReadModel:
    author = await build_optional_actor(session, deleted_message.server_id, deleted_message.author_user_id)
    deleted_by = await build_optional_actor(session, deleted_message.server_id, deleted_message.deleted_by_user_id)
    attachments: list[DeletedMessageAttachmentModel] = []
    if deleted_message.attachments_json:
        try:
            parsed = json.loads(deleted_message.attachments_json)
            if isinstance(parsed, list):
                attachments = [
                    DeletedMessageAttachmentModel.model_validate(item)
                    for item in parsed
                    if isinstance(item, dict)
                ]
        except json.JSONDecodeError:
            attachments = []

    return DeletedMessageReadModel(
        id=str(deleted_message.id),
        server_id=str(deleted_message.server_id),
        message_id=str(deleted_message.message_id),
        channel_id=str(deleted_message.channel_id),
        channel_name=channel_name,
        content=deleted_message.content,
        attachments_json=deleted_message.attachments_json,
        attachments=attachments,
        deleted_at=deleted_message.deleted_at,
        author=author,
        deleted_by=deleted_by,
    )


def to_moderation_history(result: Sequence[ModerationAction]) -> list[ModerationActionRead]:
    return [
        ModerationActionRead(
            id=str(action.id),
            action_type=action.action_type,
            server_id=str(action.server_id),
            target_user_id=str(action.target_user_id),
            target_user_username=str(action.global_user_target.username),
            moderator_user_id=str(action.moderator_user_id),
            moderator_username=str(action.global_user_moderator.username),
            reason=action.reason,
            rule_id=str(action.rule_id) if action.rule_id is not None else None,
            rule_code=action.rule.code if action.rule else None,
            rule_title=action.rule.title if action.rule else None,
            commentary=action.commentary,
            created_at=action.created_at,
            expires_at=action.expires_at,
            is_active=action.is_active,
        )
        for action in result
    ]

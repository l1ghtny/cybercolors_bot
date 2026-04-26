import json
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionRead
from api.models.moderation_cases import (
    DeletedMessageAttachmentModel,
    DeletedMessageReadModel,
    ModerationActionSummaryModel,
    ModerationActorModel,
    ModerationCaseReadModel,
    ModerationRuleRef,
    ModerationCaseUserReadModel,
)
from api.models.user_profiles import NicknameRecordModel
from src.db.models import (
    DeletedMessage,
    GlobalUser,
    ModerationAction,
    ModerationCase,
    ModerationCaseActionLink,
    ModerationCaseRuleCitation,
    ModerationCaseUser,
    ModerationActionRuleCitation,
    PastNickname,
    Server,
    User,
)


def naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


SYSTEM_ACTOR = ModerationActorModel(
    user_id="system",
    username="System",
    server_nickname=None,
    display_name="System",
    avatar_hash=None,
)


def get_system_actor() -> ModerationActorModel:
    return ModerationActorModel.model_validate(SYSTEM_ACTOR.model_dump())


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


def _rule_ref_from_action_citation(citation: ModerationActionRuleCitation) -> ModerationRuleRef:
    if citation.rule_id is not None and citation.rule is not None:
        return ModerationRuleRef(
            id=str(citation.rule.id),
            code=citation.rule.code,
            title=citation.rule.title,
            deleted=False,
        )

    title = (citation.rule_title_snapshot or "Rule").strip() or "Rule"
    if "(deleted)" not in title.lower():
        title = f"{title} (deleted)"
    return ModerationRuleRef(
        id=None,
        code=citation.rule_code_snapshot,
        title=title,
        deleted=True,
    )


def _rule_ref_from_case_citation(citation: ModerationCaseRuleCitation) -> ModerationRuleRef:
    if citation.rule_id is not None and citation.rule is not None:
        return ModerationRuleRef(
            id=str(citation.rule.id),
            code=citation.rule.code,
            title=citation.rule.title,
            deleted=False,
        )

    title = (citation.rule_title_snapshot or "Rule").strip() or "Rule"
    if "(deleted)" not in title.lower():
        title = f"{title} (deleted)"
    return ModerationRuleRef(
        id=None,
        code=citation.rule_code_snapshot,
        title=title,
        deleted=True,
    )


async def _to_action_summary(
    session: AsyncSession,
    action: ModerationAction,
) -> ModerationActionSummaryModel:
    return ModerationActionSummaryModel(
        id=str(action.id),
        action_type=action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type),
        target_user=await build_actor(session, action.server_id, action.target_user_id),
        moderator=await build_actor(session, action.server_id, action.moderator_user_id),
        reason=action.reason,
        created_at=action.created_at,
        expires_at=action.expires_at,
        is_active=action.is_active,
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

    linked_action_ids_secondary = (
        await session.exec(
            select(ModerationCaseActionLink.moderation_action_id).where(
                ModerationCaseActionLink.case_id == moderation_case.id
            )
        )
    ).all()
    action_ids_secondary = list(linked_action_ids_secondary)
    action_statement = select(ModerationAction).where(
        ModerationAction.server_id == moderation_case.server_id,
        ModerationAction.case_id == moderation_case.id,
    )
    if action_ids_secondary:
        action_statement = select(ModerationAction).where(
            ModerationAction.server_id == moderation_case.server_id,
            or_(
                ModerationAction.case_id == moderation_case.id,
                ModerationAction.id.in_(action_ids_secondary),
            ),
        )
    action_statement = action_statement.options(
        selectinload(ModerationAction.rule_citations).selectinload(ModerationActionRuleCitation.rule),
    ).order_by(ModerationAction.created_at.desc())
    linked_actions = (await session.exec(action_statement)).all()
    linked_action_summaries = [await _to_action_summary(session, action) for action in linked_actions]
    linked_action_ids = [str(action.id) for action in linked_actions]

    case_rule_citations = (
        await session.exec(
            select(ModerationCaseRuleCitation)
            .where(ModerationCaseRuleCitation.case_id == moderation_case.id)
            .options(selectinload(ModerationCaseRuleCitation.rule))
            .order_by(ModerationCaseRuleCitation.cited_at.asc(), ModerationCaseRuleCitation.id.asc())
        )
    ).all()
    case_rules = [_rule_ref_from_case_citation(item) for item in case_rule_citations]

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
        rules=case_rules,
        linked_actions=linked_action_summaries,
        linked_action_ids=linked_action_ids,
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
    payload: list[ModerationActionRead] = []
    for action in result:
        rule_refs: list[ModerationRuleRef] = []
        if action.rule_citations:
            sorted_citations = sorted(
                action.rule_citations,
                key=lambda item: (item.cited_at or datetime.min.replace(tzinfo=None), str(item.id)),
            )
            rule_refs = [_rule_ref_from_action_citation(item) for item in sorted_citations]
        elif action.rule is not None:
            rule_refs = [
                ModerationRuleRef(
                    id=str(action.rule.id),
                    code=action.rule.code,
                    title=action.rule.title,
                    deleted=False,
                )
            ]

        primary_rule = rule_refs[0] if rule_refs else None
        payload.append(
            ModerationActionRead(
                id=str(action.id),
                action_type=action.action_type,
                server_id=str(action.server_id),
                target_user_id=str(action.target_user_id),
                target_user_username=(
                    action.global_user_target.username
                    if action.global_user_target and action.global_user_target.username
                    else str(action.target_user_id)
                ),
                moderator_user_id=str(action.moderator_user_id),
                moderator_username=(
                    action.global_user_moderator.username
                    if action.global_user_moderator and action.global_user_moderator.username
                    else str(action.moderator_user_id)
                ),
                reason=action.reason,
                rule_id=primary_rule.id if primary_rule is not None else (str(action.rule_id) if action.rule_id else None),
                rule_code=primary_rule.code if primary_rule is not None else (action.rule.code if action.rule else None),
                rule_title=primary_rule.title if primary_rule is not None else (action.rule.title if action.rule else None),
                rules=rule_refs,
                case_id=str(action.case_id) if action.case_id is not None else None,
                case_title=action.case.title if action.case is not None else None,
                commentary=action.commentary,
                created_at=action.created_at,
                expires_at=action.expires_at,
                is_active=action.is_active,
            )
        )
    return payload

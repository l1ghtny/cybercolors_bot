from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.bot_replies import ReplyDuplicateResponseModel
from src.db.models import GlobalUser, Replies, Server, Triggers


async def _ensure_server_exists(session: AsyncSession, server_id: int) -> None:
    server = await session.get(Server, server_id)
    if server:
        return
    session.add(Server(server_id=server_id, server_name=str(server_id)))
    await session.flush()


async def _ensure_global_user_exists(session: AsyncSession, user_id: int) -> None:
    user = await session.get(GlobalUser, user_id)
    if user:
        return
    session.add(GlobalUser(discord_id=user_id, username=None))
    await session.flush()


async def duplicate_selected_replies(
    session: AsyncSession,
    source_server_id: int,
    target_server_id: int,
    reply_ids: list[UUID],
    actor_user_id: int,
) -> ReplyDuplicateResponseModel:
    unique_ids = list(dict.fromkeys(reply_ids))
    requested_replies = len(unique_ids)

    source_replies = (
        await session.exec(
            select(Replies).where(
                Replies.server_id == source_server_id,
                Replies.id.in_(unique_ids),
            )
        )
    ).all()

    source_reply_ids = {item.id for item in source_replies}
    missing_reply_ids = [str(item_id) for item_id in unique_ids if item_id not in source_reply_ids]

    if not source_replies:
        return ReplyDuplicateResponseModel(
            source_server_id=str(source_server_id),
            target_server_id=str(target_server_id),
            requested_replies=requested_replies,
            duplicated_replies=0,
            reused_replies=0,
            duplicated_triggers=0,
            skipped_triggers=0,
            missing_reply_ids=missing_reply_ids,
        )

    await _ensure_server_exists(session, target_server_id)
    await _ensure_global_user_exists(session, actor_user_id)

    source_trigger_rows = (
        await session.exec(
            select(Triggers).where(Triggers.reply_id.in_(list(source_reply_ids)))
        )
    ).all()
    triggers_by_source_reply: dict[UUID, list[str]] = {}
    for trigger in source_trigger_rows:
        triggers_by_source_reply.setdefault(trigger.reply_id, []).append(trigger.message)

    bot_replies = list({reply.bot_reply for reply in source_replies})
    existing_target_replies = (
        await session.exec(
            select(Replies).where(
                Replies.server_id == target_server_id,
                Replies.bot_reply.in_(bot_replies),
            )
        )
    ).all()
    target_reply_by_text = {reply.bot_reply: reply for reply in existing_target_replies}

    duplicated_replies = 0
    reused_replies = 0
    target_reply_ids: set[UUID] = {reply.id for reply in existing_target_replies}

    for source_reply in source_replies:
        existing_target = target_reply_by_text.get(source_reply.bot_reply)
        if existing_target:
            reused_replies += 1
            continue

        created_target = Replies(
            server_id=target_server_id,
            bot_reply=source_reply.bot_reply,
            created_by_id=actor_user_id,
        )
        session.add(created_target)
        await session.flush()
        target_reply_by_text[source_reply.bot_reply] = created_target
        target_reply_ids.add(created_target.id)
        duplicated_replies += 1

    existing_trigger_pairs: set[tuple[UUID, str]] = set()
    if target_reply_ids:
        existing_target_triggers = (
            await session.exec(
                select(Triggers).where(Triggers.reply_id.in_(list(target_reply_ids)))
            )
        ).all()
        existing_trigger_pairs = {(item.reply_id, item.message) for item in existing_target_triggers}

    duplicated_triggers = 0
    skipped_triggers = 0
    for source_reply in source_replies:
        target_reply = target_reply_by_text[source_reply.bot_reply]
        for trigger_text in triggers_by_source_reply.get(source_reply.id, []):
            key = (target_reply.id, trigger_text)
            if key in existing_trigger_pairs:
                skipped_triggers += 1
                continue
            session.add(Triggers(message=trigger_text, reply_id=target_reply.id))
            existing_trigger_pairs.add(key)
            duplicated_triggers += 1

    await session.flush()
    return ReplyDuplicateResponseModel(
        source_server_id=str(source_server_id),
        target_server_id=str(target_server_id),
        requested_replies=requested_replies,
        duplicated_replies=duplicated_replies,
        reused_replies=reused_replies,
        duplicated_triggers=duplicated_triggers,
        skipped_triggers=skipped_triggers,
        missing_reply_ids=missing_reply_ids,
    )

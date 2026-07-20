import json
from datetime import datetime, timezone

import discord as d
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import get_async_session
from src.db.models import (
    AttachmentLog,
    DeletedMessage,
    GlobalUser,
    MessageClaim,
    MessageLog,
    ModerationActionDeletedMessageLink,
    ModerationActionMessageLink,
    Server,
    TempVoiceLog,
    User,
)


def _as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _member_joined_server_at(user: d.Member | d.User) -> datetime | None:
    if not isinstance(user, d.Member):
        return None
    return _as_naive_utc(getattr(user, "joined_at", None))

async def ensure_message_foreign_keys(message: d.Message, session: AsyncSession) -> None:
    """
    Ensure FK dependencies for message_log exist in the same transaction as claim insert.
    This avoids race conditions where background user/server upserts happen too late.
    """
    guild = message.guild
    author = message.author
    if guild is None or author is None:
        return

    server_icon = getattr(guild, "icon", None)
    icon_url = str(server_icon.url) if server_icon else None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.exec(
        pg_insert(Server)
        .values(
            server_id=guild.id,
            server_name=guild.name,
            icon=icon_url,
            bot_active=True,
            bot_presence_updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[Server.server_id],
            set_={
                "server_name": guild.name,
                "icon": icon_url,
                "bot_active": True,
                "bot_left_at": None,
                "bot_presence_updated_at": now,
            },
        )
    )

    display_avatar = getattr(author, "display_avatar", None)
    avatar_url = str(display_avatar.url) if display_avatar else None
    joined_discord = getattr(author, "created_at", None) or getattr(author, "joined_at", None)
    await session.exec(
        pg_insert(GlobalUser)
        .values(
            discord_id=author.id,
            username=author.name,
            joined_discord=joined_discord,
            avatar_hash=avatar_url,
        )
        .on_conflict_do_update(
            index_elements=[GlobalUser.discord_id],
            set_={
                "username": author.name,
                "avatar_hash": avatar_url,
            },
        )
    )


async def check_if_user_exists(user: d.Member | d.User, server: d.Guild, session: AsyncSession):
    """Checks if a user and their server membership exist, creating or updating them if needed."""
    query = select(GlobalUser).where(GlobalUser.discord_id == user.id)
    result = await session.exec(query)
    user_in_db = result.first()

    display_avatar = getattr(user, "display_avatar", None)
    avatar_url = str(display_avatar.url) if display_avatar else None
    joined_discord = getattr(user, "created_at", None) or getattr(user, "joined_at", None)
    joined_server_at = _member_joined_server_at(user)
    if not user_in_db:
        new_user = GlobalUser(
            discord_id=user.id,
            username=user.name,
            joined_discord=joined_discord,
            avatar_hash=avatar_url,
        )
        session.add(new_user)
        await session.flush()
        user_in_db = new_user
    else:
        changed = False
        if user_in_db.username != user.name:
            user_in_db.username = user.name
            changed = True
        if user_in_db.avatar_hash != avatar_url:
            user_in_db.avatar_hash = avatar_url
            changed = True
        if changed:
            session.add(user_in_db)

    if isinstance(user, d.Member):
        membership = (
            await session.exec(
                select(User).where(
                    User.user_id == user.id,
                    User.server_id == server.id,
                )
            )
        ).first()
        if membership is None:
            await add_user_to_current_server(user_in_db, server, user.nick, joined_server_at, session)
        else:
            changed = False
            if membership.server_nickname != user.nick:
                membership.server_nickname = user.nick
                changed = True
            if not membership.is_member:
                membership.is_member = True
                changed = True
            if membership.left_server_at is not None:
                membership.left_server_at = None
                changed = True
            if joined_server_at is not None and membership.joined_server_at != joined_server_at:
                membership.joined_server_at = joined_server_at
                changed = True
            if changed:
                session.add(membership)


async def add_user_to_current_server(
    user: GlobalUser,
    server: d.Guild,
    server_nickname: str | None,
    joined_server_at: datetime | None,
    session: AsyncSession,
):
    """Adds a server membership link for a global user. Uses the provided session."""
    session.add(
        User(
            user_id=user.discord_id,
            server_id=server.id,
            server_nickname=server_nickname,
            joined_server_at=joined_server_at,
            left_server_at=None,
            is_member=True,
        )
    )


async def check_if_server_exists(server: d.Guild, session: AsyncSession):
    """Checks if a server exists in the DB, creating or updating it if needed."""
    query = select(Server).where(Server.server_id == server.id)
    result = await session.exec(query)
    server_in_db = result.first()

    server_icon = getattr(server, "icon", None)
    icon_url = str(server_icon.url) if server_icon else None
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if not server_in_db:
        session.add(
            Server(
                server_id=server.id,
                server_name=server.name,
                icon=icon_url,
                bot_active=True,
                bot_joined_at=now,
                bot_presence_updated_at=now,
            )
        )
    else:
        changed = False
        if server_in_db.server_name != server.name:
            server_in_db.server_name = server.name
            changed = True
        if server_in_db.icon != icon_url:
            server_in_db.icon = icon_url
            changed = True
        if not server_in_db.bot_active:
            server_in_db.bot_active = True
            server_in_db.bot_left_at = None
            if server_in_db.bot_joined_at is None:
                server_in_db.bot_joined_at = now
            changed = True
        server_in_db.bot_presence_updated_at = now
        changed = True
        if changed:
            session.add(server_in_db)


async def log_message(message: d.Message, session: AsyncSession):
    """Logs a message to the message_log table for later retrieval (e.g., if deleted)."""
    temp_log = (
        await session.exec(
            select(TempVoiceLog).where(
                TempVoiceLog.server_id == message.guild.id,
                TempVoiceLog.channel_id == message.channel.id,
                TempVoiceLog.deleted_at.is_(None),
            )
        )
    ).first()
    insert_stmt = (
        pg_insert(MessageLog)
        .values(
            message_id=message.id,
            log_id=temp_log.id if temp_log else None,
            user_id=message.author.id,
            channel_id=message.channel.id,
            content=message.content,
            created_at=message.created_at.replace(tzinfo=None),
            reply_to_message_id=message.reference.message_id if message.reference else None,
            server_id=message.guild.id,
        )
        .on_conflict_do_nothing(index_elements=[MessageLog.message_id])
        .returning(MessageLog.message_id)
    )
    created_row = (await session.exec(insert_stmt)).first()
    message_created = created_row is not None

    existing_storage_keys: set[str] = set()
    if not message_created and message.attachments:
        attachments_result = await session.exec(
            select(AttachmentLog).where(AttachmentLog.message_id == message.id)
        )
        existing_storage_keys = {item.storage_key for item in attachments_result.all()}

    for attachment in message.attachments:
        if attachment.url in existing_storage_keys:
            continue
        session.add(
            AttachmentLog(
                message_id=message.id,
                storage_key=attachment.url,
                file_name=attachment.filename,
                content_type=attachment.content_type or "application/octet-stream",
            )
        )
    return message_created


async def claim_message_for_processing(message: d.Message) -> bool:
    """
    Atomically claims a message for processing using a tiny write-only row.
    Full archival, user/server refreshes, attachments, temp voice linkage, and
    monitoring side effects are intentionally handled by background ingestion.
    """
    if message.guild is None or message.author is None:
        return False
    created_at = _as_naive_utc(message.created_at) or datetime.now(timezone.utc).replace(tzinfo=None)
    insert_stmt = (
        pg_insert(MessageClaim)
        .values(
            message_id=message.id,
            server_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            created_at=created_at,
        )
        .on_conflict_do_nothing(index_elements=[MessageClaim.message_id])
        .returning(MessageClaim.message_id)
    )
    async with get_async_session() as session:
        created_row = (await session.exec(insert_stmt)).first()
        await session.commit()
    return created_row is not None


async def _record_deleted_message_from_claim(
    claim: MessageClaim,
    guild_id: int,
    session: AsyncSession,
    *,
    deleted_at: datetime,
) -> DeletedMessage:
    await session.exec(
        pg_insert(Server)
        .values(
            server_id=guild_id,
            server_name=None,
            bot_active=True,
            bot_presence_updated_at=deleted_at,
        )
        .on_conflict_do_nothing(index_elements=[Server.server_id])
    )
    await session.exec(
        pg_insert(GlobalUser)
        .values(discord_id=claim.user_id)
        .on_conflict_do_nothing(index_elements=[GlobalUser.discord_id])
    )
    deleted_message = DeletedMessage(
        server_id=guild_id,
        message_id=claim.message_id,
        channel_id=claim.channel_id,
        author_user_id=claim.user_id,
        content=None,
        attachments_json=None,
        deleted_at=deleted_at,
    )
    session.add(deleted_message)
    await session.flush()
    await migrate_message_action_links_to_deleted(
        session,
        deleted_message=deleted_message,
    )
    return deleted_message


async def migrate_message_action_links_to_deleted(
    session: AsyncSession,
    *,
    deleted_message: DeletedMessage,
    ensure_action_id=None,
    linked_by_user_id: int | None = None,
) -> None:
    """Move every live action link to the durable deleted-message snapshot."""
    live_links = (
        await session.exec(
            select(ModerationActionMessageLink).where(
                ModerationActionMessageLink.server_id == deleted_message.server_id,
                ModerationActionMessageLink.message_id == deleted_message.message_id,
            )
        )
    ).all()
    links_by_action = {link.moderation_action_id: link for link in live_links}
    if ensure_action_id is not None and ensure_action_id not in links_by_action:
        links_by_action[ensure_action_id] = None

    for action_id, live_link in links_by_action.items():
        existing = (
            await session.exec(
                select(ModerationActionDeletedMessageLink).where(
                    ModerationActionDeletedMessageLink.moderation_action_id == action_id,
                    ModerationActionDeletedMessageLink.deleted_message_id == deleted_message.id,
                )
            )
        ).first()
        if existing is None:
            actor_id = (
                live_link.linked_by_user_id
                if live_link is not None
                else linked_by_user_id
            )
            if actor_id is None:
                continue
            session.add(
                ModerationActionDeletedMessageLink(
                    moderation_action_id=action_id,
                    deleted_message_id=deleted_message.id,
                    linked_by_user_id=actor_id,
                    linked_at=live_link.linked_at if live_link is not None else deleted_message.deleted_at,
                )
            )

    for live_link in live_links:
        await session.delete(live_link)
    await session.flush()


async def handle_message_deletion(message_id: int, guild_id: int | None, session: AsyncSession):
    """Moves a message from message_log to deleted_messages when it is deleted in Discord."""
    if guild_id is None:
        return

    result = await session.exec(select(MessageLog).where(MessageLog.message_id == message_id))
    logged_msg = result.first()
    if not logged_msg:
        claim_result = await session.exec(select(MessageClaim).where(MessageClaim.message_id == message_id))
        claim = claim_result.first()
        if not claim:
            return
        await _record_deleted_message_from_claim(
            claim,
            guild_id,
            session,
            deleted_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        await session.delete(claim)
        await session.commit()
        return

    attachments_result = await session.exec(
        select(AttachmentLog).where(AttachmentLog.message_id == message_id)
    )
    attachment_rows = attachments_result.all()
    attachments_json = (
        json.dumps(
            [
                {
                    "storage_key": attachment.storage_key,
                    "file_name": attachment.file_name,
                    "content_type": attachment.content_type,
                }
                for attachment in attachment_rows
            ]
        )
        if attachment_rows
        else None
    )

    deleted_message = DeletedMessage(
        server_id=guild_id,
        message_id=message_id,
        channel_id=logged_msg.channel_id,
        author_user_id=logged_msg.user_id,
        content=logged_msg.content,
        attachments_json=attachments_json,
        deleted_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(deleted_message)
    await session.flush()
    await migrate_message_action_links_to_deleted(session, deleted_message=deleted_message)

    for attachment in attachment_rows:
        await session.delete(attachment)
    await session.delete(logged_msg)
    await session.commit()


async def handle_bulk_message_deletion(message_ids: set[int], guild_id: int | None, session: AsyncSession):
    """Moves multiple messages from message_log to deleted_messages in one transaction."""
    if guild_id is None or not message_ids:
        return

    message_ids_list = list(message_ids)
    logs_result = await session.exec(select(MessageLog).where(MessageLog.message_id.in_(message_ids_list)))
    logged_messages = logs_result.all()
    logged_message_ids = {message.message_id for message in logged_messages}
    missing_message_ids = set(message_ids_list) - logged_message_ids

    if missing_message_ids:
        claims_result = await session.exec(select(MessageClaim).where(MessageClaim.message_id.in_(missing_message_ids)))
        deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        for claim in claims_result.all():
            await _record_deleted_message_from_claim(claim, guild_id, session, deleted_at=deleted_at)
            await session.delete(claim)

    if not logged_messages:
        await session.commit()
        return

    attachments_result = await session.exec(
        select(AttachmentLog).where(AttachmentLog.message_id.in_(logged_message_ids))
    )
    attachment_rows = attachments_result.all()
    attachments_by_message_id: dict[int, list[AttachmentLog]] = {}
    for attachment in attachment_rows:
        attachments_by_message_id.setdefault(attachment.message_id, []).append(attachment)

    deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for logged_msg in logged_messages:
        rows = attachments_by_message_id.get(logged_msg.message_id, [])
        attachments_json = (
            json.dumps(
                [
                    {
                        "storage_key": attachment.storage_key,
                        "file_name": attachment.file_name,
                        "content_type": attachment.content_type,
                    }
                    for attachment in rows
                ]
            )
            if rows
            else None
        )

        deleted_message = DeletedMessage(
            server_id=guild_id,
            message_id=logged_msg.message_id,
            channel_id=logged_msg.channel_id,
            author_user_id=logged_msg.user_id,
            content=logged_msg.content,
            attachments_json=attachments_json,
            deleted_at=deleted_at,
        )
        session.add(deleted_message)
        await session.flush()
        await migrate_message_action_links_to_deleted(session, deleted_message=deleted_message)

        for attachment in rows:
            await session.delete(attachment)
        await session.delete(logged_msg)

    await session.commit()

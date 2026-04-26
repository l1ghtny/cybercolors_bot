import json
from datetime import datetime, timezone

import discord as d
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import get_async_session
from src.db.models import (
    AttachmentLog,
    DeletedMessage,
    GlobalUser,
    MessageLog,
    Server,
    User,
)


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
    query = select(GlobalUser).where(GlobalUser.discord_id == user.id).options(selectinload(GlobalUser.memberships))
    result = await session.exec(query)
    user_in_db = result.first()

    display_avatar = getattr(user, "display_avatar", None)
    avatar_url = str(display_avatar.url) if display_avatar else None
    joined_discord = getattr(user, "created_at", None) or getattr(user, "joined_at", None)

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
        is_member_of_server = any(m.server_id == server.id for m in user_in_db.memberships)
        if not is_member_of_server:
            await add_user_to_current_server(user_in_db, server, user.nick, session)
        else:
            membership = next(m for m in user_in_db.memberships if m.server_id == server.id)
            changed = False
            if membership.server_nickname != user.nick:
                membership.server_nickname = user.nick
                changed = True
            if not membership.is_member:
                membership.is_member = True
                changed = True
            if changed:
                session.add(membership)


async def add_user_to_current_server(
    user: GlobalUser,
    server: d.Guild,
    server_nickname: str | None,
    session: AsyncSession,
):
    """Adds a server membership link for a global user. Uses the provided session."""
    session.add(
        User(
            user_id=user.discord_id,
            server_id=server.id,
            server_nickname=server_nickname,
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
    insert_stmt = (
        pg_insert(MessageLog)
        .values(
            message_id=message.id,
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
    Atomically claims a message for processing by inserting it into message_log.
    Returns True only for the first worker that sees this message ID.
    """
    async with get_async_session() as session:
        await ensure_message_foreign_keys(message, session)
        claimed = await log_message(message, session)
        await session.commit()
    return claimed


async def handle_message_deletion(message_id: int, guild_id: int | None, session: AsyncSession):
    """Moves a message from message_log to deleted_messages when it is deleted in Discord."""
    if guild_id is None:
        return

    result = await session.exec(select(MessageLog).where(MessageLog.message_id == message_id))
    logged_msg = result.first()
    if not logged_msg:
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

    session.add(
        DeletedMessage(
            server_id=guild_id,
            message_id=message_id,
            channel_id=logged_msg.channel_id,
            author_user_id=logged_msg.user_id,
            content=logged_msg.content,
            attachments_json=attachments_json,
            deleted_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )

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
    if not logged_messages:
        return

    attachments_result = await session.exec(
        select(AttachmentLog).where(AttachmentLog.message_id.in_(message_ids_list))
    )
    attachment_rows = attachments_result.all()
    attachments_by_message_id: dict[int, list[AttachmentLog]] = {}
    for attachment in attachment_rows:
        attachments_by_message_id.setdefault(attachment.message_id, []).append(attachment)

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

        session.add(
            DeletedMessage(
                server_id=guild_id,
                message_id=logged_msg.message_id,
                channel_id=logged_msg.channel_id,
                author_user_id=logged_msg.user_id,
                content=logged_msg.content,
                attachments_json=attachments_json,
                deleted_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

        for attachment in rows:
            await session.delete(attachment)
        await session.delete(logged_msg)

    await session.commit()

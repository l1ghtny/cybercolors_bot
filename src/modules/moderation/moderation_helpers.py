import discord as d
from datetime import datetime, timezone
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import GlobalUser, User, Server, MessageLog, DeletedMessage


async def check_if_user_exists(user: d.Member | d.User, server: d.Guild, session: AsyncSession):
    """Checks if a user and their server membership exist, creating or updating them if needed."""
    # Eagerly load the memberships to avoid extra queries later
    query = select(GlobalUser).where(GlobalUser.discord_id == user.id).options(selectinload(GlobalUser.memberships))
    result = await session.exec(query)
    user_in_db = result.first()

    avatar_url = str(user.display_avatar.url) if user.display_avatar else None

    if not user_in_db:
        # User is not in the database at all, create a new global user
        new_user = GlobalUser(
            discord_id=user.id,
            username=user.name,
            joined_discord=user.created_at, # created_at is more appropriate for GlobalUser
            avatar_hash=avatar_url
        )
        session.add(new_user)
        await session.flush()
        user_in_db = new_user
    else:
        # Update global user info if changed
        changed = False
        if user_in_db.username != user.name:
            user_in_db.username = user.name
            changed = True
        if user_in_db.avatar_hash != avatar_url:
            user_in_db.avatar_hash = avatar_url
            changed = True
        
        if changed:
            session.add(user_in_db)

    # Check if they are a member of the current server (only if it's a Member object)
    if isinstance(user, d.Member):
        is_member_of_server = any(m.server_id == server.id for m in user_in_db.memberships)

        if not is_member_of_server:
            # User exists globally but not in this server, so add them
            await add_user_to_current_server(user_in_db, server, user.nick, session)
        else:
            # Update membership info if changed
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


async def add_user_to_current_server(user: GlobalUser, server: d.Guild, server_nickname: str | None, session: AsyncSession):
    """Adds a server membership link for a global user. Uses the provided session."""
    server_member = User(
        user_id=user.discord_id, 
        server_id=server.id, 
        server_nickname=server_nickname,
        is_member=True
    )
    session.add(server_member)


async def check_if_server_exists(server: d.Guild, session: AsyncSession):
    """Checks if a server exists in the DB, creating or updating it if needed."""
    query = select(Server).where(Server.server_id == server.id)
    result = await session.exec(query)
    server_in_db = result.first()
    
    icon_url = str(server.icon.url) if server.icon else None
    
    if not server_in_db:
        new_server = Server(
            server_id=server.id, 
            server_name=server.name, 
            icon=icon_url
        )
        session.add(new_server)
    else:
        # Update server info if changed
        changed = False
        if server_in_db.server_name != server.name:
            server_in_db.server_name = server.name
            changed = True
        if server_in_db.icon != icon_url:
            server_in_db.icon = icon_url
            changed = True
        
        if changed:
            session.add(server_in_db)


async def log_message(message: d.Message, session: AsyncSession):
    """Logs a message to the message_log table for later retrieval (e.g., if deleted)."""
    msg_log = MessageLog(
        message_id=message.id,
        user_id=message.author.id,
        channel_id=message.channel.id,
        content=message.content,
        created_at=message.created_at.replace(tzinfo=None),
        reply_to_message_id=message.reference.message_id if message.reference else None,
        server_id=message.guild.id
    )
    session.add(msg_log)


async def handle_message_deletion(message_id: int, guild_id: int, session: AsyncSession):
    """Moves a message from message_log to deleted_messages when it is deleted in Discord."""
    # 1. Find the message in logs
    stmt = select(MessageLog).where(MessageLog.message_id == message_id)
    result = await session.exec(stmt)
    logged_msg = result.first()

    if logged_msg:
        # 2. Create DeletedMessage record
        deleted_msg = DeletedMessage(
            server_id=guild_id,
            message_id=message_id,
            channel_id=logged_msg.channel_id,
            author_user_id=logged_msg.user_id,
            content=logged_msg.content,
            deleted_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        session.add(deleted_msg)
        # 3. Optional: Delete from MessageLog to save space
        await session.delete(logged_msg)
        await session.commit()

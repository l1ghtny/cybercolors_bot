import discord
from sqlalchemy.orm import selectinload
from sqlmodel import select

from src.db.database import get_session
from src.db.models import GlobalUser, User, Server


async def check_if_user_exists(user: discord.Member, server: discord.Guild):
    async with get_session() as session:
        # Eagerly load the memberships to avoid extra queries later
        query = select(GlobalUser).where(GlobalUser.discord_id == user.id).options(selectinload(GlobalUser.memberships))
        result = await session.exec(query)
        user_in_db = result.first()

        if not user_in_db:
            # User is not in the database at all, create a new global user and server membership
            new_user = GlobalUser(discord_id=user.id, username=user.name, joined_discord=user.joined_at)
            session.add(new_user)
            # The new_user object is now tracked by the session.
            # We can pass it to the next function which will commit it.
            await add_user_to_current_server(new_user, server, user.nick, session)
            return True

        # User exists in DB, check if they are a member of the current server
        is_member_of_server = any(m.server_id == server.id for m in user_in_db.memberships)

        if is_member_of_server:
            # User exists and is already a member of this server
            return True
        else:
            # User exists globally but not in this server, so add them
            await add_user_to_current_server(user_in_db, server, user.nick, session)
            return True


async def add_user_to_current_server(user: GlobalUser, server: discord.Guild, server_nickname: str | None, session):
    await check_if_server_exists(server)
    async with session:
        # Use merge to handle the user object which might be from a different session
        session.add(user)
        server_member = User(user_id=user.discord_id, server_id=server.id, server_nickname=server_nickname)
        session.add(server_member)
        await session.commit()


async def check_if_server_exists(server: discord.Guild):
    async with get_session() as session:
        query = select(Server).where(Server.server_id == server.id)
        result = await session.exec(query)
        server_in_db = result.first()
        if server_in_db:
            return True
        else:
            new_server = Server(server_id=server.id, server_name=server.name)
            session.add(new_server)
            await session.commit()
            return True
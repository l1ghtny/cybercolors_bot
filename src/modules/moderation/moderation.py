import discord as d
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import GlobalUser, User, Server


async def check_if_user_exists(user: d.Member, server: d.Guild, session: AsyncSession):
    """Checks if a user and their server membership exist, creating them if not. Uses the provided session."""
    # Eagerly load the memberships to avoid extra queries later
    query = select(GlobalUser).where(GlobalUser.discord_id == user.id).options(selectinload(GlobalUser.memberships))
    result = await session.exec(query)
    user_in_db = result.first()

    if not user_in_db:
        # User is not in the database at all, create a new global user and server membership
        new_user = GlobalUser(discord_id=user.id, username=user.name, joined_discord=user.joined_at)
        session.add(new_user)
        # The new_user object is now tracked by the session.
        # The commit will be handled by the calling API endpoint.
        await add_user_to_current_server(new_user, server, user.nick, session)
        return

    # User exists in DB, check if they are a member of the current server
    is_member_of_server = any(m.server_id == server.id for m in user_in_db.memberships)

    if not is_member_of_server:
        # User exists globally but not in this server, so add them
        await add_user_to_current_server(user_in_db, server, user.nick, session)


async def add_user_to_current_server(user: GlobalUser, server: d.Guild, server_nickname: str | None, session: AsyncSession):
    """Adds a server membership link for a global user. Uses the provided session."""
    # The 'user' object is already part of the session from the calling function.
    # The commit will be handled by the API endpoint.
    server_member = User(user_id=user.discord_id, server_id=server.id, server_nickname=server_nickname)
    session.add(server_member)


async def check_if_server_exists(server: d.Guild, session: AsyncSession):
    """Checks if a server exists in the DB, creating it if not. Uses the provided session."""
    query = select(Server).where(Server.server_id == server.id)
    result = await session.exec(query)
    server_in_db = result.first()
    if not server_in_db:
        new_server = Server(server_id=server.id, server_name=server.name)
        session.add(new_server)
        # The commit will be handled by the API endpoint.
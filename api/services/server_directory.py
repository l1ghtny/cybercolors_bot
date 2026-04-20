from sqlalchemy import String, cast, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_directory import ServerUserModel
from src.db.models import GlobalUser, User


def _display_name(user: User, global_user: GlobalUser) -> str:
    if user.server_nickname:
        return user.server_nickname
    if global_user.username:
        return global_user.username
    return str(user.user_id)


def _to_server_user(user: User, global_user: GlobalUser) -> ServerUserModel:
    return ServerUserModel(
        user_id=str(user.user_id),
        display_name=_display_name(user, global_user),
        username=global_user.username,
        avatar_hash=global_user.avatar_hash,
        is_member=user.is_member,
    )


async def query_server_users(
    session: AsyncSession,
    server_id: int,
    search: str | None = None,
    limit: int = 50,
) -> list[ServerUserModel]:
    statement = (
        select(User, GlobalUser)
        .join(GlobalUser, GlobalUser.discord_id == User.user_id)
        .where(User.server_id == server_id)
    )

    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                cast(User.user_id, String).ilike(pattern),
                User.server_nickname.ilike(pattern),
                GlobalUser.username.ilike(pattern),
            )
        )

    statement = statement.order_by(User.server_nickname, GlobalUser.username).limit(limit)
    rows = (await session.exec(statement)).all()
    return [_to_server_user(user, global_user) for user, global_user in rows]


async def lookup_server_users_by_ids(
    session: AsyncSession,
    server_id: int,
    user_ids: list[int],
) -> list[ServerUserModel]:
    if not user_ids:
        return []

    statement = (
        select(User, GlobalUser)
        .join(GlobalUser, GlobalUser.discord_id == User.user_id)
        .where(User.server_id == server_id, User.user_id.in_(user_ids))
    )
    rows = (await session.exec(statement)).all()
    return [_to_server_user(user, global_user) for user, global_user in rows]

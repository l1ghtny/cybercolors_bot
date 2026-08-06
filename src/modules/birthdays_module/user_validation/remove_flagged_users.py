import datetime

from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import User, utcnow_utc_tz


def normalize_utc(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


async def remove_old_flagged_users(*, guild_ids: set[int] | None = None):
    if guild_ids is not None and not guild_ids:
        return
    async with get_async_session() as session:
        query = select(User).where(User.is_member == False)
        if guild_ids is not None:
            query = query.where(User.server_id.in_(list(guild_ids)))
        result = await session.exec(query)
        flagged_users = result.all()

    for row in flagged_users:
        server_id = row.server_id
        user_id = row.user_id
        flagged_time = row.flagged_absent_at
        if flagged_time is None:
            continue
        utc_now = utcnow_utc_tz()
        timedelta = utc_now - normalize_utc(flagged_time)
        if timedelta.days > 365:
            await remove_user_from_table(server_id, user_id)


async def remove_user_from_table(server_id, user_id):
    async with get_async_session() as session:
        query = select(User).where(User.server_id == server_id, User.user_id == user_id)
        result = await session.exec(query)
        user_data = result.first()
        if user_data is not None:
            session.delete(user_data)
            await session.commit()

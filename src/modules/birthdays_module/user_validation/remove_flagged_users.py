import datetime

from sqlalchemy import select

from src.db.database import get_session
from src.db.models import User


async def remove_old_flagged_users():
    async with get_session() as session:
        query = select(User).where(User.is_member == False)
        result = await session.exec(query)
        flagged_users = result.all()

    for row in flagged_users:
        server_id = row.server_id
        user_id = row.user_id
        flagged_time = row.flagged_absent_at
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        timedelta = utc_now - flagged_time
        if timedelta.days > 365:
            await remove_user_from_table(server_id, user_id)


async def remove_user_from_table(server_id, user_id):
    async with get_session() as session:
        query = select(User).where(User.server_id == server_id, User.user_id == user_id)
        result = await session.exec(query)
        user_data = result.first()
        if user_data is not None:
            session.delete(user_data)
            await session.commit()

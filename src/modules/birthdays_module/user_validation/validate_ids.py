from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import engine
from src.db.models import User
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def manage_invalid_users(client):
    invalid_users, need_to_delete = await get_invalid_users(client)
    if need_to_delete:
        await remove_invalid_user_ids(invalid_users)
        logger.info('invalid users purged:')
        logger.info(invalid_users)
    else:
        logger.info('no invalid users to purge')


async def get_invalid_users(client):
    async with AsyncSession(engine) as session:
        query = select(User).where(User.is_member == False)
        result = await session.exec(query)
        users = result.all()
        user_ids = [user.user_id for user in users]
    not_valid_users = []
    for user_id in user_ids:
        user_model = client.get_user(user_id)
        if user_model is None:
            not_valid_users.append(user_id)
    if not_valid_users:
        have_invalid_users = True
    else:
        have_invalid_users = False
    return not_valid_users, have_invalid_users


async def remove_invalid_user_ids(ids_list):
    async with AsyncSession(engine) as session:
        query = select(User).where(User.user_id.in_(ids_list))
        result = await session.exec(query)
        users_to_delete = result.all()

        for user in users_to_delete:
            await session.delete(user)

        await session.commit()

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import engine, get_session, get_async_session
from src.db.models import GlobalUser



async def process_background_tasks(message, server_rules, known_global_users):
    """
    This runs in the background. It does not block the bot from
    reading the next message.
    """
    user_id = message.author.id

    # 1. Database Consistency (Check global user)
    if user_id not in known_global_users:
        async with get_async_session() as session:
            global_users = (await session.exec(select(GlobalUser))).all()
            global_users.add(user_id)
            await session.commit()

        known_global_users.add(user_id)

    # 2. Log Activity
    # await db.log_activity(user_id, message.content, ...)

    # 3. LLM Moderation (The slow part)
    # Only run this if the message wasn't deleted by earlier filters
    response = await call_openai_moderation(message.content, server_rules)
    if response == "YES_VIOLATION":
        admin_channel = message.guild.get_channel(ADMIN_CHANNEL_ID)
        await admin_channel.send(f"⚠️ Possible violation: {message.jump_url}")
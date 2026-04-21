from sqlmodel.ext.asyncio.session import AsyncSession
from src.db.database import engine
from src.modules.moderation.moderation_helpers import check_if_user_exists, check_if_server_exists, log_message
from src.db.models import UserActivity
from sqlmodel import select
from datetime import datetime

async def process_background_tasks(message, server_rules, known_global_users):
    """
    This runs in the background. It does not block the bot from
    reading the next message.
    """
    user_id = message.author.id
    guild = message.guild

    async with AsyncSession(engine) as session:
        # 1. Database Consistency (Check global user and server)
        await check_if_server_exists(guild, session)
        await check_if_user_exists(message.author, guild, session)

        # 2. Log Message for evidence
        await log_message(message, session)

        # 3. Track User Activity (Phase 3 preview)
        activity_stmt = select(UserActivity).where(
            UserActivity.user_id == user_id,
            UserActivity.server_id == guild.id
        )
        activity_result = await session.exec(activity_stmt)
        activity = activity_result.first()

        if activity:
            activity.message_count += 1
            activity.last_message_at = datetime.now()
        else:
            new_activity = UserActivity(
                user_id=user_id,
                server_id=guild.id,
                channel_id=message.channel.id,
                message_count=1,
                last_message_at=datetime.now()
            )
            session.add(new_activity)

        await session.commit()
        known_global_users.add(user_id)

    # 4. LLM Moderation (Phase 6 preview - placeholder)
    # await screen_with_llm(message, server_rules)
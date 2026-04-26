from datetime import datetime, timezone

from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import UserActivity
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def process_background_tasks(message, known_global_users):
    """
    This runs in the background. It does not block the bot from
    reading the next message.
    """
    user_id = message.author.id
    guild = message.guild

    async with get_async_session() as session:
        # 1. Database consistency (check global user and server)
        await check_if_server_exists(guild, session)
        await check_if_user_exists(message.author, guild, session)

        # 2. Track user activity (Phase 3 preview)
        activity_stmt = select(UserActivity).where(
            UserActivity.user_id == user_id,
            UserActivity.server_id == guild.id,
        )
        activity_result = await session.exec(activity_stmt)
        activity = activity_result.first()

        if activity:
            activity.message_count += 1
            activity.channel_id = message.channel.id
            activity.last_message_at = _naive_utcnow()
        else:
            session.add(
                UserActivity(
                    user_id=user_id,
                    server_id=guild.id,
                    channel_id=message.channel.id,
                    message_count=1,
                    last_message_at=_naive_utcnow(),
                )
            )

        await session.commit()
        known_global_users.add(user_id)

    # 4. LLM moderation (Phase 6 preview - placeholder)
    # await screen_with_llm(message)

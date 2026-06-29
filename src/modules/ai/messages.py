from sqlmodel.ext.asyncio.session import AsyncSession

from src.modules.ai.ai_main import ai_main_class
from src.modules.ai.models import ModerationVerdict


async def check_user_message(message, session: AsyncSession | None = None) -> ModerationVerdict | None:
    if message.author.bot:
        return None
    return await ai_main_class.check_message(message, session=session)

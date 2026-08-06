from src.modules.birthdays_module.user_validation.check_flagged_users import remove_flag_from_users_by_server
from src.modules.birthdays_module.user_validation.flag_users_who_left import flag_users_by_server
from src.modules.birthdays_module.user_validation.remove_flagged_users import remove_old_flagged_users
from src.modules.birthdays_module.user_validation.validate_ids import manage_invalid_users
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def main_validation_process(client, *, guild_ids: set[int] | None = None):
    await manage_invalid_users(client, guild_ids=guild_ids)
    await flag_users_by_server(client, guild_ids=guild_ids)
    await remove_old_flagged_users(guild_ids=guild_ids)
    await remove_flag_from_users_by_server(client, guild_ids=guild_ids)
    logger.info('validation process finished')

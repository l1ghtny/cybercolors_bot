from modules.birthdays_module.user_validation.flag_users_who_left import flag_users_by_server
from modules.birthdays_module.user_validation.remove_flagged_users import check_flagged_users
from modules.birthdays_module.user_validation.validate_ids import manage_invalid_users
from modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


def main_validation_process(client):
    manage_invalid_users(client)
    flag_users_by_server(client)
    check_flagged_users()
    logger.info('validation process finished')

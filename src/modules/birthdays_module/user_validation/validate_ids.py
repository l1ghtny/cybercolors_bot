from src.misc_files.basevariables import access_db_sync
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


def manage_invalid_users(client):
    invalid_users, need_to_delete = get_invalid_users(client)
    if need_to_delete is True:
        remove_invalid_user_ids(invalid_users)
        logger.info('invalid users purged:')
        logger.info(invalid_users)
    else:
        logger.info('no invalid users to purge')


def get_invalid_users(client):
    conn, cursor = access_db_sync()
    query = 'select user_id from "public".users'
    cursor.execute(query)
    user_ids = cursor.fetchall()
    not_valid_users = []
    conn.close()
    for user_id in user_ids:
        actual_id = user_id['user_id']
        user_model = client.get_user(actual_id)
        if user_model is None:
            not_valid_users.append(actual_id)
    if not_valid_users:
        have_invalid_users = True
    else:
        have_invalid_users = False
    return not_valid_users, have_invalid_users


def remove_invalid_user_ids(ids_list):
    conn, cursor = access_db_sync()
    ids_list_tuples = zip(ids_list)
    query = 'delete from "public".users where user_id in (%s)'
    cursor.executemany(query, ids_list_tuples)
    conn.commit()
    conn.close()

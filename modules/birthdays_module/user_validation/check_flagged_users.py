from misc_files.basevariables import access_db_sync
from modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


def remove_flag_from_users_by_server(client):
    conn, cursor = access_db_sync()
    query = 'select user_id, server_id from "public".users where is_member = False'
    cursor.execute(query)
    servers_and_users = cursor.fetchall()
    conn.close()
    for each in servers_and_users:
        server_id = each['server_id']
        user_id = each['user_id']
        server = client.get_guild(server_id)
        if check_if_user_is_a_member(server, user_id) is True:
            remove_flag_user(user_id, server_id)
            user = client.get_user(user_id)
            logger.info('removed_flag_from_user')
            logger.info(user.display_name)


def remove_flag_user(user_id, server_id):
    conn, cursor = access_db_sync()
    no_time = None
    query = 'UPDATE "public".users SET is_member=True, flagged_absent_at=%s where user_id=%s and ' \
            'server_id=%s'
    values = (no_time, user_id, server_id,)
    cursor.execute(query, values)
    conn.commit()
    conn.close()


def check_if_user_is_a_member(server, user_id):
    if server.get_member(user_id) is None:
        is_member = False
    else:
        is_member = True
    return is_member

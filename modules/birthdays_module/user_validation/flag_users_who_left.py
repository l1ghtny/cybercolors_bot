import datetime

from misc_files.basevariables import access_db_sync
from modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


def flag_users_by_server(client):
    conn, cursor = access_db_sync()
    query = 'select user_id, server_id from "public".users where is_member = True'
    cursor.execute(query)
    servers_and_users = cursor.fetchall()
    conn.close()
    for each in servers_and_users:
        server_id = each['server_id']
        user_id = each['user_id']
        server = client.get_guild(server_id)
        if check_if_user_is_a_member(server, user_id) is False:
            flag_user(user_id, server_id)
            user = client.get_user(user_id)
            logger.info('flagged a user')
            logger.info(user.display_name)



def flag_user(user_id, server_id):
    conn, cursor = access_db_sync()
    utc_now = datetime.datetime.utcnow()
    query = 'UPDATE "public".users SET is_member=False, flagged_absent_at=%s where user_id=%s and ' \
            'server_id=%s'
    values = (utc_now, user_id, server_id,)
    cursor.execute(query, values)
    conn.commit()
    conn.close()


def check_if_user_is_a_member(server, user_id):
    if server.get_member(user_id) is None:
        is_member = False
    else:
        is_member = True
    return is_member

import datetime

from misc_files.basevariables import access_db_sync


def check_flagged_users():
    conn, cursor = access_db_sync()
    query = 'select server_id, user_id, flagged_absent_at, is_member from "public".users where is_member = False'
    cursor.execute(query)
    flagged_users = cursor.fetchall()
    conn.close()
    for row in flagged_users:
        server_id = row['server_id']
        user_id = row['user_id']
        flagged_time = row['flagged_absent_at']
        utc_now = datetime.datetime.utcnow()
        timedelta = utc_now - flagged_time
        if timedelta.days > 365:
            remove_user_from_table(server_id, user_id)


def remove_user_from_table(server_id, user_id):
    conn, cursor = access_db_sync()
    query = 'DELETE from "public".users where user_id=%s and server_id=%s'
    values = (user_id, server_id,)
    cursor.execute(query, values)
    conn.commit()
    conn.close()

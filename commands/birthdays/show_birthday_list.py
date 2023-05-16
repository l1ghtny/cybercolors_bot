import calendar
import itertools
import operator

from misc_files import basevariables
from views.pagination.pagination import PaginationView
from modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def send_birthday_list(client, interaction):
    await interaction.response.defer()
    server_id = interaction.guild_id
    old_data = [

    ]
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = """SELECT e.server_id, e.user_id, e.day, e.month, e.close_month + e.close_day as closest
                FROM (SELECT g.server_id, g.user_id, g.day, g.month,
                CASE 
                WHEN diff < 0 then 100 + diff ELSE diff END as close_month, 
                CASE 
                WHEN diff_1 < 0 and diff = 0 then 1000 + diff_1 ELSE 0 END as close_day
                FROM (SELECT server_id, user_id, day, day - date_part('day', now()) AS diff_1, month, month - date_part('month', now()) AS diff FROM "public".users) as g
                WHERE server_id=%s) as e
                ORDER BY closest, day"""
    values = (server_id,)
    cursor.execute(query, values)
    birthdays = cursor.fetchall()
    logger.info(f'{birthdays}')
    conn.close()
    bd_list = []
    for item in birthdays:
        user_id = item['user_id']
        user = client.get_user(user_id)
        month_num = item['month']
        day = item['day']
        month = calendar.month_name[month_num]
        bd_list.append({
            'user': user,
            'date': f'{day} {month}'
        })

    for i in bd_list:
        list_user = i['user']
        list_date = i['date']
        logger.info('list_user_id:')
        logger.info(f'{list_user.id}')
        logger.info('list_user_name:')
        logger.info(f'{list_user.name}')
        old_data.append({
            'label': list_date,
            'value': f'{list_user.mention}'
        })
    data = []
    for key, value in itertools.groupby(old_data, key=operator.itemgetter('label')):
        new_key = key
        new_value = ""
        for k in value:
            if new_value is str(""):
                new_value = k['value']
            else:
                new_value += f" и {k['value']}"
        data.append({
            'label': new_key,
            'value': new_value
        })

    title = 'Дни рождения'
    footer = 'Всего дней рождений'
    maximum = 'дней'
    pagination_view = PaginationView(data, interaction.user, title, footer, maximum, separator=15)
    pagination_view.data = data
    pagination_view.counted = len(birthdays)
    await pagination_view.send(interaction)
    await interaction.followup.send('Все дни рождения найдены')

import calendar
import itertools
import operator
from datetime import datetime

from sqlmodel import select, join
from sqlalchemy.orm import selectinload

from src.db.database import get_session
from src.db.models import User, Birthday
from src.views.pagination.pagination import PaginationView
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def send_birthday_list(client, interaction, separation):
    await interaction.response.defer()
    server_id = interaction.guild_id
    old_data = []

    async with get_session() as session:
        # Get the current month and day
        now = datetime.now()
        current_month = now.month
        current_day = now.day

        # Query users with birthdays for the current server
        statement = (
            select(User, Birthday)
            .join(Birthday, Birthday.user_id == User.user_id)
            .where(User.server_id == server_id)
        )

        result = await session.exec(statement)
        users_with_birthdays = result.all()

        # Calculate birthday proximity and sort
        bd_list = []
        for user, birthday in users_with_birthdays:
            # Calculate the month difference
            month_diff = birthday.month - current_month
            if month_diff < 0:
                month_diff = 100 + month_diff
            else:
                month_diff = month_diff

            # Calculate day difference (only when months are equal)
            day_diff = 0
            if birthday.month == current_month:
                day_diff = birthday.day - current_day
                if day_diff < 0:
                    day_diff = 1000 + day_diff

            closest = month_diff + day_diff

            # Get Discord user
            discord_user = client.get_user(user.user_id)
            if discord_user:
                month_name = calendar.month_name[birthday.month]
                bd_list.append({
                    'user': discord_user,
                    'date': f'{birthday.day} {month_name}',
                    'day': birthday.day,
                    'month': birthday.month,
                    'closest': closest
                })

        # Sort by proximity
        bd_list.sort(key=lambda x: (x['closest'], x['day']))

    # Group birthdays by date
    for item in bd_list:
        list_user = item['user']
        list_date = item['date']
        old_data.append({
            'label': list_date,
            'value': f'{list_user.mention}'
        })

    data = []
    for key, value in itertools.groupby(old_data, key=operator.itemgetter('label')):
        new_key = key
        new_value = ""
        for k in value:
            if new_value == "":
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
    pagination_view = PaginationView(data, interaction.user, title, footer, maximum, separator=separation)
    pagination_view.data = data
    pagination_view.counted = len(bd_list)
    await pagination_view.send(interaction)
    await interaction.followup.send('Все дни рождения найдены')
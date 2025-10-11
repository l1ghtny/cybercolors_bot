from pprint import pprint

import discord
import discord.ui
import psycopg2
from sqlmodel import select

from src.db.database import get_session
from src.db.models import User, Birthday

from src.modules.birthdays_module.hourly_check.check_birthday_redone import check_birthday_new
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


class DropdownTimezones(discord.ui.View):
    def __init__(self, day, month, client):
        super().__init__(timeout=None)
        self.disabled = False
        self.day = day
        self.month = month
        self.client = client

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

    @discord.ui.select(options=[
        discord.SelectOption(label='+0 Лондон', value='Europe/London'),
        discord.SelectOption(label='+01 Центральная европа', value='Europe/Berlin'),
        discord.SelectOption(label='+02 Калининград', value='Europe/Kaliningrad'),
        discord.SelectOption(label='+03 Москва', value='Europe/Moscow'),
        discord.SelectOption(label='+04 Самара', value='Europe/Samara'),
        discord.SelectOption(label='+05 Екатеринбург', value='Asia/Yekaterinburg'),
        discord.SelectOption(label='+06 Омск', value='Asia/Omsk'),
        discord.SelectOption(label='+07 Новосибирск', value='Asia/Novosibirsk'),
        discord.SelectOption(label='+08 Иркутск', value='Asia/Irkutsk'),
        discord.SelectOption(label='+09 Якутск', value='Asia/Yakutsk'),
        discord.SelectOption(label='+10 Владивосток', value='Asia/Vladivostok'),
        discord.SelectOption(label='+11 Магадан', value='Asia/Magadan'),
        discord.SelectOption(label='+12 Камчатка', value='Asia/Kamchatka'),
        discord.SelectOption(label='-01 Кабо-Верде', value='Atlantic/Cape_Verde'),
        discord.SelectOption(label='-02 Гренландия/Нуук', value='America/Nuuk'),
        discord.SelectOption(label='-03 Буэнос Айрес', value='America/Argentina/Buenos_Aires'),
        discord.SelectOption(label='-04 Сантьяго', value='America/Santiago'),
        discord.SelectOption(label='-05 Нью Йорк', value='America/New_York'),
        discord.SelectOption(label='-06 Мехико', value='America/Mexico_City'),
        discord.SelectOption(label='-07 Эдмонтон', value='America/Edmonton'),
        discord.SelectOption(label='-08 Лос-Анджелес', value='America/Los_Angeles'),
        discord.SelectOption(label='-09 Маркизские острова', value='Pacific/Marquesas'),
        discord.SelectOption(label='-10 Острова Кука', value='Pacific/Rarotonga'),
        discord.SelectOption(label='-11 Паго Паго', value='Pacific/Pago_Pago')
    ],
        custom_id='timezones_choice',
        placeholder='Твой часовой пояс',
        max_values=1,
        disabled=False
    )
    async def callback(self, interaction, select_model):
        if self.user == interaction.user:
            self.disabled = True
            user_id = interaction.user.id
            selected_timezone = select_model.values
            add_timezone = selected_timezone[0]

            try:
                async with get_session() as session:
                    query = select(Birthday).where(Birthday.user_id == user_id)
                    result = await session.exec(query)
                    user_data = result.first()
                    user_data.timezone = add_timezone
                    session.add(user_data)
                    await session.commit()
                    await session.refresh(user_data)
                await self.disable_all_items()
                embed = discord.Embed(title='Спасибо, я всё записал. Проверяй', colour=discord.Colour.orange())
                embed.add_field(name=f'Выбранный день: {self.day}', value='')
                embed.add_field(name=f'Выбранный месяц: {self.month}', value='', inline=False)
                embed.add_field(name='Выбранный часовой пояс:', value=add_timezone, inline=False)
                embed.add_field(name='', value=f'**{interaction.user.mention}, я всех приглашу на твой день рождения :)**')
                await interaction.response.send_message(embed=embed)
                await check_birthday_new(client=self.client)
            except Exception as error:
                await interaction.response.send_message(
                    'Добавить часовой пояс не получилось из-за ошибки "{}"'.format(error.__str__()))
                logger.info(f'{error}')
        else:
            await interaction.response.send_message(f'{interaction.user}, это не твоя менюшка', ephemeral=True)

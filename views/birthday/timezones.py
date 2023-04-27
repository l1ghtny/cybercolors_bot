import discord
import discord.ui
import psycopg2

from misc_files import basevariables
from logs_setup import logger

logger = logger.logging.getLogger("bot")


class DropdownTimezones(discord.ui.View):
    def __init__(self, day, month):
        super().__init__(timeout=None)
        self.disabled = False
        self.day = day
        self.month = month

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
    async def callback(self, interaction, select):
        if self.user == interaction.user:
            self.disabled = True
            interaction_guid = f'{interaction.guild.id}'
            user_id = f'{interaction.user.id}'
            selected_timezone = f'{select.values}'
            add_timezone_1 = selected_timezone[1:-1]
            add_timezone = add_timezone_1[1:-1]
            database = basevariables.database
            host = basevariables.host
            user = basevariables.user
            password = basevariables.password
            port = basevariables.port
            try:
                conn = psycopg2.connect(database=database,
                                        host=host,
                                        user=user,
                                        password=password,
                                        port=port)
                cursor = conn.cursor()
                postgres_insert_query = """UPDATE "public".users SET timezone = %s WHERE user_id = %s AND server_id =%s"""
                record_to_insert = (add_timezone, user_id, interaction_guid)
                cursor.execute(postgres_insert_query, record_to_insert)
                conn.commit()
                conn.close()
                await self.disable_all_items()
                embed = discord.Embed(title='Спасибо, я всё записал. Проверяй', colour=discord.Colour.orange())
                embed.add_field(name=f'Выбранный день: {self.day}', value='')
                embed.add_field(name=f'Выбранный месяц: {self.month}', value='', inline=False)
                embed.add_field(name='Выбранный часовой пояс:', value=add_timezone, inline=False)
                embed.add_field(name='', value=f'**{interaction.user.mention}, я всех приглашу на твой день рождения :)**')
                await interaction.response.send_message(embed=embed)
            except psycopg2.Error as error:
                await interaction.response.send_message(
                    'Добавить канал не получилось из-за ошибки "{}"'.format(error.__str__()))
                logger.info(f'{error}')
        else:
            await interaction.response.send_message(f'{interaction.user}, это не твоя менюшка', ephemeral=True)

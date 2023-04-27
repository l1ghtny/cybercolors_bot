import json
import os

import discord
import discord.ui
import psycopg2

from misc_files import basevariables
from logs_setup import logger

logger = logger.logging.getLogger("bot")


class BirthdaysChannelText(discord.ui.ChannelSelect):
    def __init__(self, user):
        super().__init__(custom_id='bd_channels', channel_types=[discord.ChannelType.text, discord.ChannelType.private])

    async def callback(self, interaction: discord.Interaction):
        await DropdownSelectBirthdaysChannels.disable_all_items(self.info)
        row = await basevariables.check_guild_id(interaction)
        selected_channel = self.values
        if row is None:
            database = os.getenv("database")
            host = os.getenv("host")
            user = os.getenv("user")
            password = os.getenv("password")
            port = os.getenv("port")
            for item in selected_channel:
                server_id = f'{item.guild.id}'
                channel_id = f'{item.id}'
                server_name = f'{item.guild.name}'
                channel_name = f'{item.name}'
                try:
                    conn = psycopg2.connect(database=database,
                                            host=host,
                                            user=user,
                                            password=password,
                                            port=port)
                    cursor = conn.cursor()
                    postgres_insert_query = """INSERT INTO "public".servers (server_id, channel_id, server_name, channel_name) VALUES (%s,%s,%s,%s)"""
                    record_to_insert = (server_id, channel_id, server_name, channel_name)
                    cursor.execute(postgres_insert_query, record_to_insert)
                    conn.commit()
                    conn.close()
                    await interaction.response.send_message(
                        f'Выбранный канал: "{item.mention}". Не забудь добавить фразы поздравления командой "/add_birthday_message')
                except psycopg2.Error as error:
                    await interaction.response.send_message(
                        'Добавить канал не получилось из-за ошибки "{}"'.format(error.__str__()))
        else:
            for item in selected_channel:
                await basevariables.update_channel_values(interaction, new_channel=item)
        view = BirthdayRoleSelectView(user=interaction.user)
        view.message = await interaction.channel.send(view=view)


class NewChannelName(discord.ui.Modal, title='Вбей название нового канала'):
    ch_title = discord.ui.TextInput(
        style=discord.TextStyle.short,
        label='Название канала',
        required=False,
        placeholder='Писать тута'
    )

    async def on_submit(self, interaction: discord.Interaction):
        new_channel_title = f'{self.ch_title.value}'
        new_channel = await interaction.guild.create_text_channel(f'{new_channel_title}', position=0)
        row = await basevariables.check_guild_id(interaction)
        if row is None:
            await basevariables.create_new_channel(interaction, new_channel)
        else:
            await basevariables.update_channel_values(interaction, new_channel)


class BirthdayRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            custom_id='birthday_role',
            placeholder='Какую роль будет выдавать бот имениннику?',
            max_values=1,
            disabled=False
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user == self.user:
            await BirthdayRoleSelectView.disable_all_items(self.info)
            server_id = interaction.guild_id
            for item in self.values:
                role_id = item.id
                role_name = item.name
                await basevariables.update_server_role(interaction, server_id, role_id, role_name)
        else:
            await interaction.response.send_message(f'{interaction.user.mention}, это не твоя менюшка, ухади',
                                                    ephemeral=True)


class DropdownSelectBirthdaysChannels(discord.ui.View):
    def __init__(self, user) -> None:
        super().__init__(timeout=None)
        select_menu = BirthdaysChannelText(user)
        select_menu.info = self
        self.add_item(select_menu)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)


class BirthdayRoleSelectView(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=None)
        roles_select = BirthdayRoleSelect()
        roles_select.info = self
        roles_select.user = user
        self.add_item(roles_select)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)


class BirthdaysButtonsSelect(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

    @discord.ui.button(label='Создать новый', custom_id='create_new', style=discord.ButtonStyle.green,
                       emoji='\U0001F58A')
    async def new_channel(self, interaction, button):
        current_user = self.user
        if current_user == interaction.user:
            await self.disable_all_items()
            await interaction.response.send_modal(NewChannelName())
        else:
            await interaction.response.send_message(f'{interaction.user}, это не твоя кнопка, уходи', ephemeral=True)
        options = [
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
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption(),
            # discord.SelectOption()
        ]
        super().__init__(custom_id='timezones_choice', placeholder='Твой часовой пояс', options=options, max_values=1,
                         disabled=False)

    async def callback(self, interaction: discord.Interaction):
        interaction_guid = f'{interaction.guild.id}'
        user = interaction.user.id
        selected_timezone = f'{self.values}'
        add_timezone_1 = selected_timezone[1:-1]
        add_timezone = add_timezone_1[1:-1]
        absolute_path = os.path.dirname(__file__)
        logger.info(f'string: {add_timezone}')
        table = f'bd_table.json'
        file_1 = f'{os.path.join(absolute_path, table)}'
        logger.info(f'self_values: {self.values}')
        with open(file_1, 'r+') as file:
            data = json.load(file)
            logger.info(f'{data}')
            for user_entry in data[interaction_guid]:
                logger.info(f'user_entry: {user_entry}')
                logger.info(f'my user id: {user}')
                if 'user_id' in user_entry:
                    if user_entry['user_id'] == user:
                        user_entry["timezone"] = add_timezone
                    else:
                        logger.info('не подходит')
                else:
                    logger.info('не найдено entry')
            file.seek(0)
            json.dump(data, file, indent=4)
        await interaction.response.send_message(f'{interaction.user.display_name}, спасибо, я всё записал(да)')

    @discord.ui.button(label='Выбрать существующий', custom_id='channel_select', style=discord.ButtonStyle.primary,
                       emoji='\U0001F4CB')
    async def select_channel(self, interaction, button):
        current_user = self.user
        if current_user == interaction.user:
            await self.disable_all_items()
            await interaction.response.send_message(f'Выбери канал для поздравлений:')
            view = DropdownSelectBirthdaysChannels(user=interaction.user)
            message = await interaction.channel.send(view=view)
            view.message = message
        else:
            await interaction.response.send_message(f'{interaction.user}, это не твоя кнопка, уходи', ephemeral=True)

    @discord.ui.button(label='Создать дефолтный', custom_id='create_default', style=discord.ButtonStyle.gray,
                       emoji='\U000023CF')
    async def channel_default(self, interaction, button):
        current_user = self.user
        if current_user == interaction.user:
            await self.disable_all_items()
            new_channel = await interaction.guild.create_text_channel('дни рождения', position=0)
            row = await basevariables.check_guild_id(interaction)
            if row is None:
                await basevariables.create_new_channel(interaction, new_channel)
            else:
                await basevariables.update_channel_values(interaction, new_channel)
            view = BirthdayRoleSelectView(user=current_user)
            view.user = current_user
            logger.info(f'{view.user.name}')
            view.message = await interaction.channel.send(view=view)
        else:
            await interaction.response.send_message(f'{interaction.user}, это не твоя кнопка, уходи', ephemeral=True)


class GuildAlreadyExists(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

    @discord.ui.button(label='Да, всё ок', custom_id='ok', style=discord.ButtonStyle.success, emoji='\U0001F44C')
    async def channel_ok(self, interaction, button):
        if interaction.user == self.user:
            await self.disable_all_items()
            await interaction.response.send_message('Ну вот и славненько')
        else:
            await interaction.response.send_message(f'{interaction.user}, это не твоя кнопка, уходи', ephemeral=True)

    @discord.ui.button(label='Хочу изменить настройки', custom_id='change_channel', style=discord.ButtonStyle.danger,
                       emoji='\U0001F6E0')
    async def channel_change(self, interaction, button):
        if interaction.user == self.user:
            await self.disable_all_items()
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
                postgres_insert_query = 'UPDATE "public".servers SET channel_id = %s, channel_name = %s WHERE server_id = %s'
                server_id = f'{interaction.guild.id}'
                channel_id = None
                channel_name = None
                update_values = (channel_id, channel_name, server_id,)
                cursor.execute(postgres_insert_query, update_values)
                conn.commit()
                conn.close()
                embed = discord.Embed(title='Давай выберем новый канал', colour=discord.Colour.dark_blue())
                view = BirthdaysButtonsSelect()
                await interaction.response.send_message('Тогда начинаем заново')
                message = await interaction.channel.send(embed=embed, view=view)
                view.message = message
                view.user = interaction.user
            except psycopg2.Error as error:
                logger.info(f'{error}')
                await interaction.response.send_message(
                    'Удалить канал не получилось из-за ошибки "{}"'.format(error.__str__()))
        else:
            await interaction.response.send_message(f'{interaction.user}, это не твоя кнопка, уходи', ephemeral=True)

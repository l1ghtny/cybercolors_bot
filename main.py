import itertools
import operator
import math
import discord
import datetime
import discord.ui
from discord import app_commands
from discord.ext import tasks
from discord.ext import commands
import json
import os
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
import basevariables
import uuid
import re
import requests
import random
import calendar

import github_api

load_dotenv()
# Grab the API token from the .env file.
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Register UUID to work with it in psycopg2
psycopg2.extras.register_uuid()


# Commands sync
class Aclient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.added = False
        self.synced = False  # we use this so the bot doesn't sync commands more than once

    # commands local sync
    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:  # check if slash commands have been synced
            await tree.sync(guild=discord.Object(id=779677470156390440))  # zagloti guild
            await tree.sync()  # global (global registration can take 1-24 hours)
            self.synced = True
        if not self.added:
            # self.add_view(DropDownViewChannels())
            self.add_view(DropdownTimezones())
            self.added = True
        birthday.start()
        update_releases.start()
        print(f"We have logged in as {self.user}.")


# select for roles based on new thing I found
class Roles2(discord.ui.RoleSelect):
    def __init__(self, command_user):
        super().__init__(custom_id='roles_new', placeholder='Выбери роли', min_values=1, max_values=5, disabled=False)
        self.user = command_user

    async def callback(self, interaction: discord.Interaction):
        if self.user == interaction.user:
            await DropDownView2.disable_all_items(self.info)
            await interaction.response.defer(thinking=True)
            selected_roles = self.values
            already_assigned = []
            new_roles = []
            forbidden = []
            selected_roles.sort()
            for item in selected_roles:
                if item.position > interaction.user.top_role.position:
                    forbidden.append(item.name)
                else:
                    if item in interaction.user.roles:
                        already_assigned.append(item.name)
                    if item not in interaction.user.roles:
                        await interaction.user.add_roles(item, reason='Roles added by command')
                        new_roles.append(item.name)
            if not forbidden:
                if not already_assigned:
                    await interaction.followup.send(f'Были добавлены роли:{new_roles}')
                if already_assigned != [] and new_roles != []:
                    await interaction.followup.send(
                        f'Были добавлены роли:{new_roles}, а эти роли у тебя уже есть:{already_assigned}')
                if already_assigned != [] and new_roles == []:
                    await interaction.followup.send(f'У тебя уже есть {already_assigned}')
            if forbidden:
                if already_assigned == [] and new_roles != []:
                    await interaction.followup.send(f'Были добавлены роли:{new_roles}. Роли {forbidden} тебе не доступны.')
                if already_assigned != [] and new_roles != []:
                    await interaction.followup.send(
                        f'Были добавлены роли:{new_roles}, а эти роли у тебя уже есть:{already_assigned}. Роли {forbidden} тебе не доступны.')
                if already_assigned != [] and new_roles == []:
                    await interaction.followup.send(
                        f'У тебя уже есть {already_assigned}. Роли {forbidden} тебе не доступны.')
                if already_assigned == [] and new_roles == []:
                    await interaction.followup.send(f'Роли {forbidden} тебе не доступны')
        else:
            await interaction.response.send_message('Это не твоя менюшка', ephemeral=True)


class Channels(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(custom_id='channels_list', channel_types=[discord.ChannelType.text],
                         placeholder='Фича пока находится разработке', min_values=1, max_values=15, disabled=False)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        d_channels = self.values
        deleted_channels_info = []
        for items in d_channels:
            await discord.TextChannel.delete(items)
            deleted_channels_info.append(items.name)
        await interaction.followup.send(f'Удалены следующие каналы: {deleted_channels_info}')
        message = self.info
        await DropDownViewChannels.disable_all_items(message)


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
                    await interaction.response.send_message(f'Выбранный канал: "{item.mention}". Не забудь добавить фразы поздравления командой "/add_birthday_message')
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


class NewDayAgain(discord.ui.Modal):
    def __init__(self, month):
        super().__init__(
            timeout=None,
            title='Напиши день'
        )
        self.month = month

    d_title = discord.ui.TextInput(
        label='Пиши тута',
        style=discord.TextStyle.short,
        custom_id='add_day_again',
        placeholder='Писать тута',
        required=True,
        max_length=2

    )

    async def on_submit(self, interaction: discord.Interaction):
        if self.d_title.value.isdigit():
            day = int(self.d_title.value)
            if self.month == '02' and day > 29:
                await interaction.response.send_message('Извини, в Феврале не бывает больше 29 дней')
            elif self.month == '04' and day > 30:
                await interaction.response.send_message('Извини, но в Апреле не бывает столько дней')
            elif self.month == '06' and day > 30:
                await interaction.response.send_message('Извини, но в Июне не бывает столько дней')
            elif self.month == '09' and day > 30:
                await interaction.response.send_message('Извини, но в Сентябре не бывает столько дней')
            elif self.month == '11' and day > 30:
                await interaction.response.send_message('Извини, но в Ноябре не бывает столько дней')
            elif day > 31:
                await interaction.response.send_message('Извини, ни в одном месяце не бывает столько дней')
            else:
                # await interaction.response.send_message(f'Выбранный месяц = {self.month}, Выбранная дата = {day}',
                #                                         ephemeral=True)
                server_id = interaction.guild_id
                user_id = interaction.user.id
                status = await basevariables.add_new_day_month(server_id, user_id, day, self.month, interaction)
                if status == 'ok':
                    await interaction.response.send_message('А теперь выбери свой часовой пояс:')
                    view = DropdownTimezones()
                    view.user = interaction.user
                    message = await interaction.channel.send(view=view)
                    view.message = message
                else:
                    interaction.channel.send('Извини, что-то пошло не так')
        else:
            await interaction.response.send_mesage('Извини, это не число. Попробуй добавить день рождения командой '
                                                   '/add_my_birthday', ephemeral=True)


class NewMonthAgain(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=None)
        select_menu = NewMonthAgainSelect()
        select_menu.user = user
        select_menu.info = self
        self.add_item(select_menu)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)


class NewMonthAgainSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            custom_id='new_month_add',
            placeholder='Месяц твоего рождения',
            max_values=1,
            disabled=False,
            options=[
                discord.SelectOption(label='Январь', value='01'),
                discord.SelectOption(label='Февраль', value='02'),
                discord.SelectOption(label='Март', value='03'),
                discord.SelectOption(label='Апрель', value='04'),
                discord.SelectOption(label='Май', value='05'),
                discord.SelectOption(label='Июнь', value='06'),
                discord.SelectOption(label='Июль', value='07'),
                discord.SelectOption(label='Август', value='08'),
                discord.SelectOption(label='Сентябрь', value='09'),
                discord.SelectOption(label='Октябрь', value='10'),
                discord.SelectOption(label='Ноябрь', value='11'),
                discord.SelectOption(label='Декабрь', value='12'),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user == self.user:
            result_list = self.values
            await NewMonthAgain.disable_all_items(self.info)
            await interaction.response.send_modal(NewDayAgain(month=result_list[0]))
        else:
            await interaction.response.send_message('Тебе нельзя', ephemeral=True)


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
            await interaction.response.send_message(f'{interaction.user.mention}, это не твоя менюшка, ухади', ephemeral=True)


# LIST OF ALL VIEWS

class DropDownView2(discord.ui.View):
    def __init__(self, user) -> None:
        super().__init__(timeout=None)
        roles = Roles2(user)
        roles.info = self
        self.add_item(roles)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)


class DropDownViewChannels(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.disabled = None
        select = Channels()
        self.add_item(select)
        select.info = self

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)


class DropdownTimezones(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.disabled = False

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
                await interaction.response.send_message(f'Выбранный часовой пояс: {add_timezone}')
            except psycopg2.Error as error:
                await interaction.response.send_message(
                    'Добавить канал не получилось из-за ошибки "{}"'.format(error.__str__()))
                print(error)
        else:
            await interaction.response.send_message(f'{interaction.user}, это не твоя менюшка', ephemeral=True)


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
        print('string:', add_timezone)
        table = f'bd_table.json'
        file_1 = f'{os.path.join(absolute_path, table)}'
        print('self_values:', self.values)
        with open(file_1, 'r+') as file:
            data = json.load(file)
            print(data)
            for user_entry in data[interaction_guid]:
                print('user_entry:', user_entry)
                print('my user id:', user)
                if 'user_id' in user_entry:
                    if user_entry['user_id'] == user:
                        user_entry["timezone"] = add_timezone
                    else:
                        print('не подходит')
                else:
                    print('не найдено entry')
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
            print(view.user.name)
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
                print(error)
                await interaction.response.send_message(
                    'Удалить канал не получилось из-за ошибки "{}"'.format(error.__str__()))
        else:
            await interaction.response.send_message(f'{interaction.user}, это не твоя кнопка, уходи', ephemeral=True)


class UserAlreadyExists(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

    @discord.ui.button(label='Да, всё верно', custom_id='birthday_ok', style=discord.ButtonStyle.success,
                       emoji='\U0001F44C')
    async def user_ok_button(self, interaction, button):
        await interaction.response.defer()
        if interaction.user == self.user:
            await self.disable_all_items()
            await interaction.followup.send('Ну вот и прекрасно')
        else:
            await interaction.followup.send(f'{interaction.user.mention}, это не твоя кнопка, уходи', ephemeral=True)

    @discord.ui.button(label='Нет, удоли', custom_id='birthday_not_ok', style=discord.ButtonStyle.danger,
                       emoji='\U0001F47A')
    async def user_not_ok_button(self, interaction, button):
        if interaction.user == self.user:
            await self.disable_all_items()
            conn, cursor = await basevariables.access_db_on_interaction(interaction)
            user = interaction.user.id
            server = interaction.guild.id
            query = 'DELETE FROM "public".users WHERE user_id=%s AND server_id=%s'
            values = (user, server,)
            cursor.execute(query, values)
            conn.commit()
            conn.close()
            await interaction.response.send_message(f'{interaction.user.display_name}, сделано')
            embed = discord.Embed(title='Твой день рождения удален. Что хочешь сделать дальше?')
            view = ChangeBirthday()
            message = await interaction.channel.send(embed=embed, view=view)
            view.message = message
            view.user = interaction.user
        else:
            await interaction.response.send_message(f'{interaction.user.mention}, это не твоя кнопка, уходи', ephemeral=True)


class ChangeBirthday(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

    @discord.ui.button(label='Пойти по своим делам', custom_id='not_add_birthday', style=discord.ButtonStyle.blurple,
                       emoji='\U0001F494')
    async def not_add_birthday(self, interaction, button):
        if interaction.user == self.user:
            await self.disable_all_items()
            await interaction.response.send_message(
                'Окей, тогда не добавляем новую дату. Если хочешь, всегда можешь воспользоваться командой '
                '/add_my_birthday')
        else:
            await interaction.response.send_message(f'{interaction.user.mention}, это не твоя кнопка, уходи', ephemeral=True)

    @discord.ui.button(label='Добавить заново', custom_id='new_birthday', style=discord.ButtonStyle.green, emoji='\U0001F382')
    async def add_new_birthday(self, interaction, button):
        if interaction.user == self.user:
            await self.disable_all_items()
            await interaction.response.send_message('Тогда выбери месяц')
            view = NewMonthAgain(user=interaction.user)
            message = await interaction.channel.send(view=view)
            view.message = message
        else:
            await interaction.response.send_message(f'{interaction.user.mention}, это не твоя кнопка, уходи', ephemeral=True)


class NewDateAgain(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        select = NewDayAgain()
        self.add_item(select)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)


class PaginationView(discord.ui.View):
    current_page: int = 1
    sep: int = 15

    def __init__(self, data, user):
        super().__init__(timeout=None)
        self.message = None
        self.roundup = math.ceil(len(data) / self.sep)
        self.interaction_user = user

    async def send(self, interaction):
        self.message = await interaction.channel.send(view=self)
        await self.update_message(self.data[:self.sep])

    def create_embed(self, data):
        embed = discord.Embed(
            title=f"Дни рождения:   Страница {self.current_page} / {self.roundup}")
        for item in data:
            embed.add_field(name=item['label'], value=item['value'], inline=False)
        embed.set_footer(text=f'Всего дней рождений: {self.counted}. Макс дат на странице: {self.sep}')
        return embed

    async def update_message(self, data):
        self.update_buttons()
        await self.message.edit(embed=self.create_embed(data), view=self)

    def update_buttons(self):
        if self.current_page == 1:
            self.first_page_button.disabled = True
            self.prev_button.disabled = True
            self.first_page_button.style = discord.ButtonStyle.gray
            self.prev_button.style = discord.ButtonStyle.gray
        else:
            self.first_page_button.disabled = False
            self.prev_button.disabled = False
            self.first_page_button.style = discord.ButtonStyle.green
            self.prev_button.style = discord.ButtonStyle.primary

        if self.current_page == self.roundup:
            self.next_button.disabled = True
            self.last_page_button.disabled = True
            self.last_page_button.style = discord.ButtonStyle.gray
            self.next_button.style = discord.ButtonStyle.gray
        else:
            self.next_button.disabled = False
            self.last_page_button.disabled = False
            self.last_page_button.style = discord.ButtonStyle.green
            self.next_button.style = discord.ButtonStyle.primary

    def get_current_page_data(self):
        until_item = self.current_page * self.sep
        from_item = until_item - self.sep
        if not self.current_page == 1:
            from_item = 0
            until_item = self.sep
        if self.current_page == self.roundup:
            from_item = self.current_page * self.sep - self.sep
            until_item = len(self.data)
        return self.data[from_item:until_item]

    @discord.ui.button(label="|<",
                       style=discord.ButtonStyle.green)
    async def first_page_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.interaction_user == interaction.user:
            await interaction.response.defer()
            self.current_page = 1

            await self.update_message(self.get_current_page_data())
        else:
            return

    @discord.ui.button(label="<",
                       style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.interaction_user == interaction.user:
            await interaction.response.defer()
            self.current_page -= 1
            await self.update_message(self.get_current_page_data())
        else:
            return

    @discord.ui.button(label=">",
                       style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.interaction_user == interaction.user:
            await interaction.response.defer()
            self.current_page += 1
            await self.update_message(self.get_current_page_data())
        else:
            return

    @discord.ui.button(label=">|",
                       style=discord.ButtonStyle.green)
    async def last_page_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.interaction_user == interaction.user:
            await interaction.response.defer()
            self.current_page = int(len(self.data) / self.sep) + 1
            await self.update_message(self.get_current_page_data())
        else:
            return


class DeleteMessages(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)


class DeleteMessagesSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(options=[],
                         custom_id='select_replies',
                         placeholder='Выборы',
                         max_values=1,
                         disabled=False
                         )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f'Ты выбрал {self.values}')


class DeleteMessagesSelect2(discord.ui.Select):
    def __init__(self):
        super().__init__(options=[],
                         custom_id='select_replies_2',
                         placeholder='Выборы',
                         max_values=1,
                         disabled=False
                         )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f'Ты выбрал {self.values}')


class DeleteMessagesSelect3(discord.ui.Select):
    def __init__(self):
        super().__init__(options=[],
                         custom_id='select_replies_3',
                         placeholder='Выборы',
                         max_values=1,
                         disabled=False
                         )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f'Ты выбрал {self.values}')


class DeleteMessagesSelect4(discord.ui.Select):
    def __init__(self):
        super().__init__(options=[],
                         custom_id='select_replies_4',
                         placeholder='Выборы',
                         max_values=1,
                         disabled=False
                         )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f'Ты выбрал {self.values}')


client = Aclient()
tree = app_commands.CommandTree(client)
intents = discord.Intents.all()
intents.message_content = True


# say hello command
@tree.command(guild=discord.Object(id=779677470156390440), name='say_hello',
              description='testing_commands')  # guild specific slash command
async def slash1(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Привет, {interaction.user.display_name}, я работаю! Меня сделал Антон на питоне", ephemeral=False)


# delete messages
@tree.command(guild=discord.Object(id=779677470156390440), name='delete_last_x_messages',
              description='для удаления последних сообщений')  # guild specific slash command
async def slash2(interaction: discord.Interaction, number: int):
    channel = interaction.channel
    messages = [message async for message in channel.history(limit=number)]
    last_digit = int(repr(number)[-1])
    await interaction.response.defer(thinking=True, ephemeral=False)
    if number <= 0:
        await interaction.followup.send('Ты шо сдурел, я не могу удалить то, чего нет')
    else:
        if last_digit == 1:
            await interaction.followup.send(f"Хм, {interaction.user.display_name}, я удалил всего {number} сообщение!",
                                            ephemeral=False)
        if last_digit >= 5:
            await interaction.followup.send(f"Сделано, {interaction.user.display_name}, я удалил {number} сообщений!",
                                            ephemeral=False)
        if (last_digit != 1) and (last_digit < 5) and (last_digit != 0):
            await interaction.followup.send(
                f'Нихера себе, {interaction.user.display_name}, я удалил целых {number} сообщения!', ephemeral=False)
        if last_digit == 0:
            await interaction.followup.send(f'Ну охуеть, я удалил аж {number} сообщений!')
        await discord.TextChannel.delete_messages(self=channel, messages=messages)


# rename channel
@tree.command(guild=discord.Object(id=779677470156390440), name='rename_channel',
              description='переименовать канал, а вы что думали?')
async def slash3(interaction: discord.Interaction, name: str):
    await interaction.channel.edit(name=name)
    await interaction.response.send_message(f'Я переименовал этот канал в "{name}"', ephemeral=False)


# add roles2
@tree.command(name='roles',
              description='Даёт возможность выбирать роли')
async def roles2(interaction: discord.Interaction):
    embed = discord.Embed(title='Выбери нужные тебе роли!', colour=discord.Colour.dark_magenta())
    view = DropDownView2(interaction.user)
    message = await interaction.channel.send(embed=embed, view=view)
    view.message = message
    await interaction.response.send_message(
        f'{interaction.user.display_name}, ты запустил новую систему выбора ролей. Она более красивая и вообще секс',
        ephemeral=True)


# delete_channels
@tree.command(name='delete_channels', description='Даёт возможность выбрать каналы для удаления')
async def delete_channels(interaction: discord.Interaction):
    embed = discord.Embed(title='Выбери нужные тебе каналы!', colour=discord.Colour.dark_magenta())
    view = DropDownViewChannels()
    message = await interaction.channel.send(embed=embed, view=view)
    view.message = message
    await interaction.response.send_message(f'{interaction.user.display_name}, ты запустил систему удаления каналов',
                                            ephemeral=True)


# Add birthdays with database
@tree.command(name='add_my_birthday', description='Добавь свой день рождения')
@app_commands.choices(
    month=[
        app_commands.Choice(name='Январь', value='01'),
        app_commands.Choice(name='Февраль', value='02'),
        app_commands.Choice(name='Март', value='03'),
        app_commands.Choice(name='Апрель', value='04'),
        app_commands.Choice(name='Май', value='05'),
        app_commands.Choice(name='Июнь', value='06'),
        app_commands.Choice(name='Июль', value='07'),
        app_commands.Choice(name='Август', value='08'),
        app_commands.Choice(name='Сентябрь', value='09'),
        app_commands.Choice(name='Октябрь', value='10'),
        app_commands.Choice(name='Ноябрь', value='11'),
        app_commands.Choice(name='Декабрь', value='12'),
    ]
)
async def add_my_birthday(interaction: discord.Interaction, day: int, month: app_commands.Choice[str]):
    await interaction.response.defer(thinking=True)
    if month.value == '02' and day > 29:
        await interaction.followup.send('Извини, такой даты не существует')
    elif day > 30 and month.value == '04':
        await interaction.followup.send('Извини, такой даты не существует')
    elif month.value == '04' and day > 30:
        await interaction.followup.send('Извини, такой даты не существует')
    elif month.value == '06' and day > 30:
        await interaction.followup.send('Извини, такой даты не существует')
    elif month.value == '09' and day > 30:
        await interaction.followup.send('Извини, такой даты не существует')
    elif month.value == '11' and day > 30:
        await interaction.followup.send('Извини, такой даты не существует')
    else:
        user_id = f'{interaction.user.id}'
        server_id = f'{interaction.guild.id}'
        anton_id = client.get_user(267745993074671616)
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
                                    port=port,
                                    cursor_factory=psycopg2.extras.DictCursor
                                    )
            cursor = conn.cursor()
            postgres_select_query = """SELECT * from "public".users WHERE user_id = %s and server_id=%s"""
            cursor.execute(postgres_select_query, (user_id, server_id,))
            row = cursor.fetchone()
            if row is None:
                postgres_insert_query = 'INSERT INTO "public".users (user_id, server_id, day, month) VALUES (%s,%s,%s,%s)'
                records_to_insert = (user_id, server_id, day, month.value,)
                cursor.execute(postgres_insert_query, records_to_insert)
                conn.commit()
                await interaction.followup.send(f'Всё записано, спасибо. День: {day}, месяц: {month.name}')
                embed = discord.Embed(title='А теперь выбери часовой пояс')
                view = DropdownTimezones()
                view.user = interaction.user
                message = await interaction.channel.send(embed=embed, view=view)
                view.message = message
            else:
                day_record = row['day']
                month_record = row['month']
                timezone_record = row['timezone']
                embed = discord.Embed(title='Тебя это устраивает?')
                view = UserAlreadyExists()
                view.user = interaction.user
                await interaction.followup.send(
                    f'Твой др уже записан. День: {day_record}, месяц: {month_record}, часовой пояс: {timezone_record}')
                message = await interaction.channel.send(embed=embed, view=view)
                view.message = message
            conn.close()
        except psycopg2.errors.ForeignKeyViolation as nameerror:
            await interaction.followup.send('Сервер ещё не настроен или что-то пошло не так. Напишите админу сервера или создателю бота')
        except psycopg2.Error as error:
            await interaction.followup.send(
                f'Что-то пошло не так, напишите {anton_id.mention}. Ошибка: {error}'
            )


# Settings for guild for birthdays module
@tree.command(name='birthdays_settings', description='Настрой дни рождения для своего сервера')
async def birthdays_settings(interaction: discord.Interaction):
    anton_id = client.get_user(267745993074671616)
    database = basevariables.database
    host = basevariables.host
    user = basevariables.user
    password = basevariables.password
    port = basevariables.port
    server_id = f'{interaction.guild.id}'
    try:
        conn = psycopg2.connect(database=database,
                                host=host,
                                user=user,
                                password=password,
                                port=port,
                                cursor_factory=psycopg2.extras.DictCursor
                                )
        cursor = conn.cursor()
        postgres_insert_query = ("""SELECT * from "public".servers WHERE server_id = %s""")
        cursor.execute(postgres_insert_query, (server_id,))
        row = cursor.fetchone()
        if row is None:
            embed = discord.Embed(title='Давай решим, в каком канале будет писать бот',
                                  colour=discord.Colour.dark_blue())
            view = BirthdaysButtonsSelect()
            await interaction.response.send_message(
                f'{interaction.user.display_name}, начинаем настройку дней рождений!')
            message = await interaction.channel.send(embed=embed, view=view)
            view.message = message
            view.user = interaction.user
        else:
            channel_name = row['channel_name']
            server_name = row['server_name']
            server_role_id = row['role_id']
            server_role_try = interaction.guild.get_role(server_role_id)
            server_role = server_role_try if server_role_try is not None else 'Не выбрано'
            embed = discord.Embed(title='Этот сервер уже настроен', colour=discord.Colour.orange())
            view = GuildAlreadyExists()
            await interaction.response.send_message(
                f'Для сервера "{server_name}" выбран канал "{channel_name}" и выбрана роль "{server_role}"')
            message = await interaction.channel.send(embed=embed, view=view)
            view.message = message
            view.user = interaction.user
        conn.close()
    except psycopg2.Error as error:
        await interaction.response.send_message(
            f'Что-то пошло не так, напишите {anton_id.mention}. Ошибка: {error}'
        )


@tree.command(name='add_reply', description='Добавляет ответы на определенные слова и фразы для бота')
async def add_reply(interaction: discord.Interaction, phrase: str, response: str):
    await interaction.response.defer(ephemeral=True)
    message_id = uuid.uuid4()
    server_id = interaction.guild_id
    user_id = interaction.user.id
    user_name = interaction.user.name
    request_phrase = phrase.lower()
    response_phrase = response
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = 'INSERT INTO "public".messages (message_id, server_id, request_phrase, respond_phrase, added_by_id, ' \
            'added_by_name, added_at) VALUES (%s,%s,%s,%s,%s,%s,current_timestamp)'
    values = (message_id, server_id, request_phrase, response_phrase, user_id, user_name,)
    try:
        cursor.execute(query, values)
        conn.commit()
        conn.close()
        await interaction.followup.send(f'Фраза "{phrase}" с ответом "{response}" записаны', ephemeral=True)
    except psycopg2.Error as error:
        print(message_id)
        await interaction.followup.send('Не получилось записать словосочетание из-за ошибки {}'.format(error.__str__()))


@tree.command(name='delete_replies', description='Вызывает список ответов')
async def add_reply(interaction: discord.Interaction):
    server_id = interaction.guild_id
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query0 = 'SELECT COUNT(*) FROM "public".messages WHERE server_id=%s'
    value0 = (server_id,)
    cursor.execute(query0, value0)
    number_of_rows = cursor.fetchone()
    print(number_of_rows)
    print(type(number_of_rows))
    if interaction.user.id == 267745993074671616:
        conn, cursor = await basevariables.access_db_on_interaction(interaction)
        query = 'SELECT * from "public".messages WHERE server_id=%s LIMIT 25'
        values = (server_id,)
        cursor.execute(query, values)
        messages = cursor.fetchall()
        query2 = 'SELECT * from "public".messages WHERE server_id=%s LIMIT 25 OFFSET 25'
        cursor.execute(query2, values)
        messages2 = cursor.fetchall()
        conn.close()
        select = DeleteMessagesSelect()
        select2 = DeleteMessagesSelect2()
        for item in messages:
            request = item['request_phrase']
            response = item['respond_phrase']
            message_id = item['message_id']
            label_main = f'{request}-{response}'
            label = label_main[0:99]
            value = f'{message_id}'
            select.add_option(label=label, value=value)
        for item in messages2:
            request = item['request_phrase']
            response = item['respond_phrase']
            message_id = item['message_id']
            label_main = f'{request}-{response}'
            label = label_main[0:99]
            value = f'{message_id}'
            select2.add_option(label=label, value=value)
        view = DeleteMessages()
        view.add_item(select)
        view.add_item(select2)
        await interaction.response.send_message('Посчитали всё, что есть')
        await interaction.channel.send(view=view)
    else:
        await interaction.response.send_message('Тебе это низя')


@tree.command(name='check_dr', description='Проверяет, есть ли у кого-нибудь др. Для тестирования')
async def birthday_check(interaction: discord.Interaction):
    await interaction.response.defer()
    await birthday()
    await interaction.followup.send('OK')


@tree.command(name='help', description='Вызывайте, если что-то сломалось')
async def help(interaction: discord.Interaction):
    lightny = client.get_user(267745993074671616)
    embed_description = f'Если с ботом что-то случилось, писать сюда: {lightny.mention}'
    embed = discord.Embed(colour=discord.Colour.orange(), description=embed_description)
    await interaction.response.send_message(embed=embed)


@tree.command(name='add_birthday_message',
              description='Добавляет сообщение, которое бот использует, чтобы поздравлять именинников')
async def birthday_message(interaction: discord.Interaction, message: str):
    server_id = interaction.guild_id
    bot_message = message
    user_id = interaction.user.id
    user_name = interaction.user.name
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = 'INSERT INTO "public".congratulations (bot_message, server_id, added_at, added_by_id, added_by_name) VALUES (%s,%s,current_timestamp,%s,%s)'
    values = (bot_message, server_id, user_id, user_name,)
    cursor.execute(query, values)
    conn.commit()
    conn.close()
    await interaction.response.send_message(f'Сообщение "{message}" было добавлено', ephemeral=True)


@tree.command(name='birthday_list', description='Показывает все дни рождения на сервере')
async def birthday_list(interaction: discord.Interaction):
    await interaction.response.defer()
    server_id = interaction.guild_id
    old_data = [

    ]
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = 'SELECT user_id, server_id, day, month FROM "public".users WHERE server_id=%s ORDER BY month, day'
    values = (server_id,)
    cursor.execute(query, values)
    birthdays = cursor.fetchall()
    conn.close()
    bd_list = []
    print(birthdays)
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
    print(bd_list)

    for i in bd_list:
        list_user = i['user']
        list_date = i['date']
        old_data.append({
            'label': list_date,
            'value': f'{list_user.mention}'
        })
    print('data before', old_data)
    data = []
    for key, value in itertools.groupby(old_data, key=operator.itemgetter('label')):
        new_key = key
        new_value = ""
        for k in value:
            if new_value is str(""):
                new_value = k['value']
            else:
                new_value += f" и {k['value']}"
            print({
                'label': key,
                'value': k['value']
            })
        data.append({
            'label': new_key,
            'value': new_value
        })
    print('data after', data)

    pagination_view = PaginationView(data, interaction.user)
    pagination_view.data = data
    pagination_view.counted = len(birthdays)
    await pagination_view.send(interaction)
    await interaction.followup.send('Все дни рождения найдены')


@client.event
async def on_message(message):
    def string_found(string1, string2):
        if re.search(r"\b" + re.escape(string1) + r"\b", string2):
            return True
        return False

    user = message.author
    if user:
        if user == client.user:
            return
        else:
            message_content = message.content.lower()
            server_id = message.guild.id
            conn, cursor = await basevariables.access_db_on_message(message)
            query = 'SELECT * from messages WHERE server_id=%s'
            values = (server_id,)
            cursor.execute(query, values)
            all_rows = cursor.fetchall()
            conn.close()
            for item in all_rows:
                request = item['request_phrase']
                response = (item['respond_phrase'])
                if request.startswith('<'):
                    if request in message_content:
                        await message.reply(response)
                else:
                    find_phrase = string_found(request, message_content)
                    if find_phrase is True:
                        try:
                            await message.reply(eval(response))
                        except SyntaxError:
                            await message.reply(response)
                        except NameError:
                            await message.reply(response)


utc = datetime.timezone.utc
check_time = [
    datetime.time(hour=0, tzinfo=utc),
    datetime.time(hour=1, tzinfo=utc),
    datetime.time(hour=2, tzinfo=utc),
    datetime.time(hour=3, tzinfo=utc),
    datetime.time(hour=4, tzinfo=utc),
    datetime.time(hour=5, tzinfo=utc),
    datetime.time(hour=6, tzinfo=utc),
    datetime.time(hour=7, tzinfo=utc),
    datetime.time(hour=8, tzinfo=utc),
    datetime.time(hour=9, tzinfo=utc),
    datetime.time(hour=10, tzinfo=utc),
    datetime.time(hour=11, tzinfo=utc),
    datetime.time(hour=12, tzinfo=utc),
    datetime.time(hour=13, tzinfo=utc),
    datetime.time(hour=14, tzinfo=utc),
    datetime.time(hour=15, tzinfo=utc),
    datetime.time(hour=16, tzinfo=utc),
    datetime.time(hour=17, tzinfo=utc),
    datetime.time(hour=18, tzinfo=utc),
    datetime.time(hour=19, tzinfo=utc),
    datetime.time(hour=20, tzinfo=utc),
    datetime.time(hour=21, tzinfo=utc),
    datetime.time(hour=22, tzinfo=utc),
    datetime.time(hour=23, tzinfo=utc)
]

check_time_1 = [
    datetime.time(hour=0, minute=30, tzinfo=utc),
    datetime.time(hour=1, minute=30, tzinfo=utc),
    datetime.time(hour=2, minute=30, tzinfo=utc),
    datetime.time(hour=3, minute=30, tzinfo=utc),
    datetime.time(hour=4, minute=30, tzinfo=utc),
    datetime.time(hour=5, minute=30, tzinfo=utc),
    datetime.time(hour=6, minute=30, tzinfo=utc),
    datetime.time(hour=7, minute=30, tzinfo=utc),
    datetime.time(hour=8, minute=30, tzinfo=utc),
    datetime.time(hour=9, minute=30, tzinfo=utc),
    datetime.time(hour=10, minute=30, tzinfo=utc),
    datetime.time(hour=11, minute=30, tzinfo=utc),
    datetime.time(hour=12, minute=30, tzinfo=utc),
    datetime.time(hour=13, minute=30, tzinfo=utc),
    datetime.time(hour=14, minute=30, tzinfo=utc),
    datetime.time(hour=15, minute=30, tzinfo=utc),
    datetime.time(hour=16, minute=30, tzinfo=utc),
    datetime.time(hour=17, minute=30, tzinfo=utc),
    datetime.time(hour=18, minute=30, tzinfo=utc),
    datetime.time(hour=19, minute=30, tzinfo=utc),
    datetime.time(hour=20, minute=30, tzinfo=utc),
    datetime.time(hour=21, minute=30, tzinfo=utc),
    datetime.time(hour=22, minute=30, tzinfo=utc),
    datetime.time(hour=23, minute=30, tzinfo=utc)
]


# BD MODULE with checking task
@tasks.loop(time=check_time)
async def birthday():
    conn, cursor = await basevariables.access_db_regular()
    query = 'SELECT * from "public".users as users inner join "public".servers as servers using(server_id)'
    cursor.execute(query)
    values = cursor.fetchall()
    for item in values:
        guild_id = item['server_id']
        guild_role_id = item['role_id']
        print('guild_role_id:', guild_role_id)
        guild = client.get_guild(guild_id)
        guild_role = discord.utils.get(guild.roles, id=guild_role_id)
        print('guild_role:', guild_role.name)
        user_id = item['user_id']
        user = client.get_user(user_id)
        member = guild.get_member(user_id)
        if member is not None:
            if item['timezone'] is not None:
                key = basevariables.t_key
                timezone = item['timezone']
                request = f'http://vip.timezonedb.com/v2.1/get-time-zone?key={key}&format=json&by=zone&zone={timezone}'
                response = requests.get(request)
                time_json = response.json()
                not_formatted = time_json['timestamp']
                formatted = time_json['formatted']
                today = datetime.date.today()
                t_year = today.year
                table_month = item['month']
                table_day = item['day']
                bd_date = datetime.datetime(t_year, table_month, table_day, hour=0, minute=0)
                json_date = datetime.datetime.fromisoformat(formatted)
                json_date_from_timestamp = datetime.datetime.utcfromtimestamp(not_formatted)
                channel_id = item['channel_id']
                channel = client.get_channel(channel_id)
                print(f'{user.name} др:', bd_date)
                print(f'{user.name} проверено в:', json_date)
                print(f'{user.name} дата по timestamp: {json_date_from_timestamp}')
                if json_date.date() == bd_date.date() and json_date.hour == bd_date.hour:
                    query2 = 'SELECT * from "public".congratulations where server_id=%s'
                    values2 = (guild_id,)
                    cursor.execute(query2, values2)
                    greetings = cursor.fetchall()
                    greetings_text = []
                    for rows in greetings:
                        greetings_text.append(rows['bot_message'])
                    message_text = random.choice(greetings_text)
                    embed_description = eval(f'{message_text}')
                    embed = discord.Embed(colour=discord.Colour.dark_gold(), description=embed_description)
                    await channel.send(embed=embed)
                    query3 = 'UPDATE "public".users SET role_added_at=%s WHERE user_id=%s AND server_id=%s'
                    current_time = datetime.datetime.utcnow()
                    values3 = (current_time, user_id, guild_id,)
                    cursor.execute(query3, values3)
                    conn.commit()
                    conn.close()
                    await member.add_roles(guild_role)
                else:
                    print('ne dr')
            else:
                print(f'{user_id} не указал свой часовой пояс, проверить невозможно')
        else:
            print(f'{user_id} is not a member of the server "{guild.name}"')
    conn.close()
    print('the end')
    conn, cursor = await basevariables.access_db_regular()
    query_last = 'SELECT * from "public".users inner join "public".servers using(server_id)'
    cursor.execute(query_last)
    users_check_roles = cursor.fetchall()
    for i in users_check_roles:
        role_time = i['role_added_at']
        role_guild_id = i['server_id']
        role_user_id = i['user_id']
        server_role_id = i['role_id']
        if role_time is not None:
            current_time_now = datetime.datetime.utcnow()
            timedelta = current_time_now - role_time
            current_guild = client.get_guild(role_guild_id)
            current_member = current_guild.get_member(role_user_id)
            current_role = discord.utils.get(current_guild.roles, id=server_role_id)
            print('timedelta in days:', timedelta.days)
            if timedelta.days >= 1:
                print('checked role is older than 1 day')
                await current_member.remove_roles(current_role)
                query_last_for_sure = 'UPDATE "public".users SET role_added_at=%s WHERE server_id=%s AND user_id=%s'
                role_added_at = None
                values_last = (role_added_at, role_guild_id, role_user_id,)
                cursor.execute(query_last_for_sure, values_last)
                conn.commit()
                print(f'role removed from user {user.name}')
            else:
                print(f'role {current_role.name} on user {user.name} is not older than 1 day')
        else:
            print('no role is given')
    conn.close()


@tasks.loop(minutes=10)
async def update_releases():
    channel_id = 1068896806156632084
    release_date, release_title, release_text = await github_api.get_release_notes()
    if release_title is not None and release_text is not None and release_date is not None:
        channel = client.get_channel(channel_id)
        embed = discord.Embed(
            title=f'{release_title}',
            colour=discord.Colour.from_rgb(3, 144, 252)
        )
        embed.add_field(name='Описание релиза', value=f'{release_text}')
        embed.add_field(name='Дата релиза:', value=f'{release_date}')
        await channel.send(embed=embed)
    else:
        print('No new releases')


# EXECUTES THE BOT WITH THE SPECIFIED TOKEN.
client.run(DISCORD_TOKEN)

import itertools
import operator
import string

import discord
import datetime
import discord.ui
from discord import app_commands
from discord.ext import tasks
import os
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
import uuid
import re
import requests
import random
import calendar
import demoji
import pytz

# project files
from misc_files import basevariables, github_api
from views.birthday.change_date import UserAlreadyExists
from views.replies.delete_multiple_replies import DeleteReplyMultiple, DeleteReplyMultipleSelect
from views.replies.delete_one_reply import DeleteOneReply
from views.pagination.pagination import PaginationView
from views.birthday.settings import BirthdaysButtonsSelect, GuildAlreadyExists
from views.birthday.timezones import DropdownTimezones
from views.misc_commands.delete_channels import DropDownViewChannels
from views.misc_commands.roles import DropDownRoles

load_dotenv()
# Grab the API token from the .env file.
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Register UUID to work with it in psycopg2
psycopg2.extras.register_uuid()


intents = discord.Intents.all()
intents.message_content = True
intents.voice_states = True


# main class
class Aclient(discord.AutoShardedClient):
    def __init__(self):
        super().__init__(intents=intents, shard_count=2)
        self.added = False
        self.synced = False  # we use this so the bot doesn't sync commands more than once

    # commands local sync
    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:  # check if slash commands have been synced
            await tree.sync(guild=discord.Object(id=779677470156390440))  # zagloti guild
            await tree.sync()  # global (can take 1-24 hours)
            self.synced = True
        if not self.added:
            # self.add_view(DropDownViewChannels())
            self.added = True
        birthday.start()
        update_releases.start()
        print(f"We have logged in as {self.user}.")


client = Aclient()
tree = app_commands.CommandTree(client)


# say hello command
@tree.command(guild=discord.Object(id=779677470156390440), name='say_hello',
              description='testing_commands')
async def slash1(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Привет, {interaction.user.display_name}, я работаю! Меня сделал Антон на питоне", ephemeral=False)


# delete messages
@tree.command(guild=discord.Object(id=779677470156390440), name='delete_last_x_messages',
              description='для удаления последних сообщений')
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
@tree.command(guild=discord.Object(id=779677470156390440), name='roles',
              description='Даёт возможность выбирать роли')
async def roles2(interaction: discord.Interaction):
    embed = discord.Embed(title='Выбери нужные тебе роли!', colour=discord.Colour.dark_magenta())
    view = DropDownRoles(interaction.user)
    message = await interaction.channel.send(embed=embed, view=view)
    view.message = message
    await interaction.response.send_message(
        f'{interaction.user.display_name}, ты запустил новую систему выбора ролей. Она более красивая и вообще секс',
        ephemeral=True)


# delete_channels.py
@tree.command(guild=discord.Object(id=779677470156390440), name='delete_channels', description='Даёт возможность выбрать каналы для удаления')
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
    await interaction.response.defer(thinking=True, ephemeral=True)
    if month.value == '02' and day > 28:
        await interaction.followup.send(
            'Извини, в Феврале не бывает больше 28 дней (Я знаю, что бывает 29, но пока бот не умеет его корректно проверять)')
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
                embed = discord.Embed(title='А теперь выбери часовой пояс')
                view = DropdownTimezones(day, month.name)
                view.user = interaction.user
                message = await interaction.followup.send(f'Всё записано, спасибо. День: {day}, месяц: {month.name}', embed=embed, view=view)
                view.message = message
            else:
                day_record = row['day']
                month_record = row['month']
                timezone_record = row['timezone']
                embed = discord.Embed(title='Тебя это устраивает?')
                view = UserAlreadyExists()
                view.user = interaction.user
                message = await interaction.followup.send(
                    f'Твой др уже записан. День: {day_record}, месяц: {month_record}, часовой пояс: {timezone_record}', embed=embed, view=view, ephemeral=True)
                view.message = message
            conn.close()
        except psycopg2.errors.ForeignKeyViolation as nameerror:
            await interaction.followup.send(
                'Сервер ещё не настроен или что-то пошло не так. Напишите админу сервера или создателю бота')
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
    def em_replace(string):
        emoji = demoji.findall(string)
        for i in emoji:
            unicode = i.encode('unicode-escape').decode('ASCII')
            print('unicode:', unicode)
            string = string.replace(i, unicode)
        return string

    def e_replace(string):
        string_new = string.replace('ё', 'е')
        return string_new

    def add_fstring(string):
        add_string = (f'{string}')
        string_new = string.replace(string, f'{add_string}')
        return string_new

    await interaction.response.defer(ephemeral=True)
    message_id = uuid.uuid4()
    server_id = interaction.guild_id
    user_id = interaction.user.id
    user_name = interaction.user.name
    request_phrase_base = phrase.lower()
    request_phrase = em_replace(e_replace(request_phrase_base))
    response_phrase = add_fstring(response)
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


@tree.command(name='delete_reply', description='Позволяет удалить заведенные триггеры на фразы')
async def delete_reply_2(interaction: discord.Interaction, reply: str):
    user = interaction.user
    server_id = interaction.guild_id
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = 'SELECT server_id, request_phrase, respond_phrase, added_by_name, added_at, message_id from "public".messages WHERE server_id=%s AND request_phrase=%s'
    values = (server_id, reply,)
    cursor.execute(query, values)
    results = cursor.fetchall()
    results_count = len(results)
    conn.close()
    if results_count > 1:
        view = DeleteReplyMultiple(interaction)
        select = DeleteReplyMultipleSelect(interaction, view)
        for item in results:
            label_base = item['respond_phrase']
            label = label_base[0:99]
            value = str(item['message_id'])
            select.add_option(label=label, value=value)
        view.add_item(select)
        await interaction.response.send_message(f'Варианта больше одного, их {results_count}. Выдаём выпадашку',
                                                view=view, ephemeral=True)
    else:
        for item in results:
            message_id = item['message_id']
            request_phrase = item['request_phrase']
            respond_phrase = item['respond_phrase']
            added_by_name = item['added_by_name']
            added_at_base = item['added_at']
            added_at = added_at_base.astimezone(pytz.timezone('EUROPE/MOSCOW')).strftime('%Y-%m-%d %H:%M:%S')
            embed = discord.Embed(title='Выбранное сообщение', colour=discord.Colour.random())
            embed.add_field(name='Триггер:', value=request_phrase)
            embed.add_field(name='Ответ:', value=respond_phrase, inline=False)
            embed.add_field(name='Кто добавил:', value=added_by_name)
            embed.add_field(name='Когда добавил (МСК время):', value=added_at)
            view = DeleteOneReply(interaction, user, message_id)
            await interaction.response.send_message(view=view, embed=embed, ephemeral=True)


@delete_reply_2.autocomplete('reply')
async def delete_reply_2_autocomplete(interaction: discord.Interaction, current: str):
    server_id = interaction.guild_id
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = 'SELECT request_phrase from "public".messages WHERE request_phrase LIKE %s AND server_id=%s LIMIT 25 '
    request_string = f'{current}%'
    values = (request_string, server_id,)
    cursor.execute(query, values)
    result = cursor.fetchall()
    conn.close()
    result_list = []
    for item in result:
        new_item = str(item)
        new_value = new_item[2:-2]
        result_list.append(app_commands.Choice(name=new_value, value=new_value))
    return result_list


@tree.command(name='check_dr', description='Форсированно запускает проверку на дни рождения в этом часу')
async def birthday_check(interaction: discord.Interaction):
    await interaction.response.defer()
    await birthday()
    await interaction.followup.send('OK')


@tree.command(name='help', description='Вызывайте, если что-то сломалось')
async def help(interaction: discord.Interaction):
    lightny_role = interaction.guild.get_role(1093537843307102289)
    embed_description = f'Если с ботом что-то случилось, пингуйте меня: {lightny_role.mention}'
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
    print(birthdays)
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


@tree.command(name='show_replies', description='Вызывает список всех вопросов-ответов на сервере')
async def show_replies(interaction: discord.Interaction):
    await interaction.response.defer()
    server_id = interaction.guild_id
    data = []
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = 'SELECT request_phrase, respond_phrase, server_id, added_at from "public".messages WHERE server_id=%s ORDER BY request_phrase'
    values = (server_id,)
    cursor.execute(query, values)
    replies = cursor.fetchall()
    conn.close()
    for item in replies:
        request = item['request_phrase']
        response = item['respond_phrase']
        data.append({
            'label': f'Триггер: {request}',
            'value': f'Ответ: {response}'
        })

    title = 'Триггеры на сервере'
    footer = 'Всего ответов'
    maximum = 'ответов'
    pagination_view = PaginationView(data, interaction.user, title, footer, maximum, separator=8)
    pagination_view.data = data
    pagination_view.counted = len(replies)
    try:
        await pagination_view.send(interaction)
        await interaction.followup.send('Держи, искал по всему серваку')
    except discord.app_commands.CommandInvokeError as error:
        await interaction.followup.send(f'Что-то пошло не так, скорее всего, бот попытался отправить тебе слишком большое количество текста.'
                                        f' \nВ таком случае обратись к Антону, он снизит количество штук на странице. \nНа всякий случай, вот ошибка:{error}')


async def twitter_link_replace(message, from_user, attachment):
    webhook = await message.channel.create_webhook(name=from_user.name)
    new_message = message.content.replace('twitter', 'fxtwitter')
    await webhook.send(str(new_message), username=from_user.name, avatar_url=from_user.avatar, files=attachment)
    webhooks = await message.channel.webhooks()
    for webhook in webhooks:
        await webhook.delete()


@client.event
async def on_message(message):
    def string_found(string1, string2):
        search = re.search(r"\b" + re.escape(string1) + r"\b", string2)
        if search:
            return True
        return False

    def em_replace(string):
        emoji = demoji.findall(string)
        for i in emoji:
            unicode = i.encode('unicode-escape').decode('ASCII')
            string = string.replace(i, unicode)
        return string

    def e_replace(string):
        string_new = string.replace('ё', 'е')
        return string_new

    user = message.author
    if user:
        if user == client.user:
            return
        else:
            # start = timer()
            message_content_base = message.content.lower()
            message_content_e = em_replace(message_content_base)
            message_content_punct = e_replace(message_content_e)
            message_content = message_content_punct.translate(str.maketrans('', '', string.punctuation))
            server_id = message.guild.id
            conn, cursor = await basevariables.access_db_on_message(message)
            query = 'SELECT * from messages WHERE server_id=%s'
            values = (server_id,)
            cursor.execute(query, values)
            all_rows = cursor.fetchall()
            conn.close()
            for item in all_rows:
                request_base = item['request_phrase']
                request = request_base.translate(str.maketrans('', '', string.punctuation))
                response_base = (item['respond_phrase'])
                response = string.Template("f'$string'").substitute(string=response_base)
                if request_base.startswith('<'):
                    if request in message_content:
                        await message.reply(response_base)
                else:
                    find_phrase = string_found(request, message_content)
                    if find_phrase is True:
                        if not message.content.isupper():
                            try:
                                await message.reply(eval(response))
                            except SyntaxError:
                                await message.reply(response_base)
                            except NameError:
                                await message.reply(response_base)
                        else:
                            response = response.upper()
                            try:
                                await message.reply(eval(response))
                            except SyntaxError:
                                await message.reply(response_base.upper())
                            except NameError:
                                await message.reply(response_base.upper())
        if 'https://twitter.com/' in message_content_base:
            files = []
            for item in message.attachments:
                file = await item.to_file()
                files.append(file)
            await message.delete()
            await twitter_link_replace(message, user, attachment=files)
    # end = timer()
    # try:
    #     if reply_message is not None:
    #         await reply_message.reply(f'Время выполнения:{end-start}')
    # except UnboundLocalError:
    #     return


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
    conn.close()
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
                    conn, cursor = await basevariables.access_db_regular()
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
            user_id = i['user_id']
            user = client.get_user(user_id)
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
    sanya_channel_id = 1099032346507890748
    # zds_guild_id = 478278763239702538
    release_date, release_title, release_text = await github_api.get_release_notes()
    if release_title is not None and release_text is not None and release_date is not None:
        channel = client.get_channel(channel_id)
        channel_main = client.get_channel(sanya_channel_id)
        embed = discord.Embed(
            title=f'{release_title}',
            colour=discord.Colour.from_rgb(3, 144, 252)
        )
        embed.add_field(name='Описание релиза', value=f'{release_text}')
        embed.add_field(name='Дата релиза (Мск):', value=f'{release_date}')
        await channel.send(embed=embed)
        await channel_main.send(embed=embed)
    else:
        print('No new releases')


@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    conn, cursor = await basevariables.access_db_basic()
    query = 'SELECT * from "public".voice_temp WHERE server_id=%s'
    server_id = member.guild.id
    values = (server_id,)
    cursor.execute(query, values)
    temp_channels_info = cursor.fetchall()
    temp_channels = []
    for i in temp_channels_info:
        temp_channels.append(i['voice_channel_id'])

    possible_channel_name = f"Канал имени {member.display_name}"
    if after.channel:
        if after.channel.id == 1099061215801639073:
            temp_channel = await after.channel.clone(name=possible_channel_name)
            await member.move_to(temp_channel)
            query2 = 'INSERT into "public".voice_temp (server_id, voice_channel_id) values (%s,%s)'
            values2 = (server_id, temp_channel.id,)
            cursor.execute(query2, values2)
            conn.commit()

    if before.channel:
        if before.channel.id in temp_channels:
            if len(before.channel.members) == 0:
                await before.channel.delete()
                await basevariables.delete_channel_id(before.channel.id, server_id, conn, cursor)
    conn.close()


# EXECUTES THE BOT WITH THE SPECIFIED TOKEN.
client.run(DISCORD_TOKEN)

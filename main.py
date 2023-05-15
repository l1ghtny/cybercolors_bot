import itertools
import operator

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
import calendar
import demoji
import pytz

from modules.birthdays_module.hourly_check.check_birthday import check_birthday
from modules.birthdays_module.hourly_check.check_roles import check_roles
from modules.birthdays_module.hourly_check.check_time import check_time
from misc_files import basevariables
from modules.logs_setup import logger
from modules.on_message_processing.bot_reply import look_for_bot_reply
from modules.on_message_processing.replies import check_for_replies
from modules.on_voice_state_processing.create_voice_channel import create_voice_channel
from modules.releases.releases_check import check_new_releases
from modules.twitter_link_fix.twitter_message_manager import manage_message
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

logger = logger.logging.getLogger("bot")


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
        logger.info(f"We have logged in as {self.user}.")


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
@tree.command(guild=discord.Object(id=779677470156390440), name='delete_channels',
              description='Даёт возможность выбрать каналы для удаления')
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
                message = await interaction.followup.send(f'Всё записано, спасибо. День: {day}, месяц: {month.name}',
                                                          embed=embed, view=view)
                view.message = message
            else:
                day_record = row['day']
                month_record = row['month']
                timezone_record = row['timezone']
                embed = discord.Embed(title='Тебя это устраивает?')
                view = UserAlreadyExists()
                view.user = interaction.user
                message = await interaction.followup.send(
                    f'Твой др уже записан. День: {day_record}, месяц: {month_record}, часовой пояс: {timezone_record}',
                    embed=embed, view=view, ephemeral=True)
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
            logger.info(f'unicode: {unicode}')
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
        logger.info(f'{message_id}')
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
        await interaction.followup.send(
            f'Что-то пошло не так, скорее всего, бот попытался отправить тебе слишком большое количество текста.'
            f' \nВ таком случае обратись к Антону, он снизит количество штук на странице. \nНа всякий случай, вот ошибка:{error}')


@tree.command(name='count_tokens_by_day', description='посчитаю, сколько тебе стоил один день использования бота')
async def count_tokens_by_day(interaction: discord.Interaction, day: str):
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    server_id = interaction.guild_id
    query = """select sum(g.token_amount), count(g.reply_link)
    from (select to_char(datetime_added:: DATE, 'dd-mm-yyyy') as date_added, token_amount, reply_link, server_id 
    from "public".count_tokens) as g where g.date_added = %s and g.server_id = %s"""
    values = (day, server_id)
    cursor.execute(query, values)
    tokens_sum = cursor.fetchone()
    tokens_counted = tokens_sum['sum']
    days_counted = tokens_sum['count']
    conn.close()
    cost = tokens_counted / 1000 * 0.002
    embed = discord.Embed(colour=discord.Colour.dark_magenta())
    embed.add_field(name='дата:', value=day)
    embed.add_field(name='количество сообщений:', value=days_counted)
    embed.add_field(name='количество токенов:', value=tokens_counted)
    embed.add_field(name='стоимость в долларах:', value=cost)
    await interaction.response.send_message(embed=embed)


@count_tokens_by_day.autocomplete('day')
async def count_tokens_by_day_autocomplete(interaction: discord.Interaction, current: str):
    date_str = f'{current}%'
    server_id = interaction.guild_id
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = """select distinct g.date_added, g.datetime_added
    from (select to_char(datetime_added:: DATE, 'dd-mm-yyyy') as date_added, token_amount, reply_link, server_id, datetime_added
    from "public".count_tokens) as g
    where g.date_added like %s and server_id = %s ORDER BY g.datetime_added DESC LIMIT 25"""
    values = (date_str, server_id)
    cursor.execute(query, values)
    result = cursor.fetchall()
    result_list = []
    for i in result:
        new_value = i['date_added']
        result_list.append(app_commands.Choice(name=new_value, value=new_value))
    conn.close()
    return result_list


@tree.command(name='most_expensive_message_today', description='показываю, какое сообщение было сегодня самое дорогое')
async def most_expensive_message_today(interaction: discord.Interaction):
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    today = datetime.datetime.today().date()
    server_id = interaction.guild_id
    query = """select g.date_added, g.token_amount, g.reply_link, g.server_id, g.today 
    from (select datetime_added::TIMESTAMP::DATE as date_added, token_amount, reply_link, server_id, current_date as today
    from "public".count_tokens) as g 
    where g.date_added = %s AND g.server_id = %s order by g.token_amount desc"""
    values = (today, server_id,)
    cursor.execute(query, values)
    message = cursor.fetchone()
    token_amount = message['token_amount']
    message_url = message['reply_link']
    embed = discord.Embed(colour=discord.Colour.dark_gold())
    embed.add_field(name='Количество токенов', value=token_amount)
    embed.add_field(name='ссылка на сообщение', value=message_url)
    await interaction.response.send_message(embed=embed)


@client.event
async def on_message(message):
    user = message.author
    message_content_base = message.content.lower()
    if user:
        if user == client.user:
            return
        else:
            # start = timer()
            if 'https://twitter.com/' in message_content_base:
                await manage_message(message, user)
            conn, cursor, database_found, server_id = await check_for_replies(message)
        if database_found is False:
            await look_for_bot_reply(message, client, server_id, cursor, conn)


# BD MODULE with checking task
@tasks.loop(time=check_time)
async def birthday():
    await check_birthday(client)
    await check_roles(client)


@tasks.loop(minutes=10)
async def update_releases():
    await check_new_releases(client)


@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    await create_voice_channel(member, before, after)


# EXECUTES THE BOT WITH THE SPECIFIED TOKEN.
client.run(DISCORD_TOKEN, root_logger=True)

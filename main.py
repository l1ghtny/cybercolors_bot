import discord
import discord.ui
from discord import app_commands
from discord.ext import tasks
import os
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
import uuid
import demoji
import pytz
from sqlmodel import select

from src.commands.misc.cats import cat_command, cat_command_text
from src.db.database import get_session
from src.db.models import Server, Message
from src.modules.birthdays_module.hourly_check.force_check_birthday import force_check_birthday
from src.modules.birthdays_module.user_validation.user_validate_time import users_time
from src.commands.birthdays.add_new_birthday import add_birthday
from src.commands.birthdays.show_birthday_list import send_birthday_list
from src.misc_files.blocking_script import run_blocking
from src.modules.birthdays_module.hourly_check.check_birthday_redone import check_birthday_new
from src.modules.birthdays_module.hourly_check.check_roles import check_roles
from src.modules.birthdays_module.hourly_check.check_time import check_time
from src.misc_files import basevariables
from src.modules.birthdays_module.user_validation.validation_main import main_validation_process
from src.modules.logs_setup import logger
from src.modules.on_message_processing.check_for_links import delete_server_links
from src.modules.on_message_processing.gpt_bot_reply import look_for_bot_reply
from src.modules.on_message_processing.replies import check_for_replies
from src.modules.on_voice_state_processing.create_voice_channel import create_voice_channel
from src.modules.twitter_link_fix.twitter_message_manager import manage_message
from src.views.replies.delete_multiple_replies import DeleteReplyMultiple, DeleteReplyMultipleSelect
from src.views.replies.delete_one_reply import DeleteOneReply
from src.views.pagination.pagination import PaginationView
from src.views.birthday.settings import BirthdaysButtonsSelect, GuildAlreadyExists
from src.views.misc_commands.delete_channels import DropDownViewChannels
from src.views.misc_commands.roles import DropDownRoles

load_dotenv()
# Grab the API token from the .env file.
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_TOKEN_TEST = os.getenv('DISCORD_TOKEN_TEST')

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
            await tree.sync()  # global (can take 1-24 hours)
            self.synced = True
        if not self.added:
            self.added = True
        # birthday.start()
        # # update_releases.start()
        # check_users_with_birthdays.start()
        logger.info(f"We have logged in as {self.user}.")


client = Aclient()
tree = app_commands.CommandTree(client)


# Add birthdays to the database
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
    await add_birthday(client, interaction, month, day)


# TODO:
#  1. Move it to a dedicated function
#  2. Move the feature to the UI
@tree.command(name='birthdays_settings', description='Настрой дни рождения для своего сервера')
async def birthdays_settings(interaction: discord.Interaction):
    await interaction.response.defer()
    server_id = interaction.guild.id
    try:
        async with get_session() as session:
            query = select(Server).where(Server.server_id == server_id)
            result = await session.exec(query)
            server_settings = result.first()
            if server_settings is None:
                embed = discord.Embed(title='Давай решим, в каком канале будет писать бот',
                                      colour=discord.Colour.dark_blue())
                view = BirthdaysButtonsSelect()
                await interaction.edit_original_response(content=
                    f'{interaction.user.display_name}, начинаем настройку дней рождений!')
                message = await interaction.channel.send(embed=embed, view=view)
                view.message = message
                view.user = interaction.user
            else:
                channel_name = server_settings.birthday_channel_name
                server_name = server_settings.server_name
                server_role_id = server_settings.birthday_role_id
                server_role_try = interaction.guild.get_role(server_role_id)
                server_role = server_role_try if server_role_try is not None else 'Не выбрано'
                embed = discord.Embed(title='Этот сервер уже настроен', colour=discord.Colour.orange())
                view = GuildAlreadyExists()
                await interaction.edit_original_response(content=
                    f'Для сервера "{server_name}" выбран канал "{channel_name}" и выбрана роль "{server_role}"')
                message = await interaction.channel.send(embed=embed, view=view)
                view.message = message
                view.user = interaction.user
    except Exception as error:
        await interaction.edit_original_response(content=f'Что-то пошло не так')
        raise Exception(error)


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
    request_phrase_base = phrase.lower()
    request_phrase = em_replace(e_replace(request_phrase_base))
    response_phrase = add_fstring(response)
    try:
        async with get_session() as session:
            message_to_add = Message(message_id=message_id, server_id=server_id, request_phrase=request_phrase,
                                     respond_phrase=response_phrase, added_by_user_id=user_id)
            session.add(message_to_add)
            await session.commit()
            await interaction.followup.send(f'Фраза "{phrase}" с ответом "{response}" записаны', ephemeral=True)
    except Exception as error:
        await interaction.followup.send('Не получилось записать словосочетание из-за ошибки {}'.format(error.__str__()))
        raise Exception(error)


@tree.command(name='delete_reply', description='Позволяет удалить заведенные триггеры на фразы')
async def delete_reply_2(interaction: discord.Interaction, reply: str):
    reply = '%' + reply.replace("\\\\", "\\") + '%'
    user = interaction.user
    server_id = interaction.guild_id
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = 'SELECT server_id, request_phrase, respond_phrase, added_by_name, added_at, message_id from "public".messages WHERE server_id=%s AND request_phrase LIKE %s'
    values = (server_id, reply,)
    sql_query = cursor.mogrify(query, values)
    print(sql_query.decode('utf-8'))
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
            view = DeleteOneReply(interaction, user, message_id, True)
            await interaction.response.send_message(view=view, embed=embed, ephemeral=True)


@delete_reply_2.autocomplete('reply')
async def delete_reply_2_autocomplete(interaction: discord.Interaction, current: str):
    server_id = interaction.guild_id
    query = 'SELECT request_phrase from "public".messages WHERE request_phrase LIKE %s AND server_id=%s LIMIT 25;'
    request_string = f'%{current}%'
    values = (request_string, server_id,)
    async with get_session() as session:
        query = select(Message).where(Message.request_phrase)
    cursor.execute(query, values)
    result = cursor.fetchall()
    conn.close()
    result_list = []
    for item in result:
        new_item = str(item)
        new_value = new_item[2:-2]
        if len(new_value) > 100:
            new_value = new_value[:96] + '...'
        result_list.append(app_commands.Choice(name=new_value, value=new_value))
    return result_list


@tree.command(name='check_dr', description='Форсированно запускает проверку на дни рождения, если сегодня кому-то не выдали роль')
async def birthday_check(interaction: discord.Interaction):
    await interaction.response.defer()
    await birthday()
    await force_check_birthday(client)
    await interaction.followup.send('OK')


# Needs to be implemented with UI
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
    await send_birthday_list(client, interaction)


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


# Тоже должно жить в UI
@tree.command(name='show_usage_by_day', description='посчитаю, сколько тебе стоил один день использования бота')
async def show_usage_by_day(interaction: discord.Interaction, day: str):
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


@show_usage_by_day.autocomplete('day')
async def show_usage_by_day_autocomplete(interaction: discord.Interaction, current: str):
    date_str = f'{current}%'
    server_id = interaction.guild_id
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = """
    select distinct on (g.month_added, g.date_added)
    g.date_added, g.datetime_added
    from (select to_char(datetime_added:: DATE, 'dd-mm-yyyy') as date_added, to_char(datetime_added:: DATE, 'mm-yyyy') as month_added, token_amount, reply_link, server_id, datetime_added
    from "public".count_tokens) as g
    where g.date_added like %s and server_id = %s ORDER BY g.month_added DESC, g.date_added DESC, g.datetime_added LIMIT 25"""
    values = (date_str, server_id)
    cursor.execute(query, values)
    result = cursor.fetchall()
    result_list = []
    for i in result:
        new_value = i['date_added']
        result_list.append(app_commands.Choice(name=new_value, value=new_value))
    conn.close()
    return result_list


# Тоже должно жить в UI
@tree.command(name='show_usage_by_month',
              description='показывает расходы на использование chatgpt на определенном сервере за определенный месяц')
async def show_usage_by_month(interaction: discord.Interaction, month: str):
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    server_id = interaction.guild_id
    query = """select sum(g.token_amount), count(g.reply_link)
        from (select to_char(datetime_added:: DATE, 'mm-yyyy') as date_added, token_amount, reply_link, server_id 
        from "public".count_tokens) as g where g.date_added = %s and g.server_id = %s"""
    values = (month, server_id)
    cursor.execute(query, values)
    tokens_sum = cursor.fetchone()
    tokens_counted = tokens_sum['sum']
    days_counted = tokens_sum['count']
    conn.close()
    cost = tokens_counted / 1000 * 0.002
    embed = discord.Embed(colour=discord.Colour.dark_magenta())
    embed.add_field(name='дата:', value=month)
    embed.add_field(name='количество сообщений:', value=days_counted)
    embed.add_field(name='количество токенов:', value=tokens_counted)
    embed.add_field(name='стоимость в долларах:', value=cost)
    await interaction.response.send_message(embed=embed)


@show_usage_by_month.autocomplete('month')
async def show_usage_by_month_autocomplete(interaction: discord.Interaction, current: str):
    date_str = f'{current}%'
    server_id = interaction.guild_id
    conn, cursor = await basevariables.access_db_on_interaction(interaction)
    query = """
    select distinct on (g.date_added)
    g.date_added, g.datetime_added
        from (select to_char(datetime_added:: DATE, 'mm-yyyy') as date_added, token_amount, reply_link, server_id, datetime_added
        from "public".count_tokens) as g
        where g.date_added like %s and server_id = %s ORDER BY g.date_added DESC, g.datetime_added LIMIT 25"""
    values = (date_str, server_id)
    cursor.execute(query, values)
    result = cursor.fetchall()
    result_list = []
    for i in result:
        new_value = i['date_added']
        result_list.append(app_commands.Choice(name=new_value, value=new_value))
    conn.close()
    return result_list


@tree.command(name='force_validation',
              description='command for testing purposes to check if validation works fine or not')
async def force_validation(interaction: discord.Interaction):
    await check_users_with_birthdays()
    await interaction.response.send_message('команда выполнена')


@tree.command(name='cat_text', description='Котя с текстом')
async def cat_text(interaction: discord.Interaction, text: str):
    await cat_command_text(interaction, text)


@tree.command(name='cat', description='cat')
async def cat(interaction: discord.Interaction):
    await cat_command(interaction)


@client.event
async def on_message(message):
    user = message.author
    message_content_base = message.content.lower()
    server = message.guild
    await delete_server_links(message, message_content_base)
    if user and server:
        if user == client.user:
            return
        else:
            if 'https://twitter.com/' in message_content_base:
                await manage_message(message, user)
            elif 'https://x.com/' in message_content_base:
                await manage_message(message, user)
            conn, cursor, database_found, server_id = await check_for_replies(message)
        if database_found is False:
            await look_for_bot_reply(message, client, server_id, cursor, conn)


# BD MODULE with checking task
@tasks.loop(time=check_time)
async def birthday():
    await check_birthday_new(client)
    await check_roles(client)


@tasks.loop(time=users_time)
async def check_users_with_birthdays():
    logger.info('validation process started')
    await run_blocking(client, main_validation_process, client)


@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    await create_voice_channel(member, before, after)


# def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
#     logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
#     # Optionally, you can re-raise the exception or perform other actions

# sys.excepthook = handle_uncaught_exception


# EXECUTES THE BOT WITH THE SPECIFIED TOKEN.
client.run(DISCORD_TOKEN_TEST, root_logger=True)

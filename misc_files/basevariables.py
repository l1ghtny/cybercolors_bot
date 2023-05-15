import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import NamedTupleCursor
from modules.logs_setup import logger

load_dotenv()

database = os.getenv("database")
host = os.getenv("host")
user = os.getenv("user")
password = os.getenv("password")
port = os.getenv("port")
t_key = os.getenv("timezonedb_key")

logger = logger.logging.getLogger("bot")

async def create_new_channel(interaction, new_channel):
    server_id = f'{interaction.guild.id}'
    channel_id = f'{new_channel.id}'
    server_name = f'{interaction.guild.name}'
    channel_name = f'{new_channel.name}'
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
        await interaction.response.send_message(f'Выбранный канал: {new_channel.mention}')
    except psycopg2.Error as error:
        await interaction.response.send_message(
            'Добавить канал не получилось из-за ошибки "{}"'.format(error.__str__()))


async def update_channel_values(interaction, new_channel):
    server_id = f'{interaction.guild.id}'
    channel_id = f'{new_channel.id}'
    channel_name = f'{new_channel.name}'
    try:
        conn = psycopg2.connect(database=database,
                                host=host,
                                user=user,
                                password=password,
                                port=port)
        cursor = conn.cursor()
        postgres_insert_query = """UPDATE "public".servers SET channel_id = %s, channel_name = %s WHERE server_id = %s"""
        record_to_insert = (channel_id, channel_name, server_id)
        cursor.execute(postgres_insert_query, record_to_insert)
        conn.commit()
        conn.close()
        await interaction.response.send_message(f'Выбранный канал: {new_channel.mention}')
    except psycopg2.Error as error:
        await interaction.response.send_message(
            'Добавить канал не получилось из-за ошибки "{}"'.format(error.__str__()))


async def check_guild_id(interaction):
    server_id = f'{interaction.guild.id}'
    try:
        conn = psycopg2.connect(database=database,
                                host=host,
                                user=user,
                                password=password,
                                port=port,
                                cursor_factory=psycopg2.extras.DictCursor)
        cursor = conn.cursor()
        postgres_insert_query = """SELECT * FROM "public".servers WHERE server_id = %s"""
        record_to_insert = (server_id,)
        cursor.execute(postgres_insert_query, record_to_insert)
        row = cursor.fetchone()
        conn.close()
        return row
    except psycopg2.Error as error:
        await interaction.response.send_message(
            'Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def access_db_on_message(message):
    try:
        conn = psycopg2.connect(database=database,
                                host=host,
                                user=user,
                                password=password,
                                port=port,
                                cursor_factory=psycopg2.extras.DictCursor)
        cursor = conn.cursor()
        return conn, cursor
    except psycopg2.Error as error:
        logger.info(
            'Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def access_db_on_interaction(interaction):
    try:
        conn = psycopg2.connect(database=database,
                                host=host,
                                user=user,
                                password=password,
                                port=port,
                                cursor_factory=psycopg2.extras.DictCursor)
        cursor = conn.cursor()
        return conn, cursor
    except psycopg2.Error as error:
        await interaction.response.send_message(
            'Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def access_db_regular():
    try:
        conn = psycopg2.connect(database=database,
                                host=host,
                                user=user,
                                password=password,
                                port=port,
                                cursor_factory=psycopg2.extras.DictCursor)
        cursor = conn.cursor()
        return conn, cursor
    except psycopg2.Error as error:
        logger.info('Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def update_server_role(interaction, server_id, role_id, role_name):
    try:
        conn = psycopg2.connect(database=database,
                                host=host,
                                user=user,
                                password=password,
                                port=port,
                                cursor_factory=psycopg2.extras.DictCursor)
        cursor = conn.cursor()
        query = 'UPDATE "public".servers SET role_id=%s WHERE server_id=%s'
        values = (role_id, server_id)
        cursor.execute(query, values)
        conn.commit()
        conn.close()
        await interaction.response.send_message(f'Роль "{role_name}" добавлена, спасибо')
    except psycopg2.Error as error:
        await interaction.response.send_message(
            'Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def access_db_basic():
    try:
        conn = psycopg2.connect(database=database,
                                host=host,
                                user=user,
                                password=password,
                                port=port,
                                cursor_factory=psycopg2.extras.DictCursor)
        cursor = conn.cursor()
        return conn, cursor
    except psycopg2.Error as error:
        logger.info(
            'Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def add_new_day_month(server_id, user_id, day, month, interaction):
    try:
        conn = psycopg2.connect(database=database,
                                host=host,
                                user=user,
                                password=password,
                                port=port,
                                cursor_factory=psycopg2.extras.DictCursor)
        cursor = conn.cursor()
        query = 'INSERT INTO "public".users (server_id, user_id, day, month) VALUES (%s,%s,%s,%s)'
        values = (server_id, user_id, day, month,)
        cursor.execute(query, values)
        conn.commit()
        conn.close()
        status = 'ok'
        return status
    except psycopg2.Error as error:
        await interaction.response.send_message(
            'Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def delete_channel_id(channel_id, server_id, conn, cursor):
    query = 'DELETE FROM "public".voice_temp WHERE server_id=%s AND voice_channel_id=%s'
    values = (server_id, channel_id,)
    cursor.execute(query, values)
    conn.commit()

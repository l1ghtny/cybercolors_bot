import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import NamedTupleCursor
from sqlmodel import select

from src.db.database import get_session
from src.db.models import Server, Birthday, VoiceChannel
from src.modules.logs_setup import logger

load_dotenv(override=True)

t_key = os.getenv("timezonedb_key")

logger = logger.logging.getLogger("bot")


async def create_new_channel(interaction, new_channel):
    server_id = interaction.guild.id
    channel_id = new_channel.id
    server_name = interaction.guild.name
    channel_name = new_channel.name
    try:
        async with get_session() as session:
            new_settings = Server(server_id=server_id, birthday_channel_id=channel_id, birthday_channel_name=channel_name, server_name=server_name)
            session.add(new_settings)
            await session.commit()
            await session.refresh(new_settings)
        await interaction.response.send_message(f'Выбранный канал: {new_channel.mention}')
    except psycopg2.Error as error:
        await interaction.response.send_message(
            'Добавить канал не получилось из-за ошибки "{}"'.format(error.__str__()))


async def update_channel_values(interaction, new_channel):
    server_id = interaction.guild.id
    channel_id = new_channel.id
    channel_name = new_channel.name
    try:
        async with get_session() as session:
            server_settings = await session.exec(select(Server).where(Server.server_id == server_id))
            server_settings = server_settings.first()
            server_settings.birthday_channel_id = channel_id
            server_settings.birthday_channel_name = channel_name
            session.add(server_settings)
            await session.commit()
            await session.refresh(server_settings)
        await interaction.response.send_message(f'Выбранный канал: {new_channel.mention}')
    except Exception as error:
        await interaction.response.send_message(
            'Добавить канал не получилось из-за ошибки "{}"'.format(error.__str__()))


async def check_guild_id(interaction):
    server_id = interaction.guild.id
    try:
        async with get_session() as session:
            query = select(Server).where(Server.server_id == server_id)
            result = await session.exec(query)
            row = result.first()
        return row
    except psycopg2.Error as error:
        await interaction.response.send_message(
            'Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def update_server_role(interaction, server_id, role_id):
    try:
        async with get_session() as session:
            server_settings = await session.exec(select(Server).where(Server.server_id == server_id))
            server_settings = server_settings.first()
            server_settings.birthday_role_id = role_id
            await session.commit()
            await session.refresh(server_settings)
            role = await interaction.guild.fetch_role(role_id)
            role_name = role.name
            await interaction.response.send_message(f'Роль "{role_name}" добавлена, спасибо')
    except Exception as error:
        await interaction.response.send_message(
            'Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def add_new_day_month(user_id, day, month, interaction):
    try:
        async with get_session() as session:
            result = await session.exec(select(Birthday).where(Birthday.user_id == user_id))
            birthday = result.first()
            if birthday is None:
                # If for some reason it doesn't exist yet, create it
                birthday = Birthday(user_id=user_id, day=day, month=month)
                session.add(birthday)
            else:
                birthday.day = day
                birthday.month = month
                session.add(birthday)
            await session.commit()
            await session.refresh(birthday)
            status = 'ok'
            return status
    except Exception  as error:
        return error
        # await interaction.response.send_message(
        #     'Всё сломалось из-за ошибки "{}"'.format(error.__str__()))


async def delete_channel_id(channel_id, server_id):
    async with get_session() as session:
        selected_channel = await session.exec(select(VoiceChannel).where(VoiceChannel.channel_id == channel_id and VoiceChannel.server_id == server_id))
        selected_channel = selected_channel.first()
        if selected_channel is not None:
            session.delete(selected_channel)
            await session.commit()
            await session.refresh(selected_channel)
            return True
        else:
            return False

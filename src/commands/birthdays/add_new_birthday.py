import psycopg2
import discord
from sqlalchemy.orm import selectinload
from sqlmodel import select

from src.db.database import get_session
from src.db.models import User, Birthday, GlobalUser
from src.views.birthday.change_date import UserAlreadyExists
from src.views.birthday.timezones import DropdownTimezones


async def add_birthday(client, interaction, month, day):
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
    elif day > 31:
        await interaction.followup.send('Извини, такой даты не существует')
    else:
        user_id = interaction.user.id
        server_id = interaction.guild.id
        day = int(day)
        try:
            async with get_session() as session:
                # Load GlobalUser with their birthday
                query = select(GlobalUser).where(GlobalUser.discord_id == user_id).options(selectinload(GlobalUser.birthday))
                result = await session.exec(query)
                gu = result.first()

                # Ensure GlobalUser exists
                if gu is None:
                    gu = GlobalUser(discord_id=user_id, username=interaction.user.global_name)
                    session.add(gu)
                    await session.flush()

                # Ensure membership for this server exists
                membership_q = select(User).where(User.user_id == user_id, User.server_id == server_id)
                membership_res = await session.exec(membership_q)
                membership = membership_res.first()
                if membership is None:
                    membership = User(user_id=user_id, server_id=server_id, nickname=interaction.user.global_name, server_nickname=interaction.user.display_name, is_member=True)
                    session.add(membership)

                # Handle birthday
                if gu.birthday is None:
                    gu.birthday = Birthday(user_id=user_id, day=day, month=int(month.value), timezone=None)
                    session.add(gu)
                    await session.commit()
                    await added_birthday_send_reply(interaction, client, month, day)
                else:
                    day_record = gu.birthday.day
                    month_record = gu.birthday.month
                    timezone_record = gu.birthday.timezone
                    embed = discord.Embed(title='Тебя это устраивает?')
                    view = UserAlreadyExists(client=client)
                    view.user = interaction.user
                    message = await interaction.followup.send(
                        f'Твой др уже записан. День: {day_record}, месяц: {month_record}, часовой пояс: {timezone_record}',
                        embed=embed, view=view, ephemeral=True)
                    view.message = message
        except Exception as error:
            await interaction.followup.send(
                'Сервер ещё не настроен или что-то пошло не так. Напишите админу сервера или создателю бота')
            raise Exception(error)


async def added_birthday_send_reply(interaction, client, month, day):
    embed = discord.Embed(title='А теперь выбери часовой пояс')
    view = DropdownTimezones(day, month.name, client=client)
    view.user = interaction.user
    message = await interaction.followup.send(f'Всё записано, спасибо. День: {day}, месяц: {month.name}',
                                              embed=embed, view=view)
    view.message = message
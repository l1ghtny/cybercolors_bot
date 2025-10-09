import psycopg2
import discord
from sqlmodel import select

from src.db.database import get_session
from src.db.models import User
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
    else:
        user_id = f'{interaction.user.id}'
        server_id = f'{interaction.guild.id}'
        try:
            async with get_session() as session:
                query = select(User).where(User.user_id == user_id)
                result = await session.exec(query)
                user_data = result.first()
            if user_data is None:
                async with get_session() as session:
                    user = User(user_id=user_id, server_id=server_id, day=day, month=month.value)
                    session.add(user)
                    await session.commit()
                    await session.refresh(user)
                embed = discord.Embed(title='А теперь выбери часовой пояс')
                view = DropdownTimezones(day, month.name, client=client)
                view.user = interaction.user
                message = await interaction.followup.send(f'Всё записано, спасибо. День: {day}, месяц: {month.name}',
                                                          embed=embed, view=view)
                view.message = message
            else:
                day_record = user_data['day']
                month_record = user_data['month']
                timezone_record = user_data['timezone']
                embed = discord.Embed(title='Тебя это устраивает?')
                view = UserAlreadyExists(client=client)
                view.user = interaction.user
                message = await interaction.followup.send(
                    f'Твой др уже записан. День: {day_record}, месяц: {month_record}, часовой пояс: {timezone_record}',
                    embed=embed, view=view, ephemeral=True)
                view.message = message
        except:
            await interaction.done()
            await interaction.followup.send(
                'Сервер ещё не настроен или что-то пошло не так. Напишите админу сервера или создателю бота')

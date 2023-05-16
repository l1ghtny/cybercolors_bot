import psycopg2
import discord

from misc_files import basevariables
from views.birthday.change_date import UserAlreadyExists
from views.birthday.timezones import DropdownTimezones


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

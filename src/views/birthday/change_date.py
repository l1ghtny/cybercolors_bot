import calendar

import discord
import discord.ui

from src.misc_files import basevariables
from src.views.birthday.timezones import DropdownTimezones


class NewDayAgain(discord.ui.Modal):
    def __init__(self, month, client):
        super().__init__(
            timeout=None,
            title='Напиши день'
        )
        self.month = month
        self.client = client

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
            if self.month == '02' and day > 28:
                await interaction.response.send_message(
                    'Извини, в Феврале не бывает больше 28 дней (Я знаю, что бывает 29, но пока бот не умеет его корректно проверять)')
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
                    await interaction.response.defer(ephemeral=True)
                    month_num = int(self.month)
                    month = calendar.month_name[month_num]
                    view = DropdownTimezones(day, month, client=self.client)
                    view.user = interaction.user
                    message = await interaction.followup.send('А теперь выбери свой часовой пояс:', view=view, ephemeral=True)
                    view.message = message
                else:
                    interaction.channel.send('Извини, что-то пошло не так')
        else:
            await interaction.followup.send('Извини, это не число. Попробуй добавить день рождения командой '
                                                   '/add_my_birthday', ephemeral=True)


class NewMonthAgain(discord.ui.View):
    def __init__(self, user, client):
        super().__init__(timeout=None)
        select_menu = NewMonthAgainSelect(client)
        select_menu.user = user
        select_menu.info = self
        self.add_item(select_menu)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit_original_response(view=self)


class NewMonthAgainSelect(discord.ui.Select):
    def __init__(self, client):
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
        self.client = client

    async def callback(self, interaction: discord.Interaction):
        if interaction.user == self.user:
            result_list = self.values
            await NewMonthAgain.disable_all_items(self.info)
            modal = NewDayAgain(month=result_list[0], client=self.client)
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.send_message('Тебе нельзя', ephemeral=True)


class UserAlreadyExists(discord.ui.View):
    def __init__(self, client) -> None:
        super().__init__(timeout=None)
        self.client = client

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
            await interaction.followup.send('Ну вот и прекрасно', ephemeral=True)
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
            embed = discord.Embed(title='Твой день рождения удален. Что хочешь сделать дальше?')
            view = ChangeBirthday(client=self.client)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.message = interaction
            view.user = interaction.user
        else:
            await interaction.response.send_message(f'{interaction.user.mention}, это не твоя кнопка, уходи',
                                                    ephemeral=True)


class ChangeBirthday(discord.ui.View):
    def __init__(self, client) -> None:
        super().__init__(timeout=None)
        self.client = client

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        message = self.message
        await message.edit_original_response(view=self)

    @discord.ui.button(label='Пойти по своим делам', custom_id='not_add_birthday', style=discord.ButtonStyle.blurple,
                       emoji='\U0001F494')
    async def not_add_birthday(self, interaction, button):
        if interaction.user == self.user:
            await self.disable_all_items()
            await interaction.response.send_message(
                'Окей, тогда не добавляем новую дату. Если хочешь, всегда можешь воспользоваться командой '
                '/add_my_birthday', ephemeral=True)
        else:
            await interaction.response.send_message(f'{interaction.user.mention}, это не твоя кнопка, уходи',
                                                    ephemeral=True)

    @discord.ui.button(label='Добавить заново', custom_id='new_birthday', style=discord.ButtonStyle.green,
                       emoji='\U0001F382')
    async def add_new_birthday(self, interaction, button):
        if interaction.user == self.user:
            await self.disable_all_items()
            view = NewMonthAgain(user=interaction.user, client=self.client)
            await interaction.response.send_message('Тогда выбери месяц', view=view, ephemeral=True)
            view.message = interaction
        else:
            await interaction.response.send_message(f'{interaction.user.mention}, это не твоя кнопка, уходи',
                                                    ephemeral=True)


class NewDateAgain(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        select = NewDayAgain()
        self.add_item(select)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

import discord
import datetime
import discord.ui
from discord import app_commands
from discord.ui import Select
from discord.ext import tasks
import json
import os
from dotenv import load_dotenv
from os import path

load_dotenv()
# Grab the API token from the .env file.
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

#Commands sync
class aclient(discord.Client):
    def __init__(self):
        super().__init__(intents = discord.Intents.all())
        self.added = False
        self.synced = False #we use this so the bot doesn't sync commands more than once

    # commands local sync
    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:  # check if slash commands have been synced
            await tree.sync(guild=discord.Object(id=779677470156390440)) #zagloti guild
            await tree.sync()#global (global registration can take 1-24 hours)
            self.synced = True
        if not self.added:
            self.add_view(DropDownView())
            self.add_view(DropDownView2())
            self.add_view(DropDownViewChannels())
            self.add_view(DropdownTimezones())
            self.added = True
        print(f"We have logged in as {self.user}.")

#select for roles. Add roles here in case there are more

class Roles(discord.ui.Select):
    def __init__(self):
        option = [
            discord.SelectOption(label='Стример'),
            discord.SelectOption(label='One Piece'),
            discord.SelectOption(label='Borderlands'),
            discord.SelectOption(label='Left4Dead'),
            discord.SelectOption(label='barotrauma'),
            discord.SelectOption(label='dayz'),
            discord.SelectOption(label='Apex'),
            discord.SelectOption(label='Dead By Daylight')
        ]
        super().__init__(placeholder='Выбери роли, которые хочешь', min_values=1, max_values=8, options=option, custom_id='add_roles')

    async def callback(self, interaction: discord.Interaction):
        streamer_role = interaction.guild.get_role(1041330451597508650)
        one_piece = interaction.guild.get_role(1041330914258604063)
        borda = interaction.guild.get_role(1041331032835772456)
        l4d = interaction.guild.get_role(1048507173711388702)
        brma = interaction.guild.get_role(1057926892759547914)
        dayz = interaction.guild.get_role(1060666359391998032)
        apex = interaction.guild.get_role(1041332894314020935)
        dbd = interaction.guild.get_role(1041333052216979457)
        await interaction.response.defer()
        await interaction.followup.send(f'Ты выбрал роли {self.values}', ephemeral=True)
        if 'Стример' in self.values:
            if streamer_role in interaction.user.roles:
                await interaction.followup.send(f'{interaction.user.display_name}, у тебя уже есть {streamer_role.name}', ephemeral=True)
            else:
                await interaction.user.add_roles(streamer_role, atomic=True)
        if 'One Piece' in self.values:
            if one_piece in interaction.user.roles:
                await interaction.followup.send(f'{interaction.user.display_name}, у тебя уже есть {one_piece}', ephemeral=True)
            else:
                await interaction.user.add_roles(one_piece, atomic=True)
        if 'Borderlands' in self.values:
            if borda in interaction.user.roles:
                await interaction.followup.send(f'{interaction.user.display_name}, у тебя уже есть {borda}', ephemeral=True)
            else:
                await interaction.user.add_roles(borda, atomic=True)
        if 'Left4Dead' in self.values:
            if l4d in interaction.user.roles:
                await interaction.followup.send(f'{interaction.user.display_name}, у тебя уже есть {l4d}', ephemeral=True)
            else:
                await interaction.user.add_roles(l4d, atomic=True)
        if 'barotrauma' in self.values:
            if brma in interaction.user.roles:
                await interaction.followup.send(f'{interaction.user.display_name}, у тебя уже есть {brma}', ephemeral=True)
            else:
                await interaction.user.add_roles(brma, atomic=True)
        if 'dayz' in self.values:
            if dayz in interaction.user.roles:
                await interaction.followup.send(f'{interaction.user.display_name}, у тебя уже есть {dayz}', ephemeral=True)
            else:
                await interaction.user.add_roles(dayz, atomic=True)
        if 'Apex' in self.values:
            if apex in interaction.user.roles:
                await interaction.followup.send(f'{interaction.user.display_name}, у тебя уже есть {apex}', ephemeral=True)
            else:
                await interaction.user.add_roles(apex, atomic=True)
        if 'Dead By Daylight' in self.values:
            if dbd in interaction.user.roles:
                await interaction.followup.send(f'{interaction.user.display_name}, у тебя уже есть {dbd}', ephemeral=True)
            else:
                await interaction.user.add_roles(dbd, atomic=True)

#select for roles baded on new thing i found
class Roles2(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(custom_id='roles_new', placeholder='Выбери роли', min_values=1, max_values=5, disabled=False)
    async def callback(self, interaction: discord.Interaction):
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
        if forbidden == []:
            if already_assigned == []:
                await interaction.followup.send(f'Были добавлены роли:{new_roles}')
            if already_assigned != [] and new_roles != []:
                await interaction.followup.send(f'Были добавлены роли:{new_roles}, а эти роли у тебя уже есть:{already_assigned}')
            if already_assigned != [] and new_roles == []:
                await interaction.followup.send(f'У тебя уже есть {already_assigned}')
        if forbidden != []:
            if already_assigned == [] and new_roles != []:
                await interaction.followup.send(f'Были добавлены роли:{new_roles}. Роли {forbidden} тебе не доступны.')
            if already_assigned != [] and new_roles != []:
                await interaction.followup.send(f'Были добавлены роли:{new_roles}, а эти роли у тебя уже есть:{already_assigned}. Роли {forbidden} тебе не доступны.')
            if already_assigned != [] and new_roles == []:
                await interaction.followup.send(f'У тебя уже есть {already_assigned}. Роли {forbidden} тебе не доступны.')
            if already_assigned == [] and new_roles == []:
                await interaction.followup.send(f'Роли {forbidden} тебе не доступны')



class Channels(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(custom_id='channels_list', channel_types=[discord.ChannelType.private], placeholder='Фича пока находится разработке', min_values=1, max_values=5, disabled=False)
    async def callback(self, interaction: discord.Interaction):
        d_channels = self.values
        deleted_channels = []
        channel = discord.utils.get(interaction.guild.channels, name="запросы-от-lightny")
        print(channel.type)
        for items in d_channels:
            await discord.TextChannel.delete(items)
            deleted_channels.append(items.name)
        await interaction.response(f'Удалены следующие каналы: {deleted_channels}')

class Timezones(discord.ui.Select):
    def __init__(self):
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
        super().__init__(custom_id='timezones_choice', placeholder='Твой часовой пояс', options=options, max_values=1, disabled=False)
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




#LIST OF ALL VIEWS

class DropDownView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(Roles())

class DropDownView2(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(Roles2())

class DropDownViewChannels(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(Channels())

class DropdownTimezones(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(Timezones())


client = aclient()
tree = app_commands.CommandTree(client)
intents = discord.Intents.all()
intents.message_content = True

#say hello command
@tree.command(guild=discord.Object(id=779677470156390440), name='say_hello', description='testing_commands') #guild specific slash command
async def slash1(interaction: discord.Interaction):
    await interaction.response.send_message(f"Привет, {interaction.user.display_name}, я работаю! Меня сделал Антон на питоне", ephemeral = False)

#delete messages
@tree.command(guild=discord.Object(id=779677470156390440), name='delete_last_x_messages', description='для удаления последних сообщений') #guild specific slash command
async def slash2(interaction: discord.Interaction, number: int):
    channel = interaction.channel
    messages = [message async for message in channel.history(limit=number)]
    last_digit = int(repr(number)[-1])
    await interaction.response.defer(thinking=True, ephemeral=False)
    if number <= 0:
        await interaction.followup.send('Ты шо сдурел, я не могу удалить то, чего нет')
    else:
        if last_digit == 1:
            await interaction.followup.send(f"Хм, {interaction.user.display_name}, я удалил всего {number} сообщение!", ephemeral=False)
        if last_digit >= 5:
            await interaction.followup.send(f"Сделано, {interaction.user.display_name}, я удалил {number} сообщений!", ephemeral=False)
        if (last_digit != 1) and (last_digit < 5) and (last_digit != 0):
            await interaction.followup.send(f'Нихера себе, {interaction.user.display_name}, я удалил целых {number} сообщения!', ephemeral = False)
        if last_digit == 0:
            await interaction.followup.send(f'Ну охуеть, я удалил аж {number} сообщений!')
        await discord.TextChannel.delete_messages(self=channel, messages=messages)


#rename channel
@tree.command(guild = discord.Object(id=779677470156390440), name='rename_channel', description='переименовать канал, а вы что думали?')
async def slash3(interaction: discord.Interaction, name: str):
    await interaction.channel.edit(name = name)
    await interaction.response.send_message(f'Я переименовал этот канал в "{name}"', ephemeral= False)

#add roles
@tree.command(guild = discord.Object(id=779677470156390440), name='roles', description='Даёт возможность выбирать роли')
async def roles(interaction: discord.Interaction):
    embed = discord.Embed(title='Выбери нужные тебе роли!', colour=discord.Colour.dark_magenta())
    await interaction.channel.send(embed=embed, view=DropDownView())
    await interaction.response.send_message(f'{interaction.user.display_name}, ты запустил систему выбора ролей', ephemeral=True)


#add roles2
@tree.command(guild = discord.Object(id=779677470156390440), name='roles_natural', description='Даёт возможность выбирать роли')
async def roles2(interaction: discord.Interaction):
    embed = discord.Embed(title='Выбери нужные тебе роли!', colour=discord.Colour.dark_magenta())
    await interaction.channel.send(embed=embed, view=DropDownView2())
    await interaction.response.send_message(f'{interaction.user.display_name}, ты запустил новую систему выбора ролей. Она более красивая и вообще секс', ephemeral=True)

#delete_channels
@tree.command(guild = discord.Object(id=779677470156390440), name='delete_channels', description='Даёт возможность выбрать каналы для удаления')
async def delete_channels(interaction: discord.Interaction):
    embed = discord.Embed(title='Выбери нужные тебе каналы!', colour=discord.Colour.dark_magenta())
    await interaction.channel.send(embed=embed, view=DropDownViewChannels())
    await interaction.response.send_message(f'{interaction.user.display_name}, ты запустил систему удаления каналов', ephemeral=True)

#create_birthday
@tree.command(name='add_birthday', description='Добавь свой день рождения')
@app_commands.choices(
    month=[
        app_commands.Choice(name='Январь', value='january'),
        app_commands.Choice(name='Февраль', value='february'),
        app_commands.Choice(name='Март', value='march'),
        app_commands.Choice(name='Апрель', value='april'),
        app_commands.Choice(name='Май', value='may'),
        app_commands.Choice(name='Июнь', value='june'),
        app_commands.Choice(name='Июль', value='july'),
        app_commands.Choice(name='Август', value='august'),
        app_commands.Choice(name='Сентябрь', value='september'),
        app_commands.Choice(name='Октябрь', value='october'),
        app_commands.Choice(name='Ноябрь', value='november'),
        app_commands.Choice(name='Декабрь', value='december'),
    ]
)

async def birthday_command(interaction: discord.Interaction, day: int, month: app_commands.Choice[str]):
    user = interaction.user.id
    day = day
    absolute_path = os.path.dirname(__file__)
    month_value = month.value
    interaction_guild = f'{interaction.guild.id}'
    dictionary = {
        'user_id': user,
        'day': day,
        'month': month_value,
        'timezone': ''
    }
    embed = discord.Embed(title=f'{interaction.user.display_name}, а теперь выбери свой часовой пояс', colour=discord.Colour.dark_gold())
    await interaction.response.defer()
    table_name = 'bd_table.json'
    filename = f'{os.path.join(absolute_path, table_name)}'
    anton_id = client.get_user(267745993074671616)
    list_bdays = [dictionary]
    if path.isfile(filename) is False:
        await interaction.followup.send(f'Файл не найден, напишите {anton_id.mention}')
    else:
        try:
            with open(filename, 'r+') as file:
                current_data = json.load(file)
                if any(d == interaction_guild for d in current_data):
                    server = current_data[interaction_guild]
                    if not any(d['user_id'] == user for d in server):
                        if server is None:
                            json.dump({interaction_guild: list_bdays}, file, indent=4)
                            await interaction.followup.send(f'{interaction.user.display_name}, твой день рождения добавлен. День: {day}, месяц: {month.name}')
                            await interaction.followup.send(embed=embed, view=DropdownTimezones(), ephemeral=True)
                        else:
                            server.append(dictionary)
                            print(current_data)
                            print(server)
                            file.seek(0)
                            json.dump(current_data, file, indent=4)
                            await interaction.followup.send(f'{interaction.user.display_name}, твой день рождения добавлен. День: {day}, месяц: {month.name}')
                            await interaction.followup.send(embed=embed, view=DropdownTimezones(), ephemeral=True)
                    else:
                        await interaction.followup.send(f'{interaction.user.display_name}, твой день рождения уже записан. Если ты хочешь его изменить, обратись к {anton_id.mention}, так как функция удаления своего дня рождения пока не доступна')
                else:
                    new_server = {interaction_guild: list_bdays}
                    current_data.update(new_server)
                    file.seek(0)
                    json.dump(current_data, file, indent=4)
                    await interaction.followup.send(f'{interaction.user.display_name}, твой день рождения добавлен. День: {day}, месяц: {month.name}')
                    await interaction.followup.send(embed=embed, view=DropdownTimezones(), ephemeral=True)

        except:
            with open(filename, 'w') as file:
                json.dump({interaction_guild: list_bdays}, file, indent=4)
            await interaction.followup.send(f'{interaction.user.display_name}, твой день рождения добавлен. День: {day}, месяц: {month.name}')
            await interaction.followup.send(embed=embed, view=DropdownTimezones(), ephemeral=True)

#NEW CODE FOR REPLIES
@client.event
async def on_message(message):
    user = message.author
    if message.author == client.user:
        return
    message_content = message.content.lower()
    if message_content.startswith('lol'):
        await message.channel.send('lul')
    if message_content.startswith("йопта"): #bot trigger
       await message.channel.send("сам ты йопта") #what you want to send
    if message_content.startswith('здарова'):
       await message.channel.send(f'ну здарова, {user.mention}')
    if message_content.startswith('hello'):
        await message.channel.send(f'Always good to see you, master {user.mention}')
    if message_content.startswith("сука"): #bot trigger
       await message.channel.send("сука! смешное слово, го повторять его") #what you want to send
    if message_content.startswith("бот пошёл нахуй") or message_content.startswith('бот пошел нахуй'): #bot trigger
       await message.channel.send("я тут стараюсь, значит, нагружаю Антону комп, а ты меня нахуй посылаешь. Сам пшёл)") #what you want to send
    if message_content.startswith("пёс"): #bot trigger
       await message.channel.send("Пёс? Успокойтесь, здесь нет никаких собак(с)")
    if message_content.startswith('пошёл нахуй') or message_content.startswith('пошел нахуй'):
       await message.channel.send(f'{user.display_name}, сам иди')
    if message_content.startswith('бот молодец') or message_content.startswith('бот спасибо') or message_content.startswith('бот ты хороший'):
       await message.channel.send(f'{user.display_name}, спасибо, стараемся')
    if message_content.startswith('пидр') or message_content.startswith('пидорас') or message_content.startswith('вот пидр') or message_content.startswith('вот пидорас'):
        await message.delete()
        await message.channel.send(f'{user.display_name}, фу-фу-фу, асуждаем')
    if message_content.startswith('заглоты'):
        await message.channel.send('САМЫЕ КРУТЫЕ В МИРЕ')
    if message_content.startswith('мразь'):
        await message.channel.send('мразотное слово, как по мне')
    if message_content.startswith('жопа'):
        await message.channel.send('серьёзное заявление')
    if message_content.startswith('скотина'):
        await message.channel.send('скотина вообще-то полезна в хозяйстве')
    if message_content.startswith('уёбок') or message_content.startswith('уебок'):
        await message.channel.send('тебе уебать?')
    if message_content.startswith('мудак'):
        await message.channel.send('как по мне, "мудозвон" веселее звучит')
    if message_content.startswith('робин гуд'):
        await message.channel.send('спешит на помощь')
    if message_content.startswith('кто тут'):
        await message.channel.send('я тут')
    if message_content.startswith('где'):
        await message.channel.send('здесь')
    if message_content.startswith('куда'):
        await message.channel.send('мде')
    if message_content.startswith('вот уж МДЕ'):
        await message.channel.send('тудой')
    if message_content.startswith('бот смешной'):
        await message.channel.send('да я чисто мистер Бин, только разговаривать умею')
    if message_content.startswith('всратый муд'):
        await message.channel.send('попробуй представить свой муд в одежде своей бабушки')
    if message_content.startswith('бот пожалуйста'):
        await message.channel.send('ты уже совсем поехал? Какое я тебе пожалуйста?')
    if message_content.startswith('падла'):
        await message.channel.send('синонимы: профура, девка, хипесница, шмара, погань, блядюга, курва, шалава, лярва, сволота, падло, блядь, лахудра, стервоза, блядища, поблядушка, гулящая, шлюшка, падаль, потаскуха, блядушка, сволочье, потаскунья, стерва, проститутка, шлюха, подстилка, мара, потаскушка')

#BD MODULE with checking task







# EXECUTES THE BOT WITH THE SPECIFIED TOKEN.
client.run(DISCORD_TOKEN)


import asyncio

import discord
import discord.ui
from discord import app_commands
from discord.ext import tasks
import os
from dotenv import load_dotenv
import demoji
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.commands.misc.cats import cat_command, cat_command_text
from src.commands.moderation.security import (
    security_capture_permissions,
    security_lockdown,
    security_set_verified_role,
    verify_member,
)
from src.commands.moderation.rules import (
    rule_add,
    rules_import_message,
    rules_import_messages,
    rules_import_from_message_ctx,
    rules_list,
    rules_parse_guide,
)
from src.commands.moderation.warn import warn
from src.commands.moderation.mute import (
    moderation_settings,
    moderation_set_mute_role,
    moderation_set_language,
    moderation_set_log_channel,
    moderation_clear_log_channel,
    moderation_create_mute_role,
    moderation_set_mute_defaults,
    mute,
    unmute,
)
from src.db.database import engine, get_async_session
from src.modules.moderation.moderation_helpers import (
    check_if_server_exists,
    check_if_user_exists,
    claim_message_for_processing,
    handle_bulk_message_deletion,
    handle_message_deletion,
)
from src.db.models import Server, Replies, Triggers, GlobalUser, ModerationRule
from src.modules.birthdays_module.user_validation.user_validate_time import users_time
from src.commands.birthdays.add_new_birthday import add_birthday
from src.commands.birthdays.show_birthday_list import send_birthday_list
from src.modules.birthdays_module.hourly_check.check_birthday_redone import check_birthday_new
from src.modules.birthdays_module.hourly_check.check_roles import check_roles
from src.modules.birthdays_module.hourly_check.check_time import check_time
from src.modules.birthdays_module.user_validation.validation_main import main_validation_process
from src.modules.guild_lifecycle import mark_guild_presence, sync_active_guild_presence
from src.modules.logs_setup import logger
from src.modules.on_message_processing.background_message_processing import process_background_tasks
from src.modules.on_message_processing.check_for_links import delete_server_links
from src.modules.on_message_processing.gpt_bot_reply import look_for_bot_reply
from src.modules.on_message_processing.replies import check_for_replies
from src.modules.on_voice_state_processing.create_voice_channel import create_voice_channel
from src.modules.moderation.mute_worker import process_expired_mutes
from src.views.replies.delete_multiple_replies import DeleteReplyMultiple, DeleteReplyMultipleSelect
from src.views.replies.delete_one_reply import DeleteOneReply
from src.views.pagination.pagination import PaginationView
from src.views.birthday.settings import BirthdaysButtonsSelect, GuildAlreadyExists

load_dotenv()
# Grab the API token from the .env file.
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_TOKEN_TEST = os.getenv('DISCORD_TOKEN_TEST')
TEST_GUILD_ID = os.getenv('TEST_GUILD_ID')

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

        self.known_global_users = set()
        self.current_server_rules: dict[int, list[dict]] = {}
        self.guild_presence_synced = False

    async def setup_hook(self):
        """
        This method is called automatically by discord.py once the client
        is logged in, but BEFORE it connects to the WebSocket.
        It is the safe place for async DB calls.
        """
        # 2. Call your cache loader
        await self.load_user_cache()
        await self.load_current_server_rules()

    async def load_user_cache(self):
        """
        Fetch existing user IDs from Postgres and store in memory.
        """
        logger.info("⏳ Pre-loading global users from database...")
        try:
            # Adjust these imports based on your actual file structure
            # from the database import engine, GlobalUser

            async with AsyncSession(engine) as session:
                # Select only the ID column for efficiency
                statement = select(GlobalUser.discord_id)
                result = await session.exec(statement)
                user_ids = result.all()

                # Convert to a set for O(1) lookups
                self.known_global_users = set(user_ids)

            logger.info(f"✅ Cache warm! Loaded {len(self.known_global_users)} users.")

        except Exception as e:
            logger.error(f"❌ Failed to load user cache: {e}")

    async def load_current_server_rules(self):
        """
        Fetch active moderation rules per server and keep them in-memory.
        """
        logger.info("Pre-loading active moderation rules from database...")
        try:
            async with get_async_session() as session:
                statement = (
                    select(ModerationRule)
                    .where(ModerationRule.is_active == True)
                    .order_by(ModerationRule.server_id.asc(), ModerationRule.sort_order.asc())
                )
                result = await session.exec(statement)
                rules = result.all()

            rules_map: dict[int, list[dict]] = {}
            for rule in rules:
                rules_map.setdefault(rule.server_id, []).append(
                    {
                        "id": str(rule.id),
                        "code": rule.code,
                        "title": rule.title,
                        "description": rule.description,
                        "sort_order": rule.sort_order,
                    }
                )
            self.current_server_rules = rules_map
            logger.info(f"Loaded moderation rules for {len(self.current_server_rules)} servers.")
        except Exception as e:
            logger.error(f"Failed to load moderation rules cache: {e}")



    # commands local sync
    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:  # check if slash commands have been synced
            if TEST_GUILD_ID:
                guild = discord.Object(id=int(TEST_GUILD_ID))
                tree.copy_global_to(guild=guild)
                await tree.sync(guild=guild)
                print(f"Commands synced to guild {TEST_GUILD_ID}.")
            else:
                await tree.sync()  # global (can take 1-24 hours)
                print("Commands synced globally.")
            self.synced = True
        if not self.added:
            self.added = True
        if not birthday.is_running():
            birthday.start()
        if not check_users_with_birthdays.is_running():
            check_users_with_birthdays.start()
        if not auto_unmute_worker.is_running():
            auto_unmute_worker.start()
        if not self.guild_presence_synced:
            await sync_active_guild_presence(self.guilds)
            self.guild_presence_synced = True
        logger.info(f"We have logged in as {self.user}.")


client = Aclient()
tree = app_commands.CommandTree(client)

moderation_group = app_commands.Group(
    name="moderation",
    description="Moderation commands",
)
moderation_rules_group = app_commands.Group(
    name="rules",
    description="Moderation rule management",
    parent=moderation_group,
)
moderation_security_group = app_commands.Group(
    name="security",
    description="Server security moderation commands",
    parent=moderation_group,
)
moderation_settings_group = app_commands.Group(
    name="settings",
    description="Moderation settings",
    parent=moderation_group,
)

moderation_group.add_command(warn)
moderation_group.add_command(mute)
moderation_group.add_command(unmute)

moderation_rules_group.add_command(rule_add)
moderation_rules_group.add_command(rules_import_message)
moderation_rules_group.add_command(rules_import_messages)
moderation_rules_group.add_command(rules_list)
moderation_rules_group.add_command(rules_parse_guide)

moderation_security_group.add_command(security_set_verified_role)
moderation_security_group.add_command(security_capture_permissions)
moderation_security_group.add_command(security_lockdown)
moderation_security_group.add_command(verify_member)

moderation_settings_group.add_command(moderation_settings)
moderation_settings_group.add_command(moderation_set_language)
moderation_settings_group.add_command(moderation_set_mute_role)
moderation_settings_group.add_command(moderation_set_log_channel)
moderation_settings_group.add_command(moderation_clear_log_channel)
moderation_settings_group.add_command(moderation_create_mute_role)
moderation_settings_group.add_command(moderation_set_mute_defaults)

tree.add_command(moderation_group)
tree.add_command(rules_import_from_message_ctx)


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
        async with get_async_session() as session:
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
            string = string.replace(i, unicode)
        return string

    def e_replace(string):
        return string.replace('ё', 'е')

    await interaction.response.defer(ephemeral=True)
    server_id = interaction.guild_id
    user_id = interaction.user.id
    
    # Normalize the trigger phrase
    trigger_text = em_replace(e_replace(phrase.lower().strip()))
    
    try:
        async with get_async_session() as session:
            await check_if_server_exists(interaction.guild, session)
            await check_if_user_exists(interaction.user, interaction.guild, session)

            new_reply = Replies(
                bot_reply=response,
                server_id=server_id,
                created_by_id=user_id
            )
            session.add(new_reply)
            await session.flush() # Get the new_reply.id
            
            new_trigger = Triggers(
                message=trigger_text,
                reply_id=new_reply.id
            )
            session.add(new_trigger)
            
            await session.commit()
            await interaction.followup.send(f'Фраза "{phrase}" с ответом "{response}" записаны', ephemeral=True)
    except Exception as error:
        logger.error(f"Error adding reply: {error}")
        await interaction.followup.send(f'Не получилось записать словосочетание из-за ошибки: {error}', ephemeral=True)


@tree.command(name='delete_reply', description='Позволяет удалить заведенные триггеры на фразы')
async def delete_reply(interaction: discord.Interaction, trigger: str):
    search_pattern = f'%{trigger}%'
    server_id = interaction.guild_id
    
    async with get_async_session() as session:
        statement = select(Triggers).join(Replies).where(
            Replies.server_id == server_id,
            Triggers.message.like(search_pattern)
        )
        result = await session.exec(statement)
        triggers = result.all()
        results_count = len(triggers)

    if results_count == 0:
        await interaction.response.send_message("Триггеры не найдены.", ephemeral=True)
        return

    if results_count > 1:
        view = DeleteReplyMultiple(interaction)
        select_module = DeleteReplyMultipleSelect(interaction, view)
        for t in triggers:
            async with get_async_session() as session:
                reply = await session.get(Replies, t.reply_id)
            
            label = f"Т: {t.message[:40]} -> О: {reply.bot_reply[:40]}"
            select_module.add_option(label=label, value=str(t.id))
        
        view.add_item(select_module)
        await interaction.response.send_message(f'Найдено {results_count} совпадений. Выберите для удаления:',
                                                view=view, ephemeral=True)
    else:
        target_trigger = triggers[0]
        async with get_async_session() as session:
            reply = await session.get(Replies, target_trigger.reply_id)
            creator = await session.get(GlobalUser, reply.created_by_id)
            creator_name = creator.username if creator else "Unknown"
            
            embed = discord.Embed(title='Удаление триггера', colour=discord.Colour.red())
            embed.add_field(name='Триггер:', value=target_trigger.message)
            embed.add_field(name='Ответ:', value=reply.bot_reply, inline=False)
            embed.add_field(name='Кто добавил:', value=creator_name)
            
            view = DeleteOneReply(interaction, interaction.user, target_trigger.id, True)
            await interaction.response.send_message(view=view, embed=embed, ephemeral=True)


@delete_reply.autocomplete('trigger')
async def delete_reply_autocomplete(interaction: discord.Interaction, current: str):
    server_id = interaction.guild_id
    request_string = f'%{current}%'
    async with get_async_session() as session:
        query = select(Triggers).join(Replies).where(
            Triggers.message.like(request_string), 
            Replies.server_id == server_id
        )
        result_get = await session.exec(query)
        result = result_get.all()
    
    result_list = []
    for item in result:
        new_value = item.message
        if len(new_value) > 100:
            new_value = new_value[:96] + '...'
        result_list.append(app_commands.Choice(name=new_value, value=new_value))
    return result_list


@tree.command(name='check_dr', description='Форсированно запускает проверку на дни рождения, если сегодня кому-то не выдали роль')
async def birthday_check(interaction: discord.Interaction):
    await interaction.response.defer()
    await check_birthday_new(client)
    await check_roles(client)
    await interaction.followup.send('OK')


# TODO: Needs to be implemented with UI
# @tree.command(name='add_birthday_message',
#               description='Добавляет сообщение, которое бот использует, чтобы поздравлять именинников')
# async def birthday_message(interaction: discord.Interaction, message: str):



@tree.command(name='birthday_list', description='Показывает все дни рождения на сервере')
async def birthday_list(interaction: discord.Interaction):
    await send_birthday_list(client, interaction, 15)


@tree.command(name='show_replies', description='Вызывает список всех вопросов-ответов на сервере')
async def show_replies(interaction: discord.Interaction):
    await interaction.response.defer()
    server_id = interaction.guild_id
    data = []
    
    async with get_async_session() as session:
        statement = select(Triggers, Replies).join(Replies).where(Replies.server_id == server_id).order_by(Triggers.message)
        result = await session.exec(statement)
        rows = result.all()
        
        for trigger, reply in rows:
            data.append({
                'label': f'Триггер: {trigger.message}',
                'value': f'Ответ: {reply.bot_reply}'
            })

    title = 'Триггеры на сервере'
    footer = 'Всего триггеров'
    maximum = 'триггеров'
    pagination_view = PaginationView(data, interaction.user, title, footer, maximum, separator=8)
    
    if not data:
        await interaction.followup.send("На этом сервере пока нет настроенных ответов.")
        return

    try:
        await pagination_view.send(interaction)
    except Exception as error:
        logger.error(f"Pagination error: {error}")
        await interaction.followup.send(f'Ошибка при выводе списка: {error}')


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
    server = message.guild
    if not user or not server:
        return
    if user == client.user:
        return

    try:
        claimed = await claim_message_for_processing(message)
    except Exception as error:
        logger.warning("Failed to claim message %s for processing: %s", message.id, error)
        claimed = True
    if not claimed:
        return

    message_content_base = message.content.lower()
    link_deleted = await delete_server_links(message, message_content_base)
    if link_deleted is True:
        return
    database_found, server_id = await check_for_replies(message)
    if database_found is False:
        await look_for_bot_reply(message, client)
    asyncio.create_task(process_background_tasks(message, client.known_global_users))


@client.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    """Triggered when a message is deleted. Moves it to deleted_messages table."""
    async with AsyncSession(engine) as session:
        await handle_message_deletion(payload.message_id, payload.guild_id, session)


@client.event
async def on_raw_bulk_message_delete(payload: discord.RawBulkMessageDeleteEvent):
    """Triggered when multiple messages are deleted in bulk."""
    async with AsyncSession(engine) as session:
        await handle_bulk_message_deletion(payload.message_ids, payload.guild_id, session)


# BD MODULE with checking task
@tasks.loop(time=check_time)
async def birthday():
    await check_birthday_new(client)
    await check_roles(client)


@tasks.loop(time=users_time)
async def check_users_with_birthdays():
    logger.info('validation process started')
    await main_validation_process(client)


@tasks.loop(seconds=60)
async def auto_unmute_worker():
    processed, failed = await process_expired_mutes(client)
    if processed or failed:
        logger.info("Auto-unmute run finished. processed=%s failed=%s", processed, failed)


@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    await create_voice_channel(member, before, after)


@client.event
async def on_guild_join(guild: discord.Guild):
    await mark_guild_presence(guild, is_active=True)


@client.event
async def on_guild_remove(guild: discord.Guild):
    await mark_guild_presence(guild, is_active=False)


# def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
#     logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
#     # Optionally, you can re-raise the exception or perform other actions

# sys.excepthook = handle_uncaught_exception


# EXECUTES THE BOT WITH THE SPECIFIED TOKEN.
client.run(DISCORD_TOKEN_TEST, root_logger=True)

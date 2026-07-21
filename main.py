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
from src.commands.app_command_errors import handle_app_command_error
from src.commands.temp_voice import temp_voice_limit, temp_voice_rename
from src.commands.moderation.security import (
    security_create_newcomer_role,
    security_newcomer_role_suggestion,
    security_capture_permissions,
    security_lockdown,
    security_set_newcomer_role,
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
from src.commands.moderation.message_actions import (
    link_message_to_action_ctx,
    start_action_from_message_ctx,
)
from src.commands.moderation.bot_messages import (
    StaticCommandTranslator,
    reply_as_bot_ctx,
    reply_as_cybercolors_ctx,
)
from src.commands.sync import sync_application_commands
from src.commands.moderation.actions import (
    action_revert,
    actions_list,
    ban,
    kick,
    register_moderation_action_components,
    unban,
)
from src.commands.moderation.cases import (
    case_add_rule,
    case_add_user,
    case_archive,
    case_close,
    case_create,
    case_evidence,
    case_link_action,
    case_note,
    case_remove_rule,
    case_remove_user,
    case_reopen,
    case_show,
    case_unlink_action,
    cases_list,
)
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
from src.db.models import Server, Replies, Triggers, GlobalUser, ModerationRule, ServerSecuritySettings
from src.modules.birthdays_module.user_validation.user_validate_time import users_time
from src.commands.birthdays.add_new_birthday import add_birthday, change_birthday
from src.commands.birthdays.show_birthday_list import send_birthday_list
from src.modules.birthdays_module.hourly_check.check_birthday_redone import check_birthday_new
from src.modules.birthdays_module.hourly_check.check_roles import check_roles
from src.modules.birthdays_module.hourly_check.check_time import check_time
from src.modules.birthdays_module.user_validation.flag_users_who_left import flag_user
from src.modules.birthdays_module.user_validation.validation_main import main_validation_process
from src.modules.guild_lifecycle import mark_guild_presence, sync_active_guild_presence
from src.modules.logs_setup import logger
from src.modules.on_message_processing.background_message_processing import process_background_tasks
from src.modules.ai.moderation_review import register_ai_moderation_review_views
from src.modules.on_message_processing.check_for_links import delete_server_links
from src.modules.on_message_processing.gpt_bot_reply import look_for_bot_reply
from src.modules.on_message_processing.replies import check_for_replies
from src.modules.on_message_processing.message_ingestion import (
    enqueue_message_ingestion,
    start_message_ingestion_workers,
)
from src.modules.on_voice_state_processing.create_voice_channel import create_voice_channel
from src.modules.moderation.ban_worker import process_expired_bans
from src.modules.moderation.mute_worker import process_expired_mutes
from src.modules.moderation.newcomer_restrictions import handle_newcomer_role_granted
from src.modules.monitoring.activity import (
    handle_member_join_monitoring,
    record_bot_command_activity,
    record_thread_create_activity,
    record_voice_join_activity,
)
from api.services.moderation_rules_service import sync_rules_from_source_message_edit
from src.views.replies.delete_multiple_replies import DeleteReplyMultiple, DeleteReplyMultipleSelect
from src.views.replies.delete_one_reply import DeleteOneReply
from src.views.pagination.pagination import PaginationView
from src.views.birthday.settings import BirthdaysButtonsSelect, GuildAlreadyExists

load_dotenv()
# Grab the API token from the .env file.
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN_TEST") or os.getenv("DISCORD_TOKEN")
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
        self.security_pause_cache: dict[int, tuple[bool, float]] = {}

    async def setup_hook(self):
        """
        This method is called automatically by discord.py once the client
        is logged in, but BEFORE it connects to the WebSocket.
        It is the safe place for async DB calls.
        """
        # 2. Call your cache loader
        await self.load_user_cache()
        await self.load_current_server_rules()
        register_moderation_action_components(self)
        await register_ai_moderation_review_views(self)
        start_message_ingestion_workers()

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



    async def public_responses_paused(self, server_id: int) -> bool:
        now = asyncio.get_running_loop().time()
        cached = self.security_pause_cache.get(server_id)
        if cached is not None and cached[1] > now:
            return cached[0]
        async with get_async_session() as session:
            settings = await session.get(ServerSecuritySettings, server_id)
        paused = bool(settings and settings.public_bot_responses_paused)
        self.security_pause_cache[server_id] = (paused, now + 5.0)
        return paused

    # commands local sync
    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:  # check if slash commands have been synced
            await tree.set_translator(StaticCommandTranslator())
            synced = await sync_application_commands(
                tree,
                test_guild_id=TEST_GUILD_ID,
                test_guild_commands=(reply_as_cybercolors_ctx,),
            )
            print(f"Commands synced globally ({synced.global_count}).")
            if synced.guild_id is not None:
                print(
                    f"Guild-specific command overrides synced for guild {synced.guild_id} "
                    f"({synced.guild_count} total)."
                )
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
class CyberColorsCommandTree(app_commands.CommandTree):
    async def on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await handle_app_command_error(interaction, error, logger=logger)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None or not isinstance(interaction.user, discord.Member):
            return True
        command_name = interaction.command.qualified_name if interaction.command else ""
        if command_name == "mod" or command_name.startswith("mod "):
            return True
        if interaction.user.guild_permissions.manage_guild:
            return True

        async with get_async_session() as session:
            settings = await session.get(ServerSecuritySettings, interaction.guild_id)
        if (
            settings is None
            or not settings.newcomer_restriction_enabled
            or not settings.newcomer_block_bot_commands
            or settings.newcomer_role_id is None
        ):
            return True
        if settings.newcomer_role_id not in {role.id for role in interaction.user.roles}:
            return True

        message = (
            "Команды бота недоступны, пока действует ограничение для новичков. "
            "Обратитесь к модератору, если это ошибка.\n"
            "Bot commands are unavailable while the newcomer restriction is active."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False


tree = CyberColorsCommandTree(client)

moderation_group = app_commands.Group(
    name="mod",
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
moderation_cases_group = app_commands.Group(
    name="cases",
    description="Moderation case management",
    parent=moderation_group,
)
moderation_actions_group = app_commands.Group(
    name="actions",
    description="Moderation action management",
    parent=moderation_group,
)

temp_voice_group = app_commands.Group(
    name="tempvoice",
    description="Temporary voice channel controls",
)
moderation_group.add_command(warn)
moderation_group.add_command(mute)
moderation_group.add_command(unmute)
moderation_group.add_command(kick)
moderation_group.add_command(ban)
moderation_group.add_command(unban)

moderation_rules_group.add_command(rule_add)
moderation_rules_group.add_command(rules_import_message)
moderation_rules_group.add_command(rules_import_messages)
moderation_rules_group.add_command(rules_list)
moderation_rules_group.add_command(rules_parse_guide)

moderation_security_group.add_command(security_set_verified_role)
moderation_security_group.add_command(security_newcomer_role_suggestion)
moderation_security_group.add_command(security_set_newcomer_role)
moderation_security_group.add_command(security_create_newcomer_role)
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

moderation_cases_group.add_command(case_create)
moderation_cases_group.add_command(cases_list)
moderation_cases_group.add_command(case_show)
moderation_cases_group.add_command(case_close)
moderation_cases_group.add_command(case_reopen)
moderation_cases_group.add_command(case_archive)
moderation_cases_group.add_command(case_note)
moderation_cases_group.add_command(case_evidence)
moderation_cases_group.add_command(case_add_user)
moderation_cases_group.add_command(case_remove_user)
moderation_cases_group.add_command(case_add_rule)
moderation_cases_group.add_command(case_remove_rule)
moderation_cases_group.add_command(case_link_action)
moderation_cases_group.add_command(case_unlink_action)

moderation_actions_group.add_command(actions_list)
moderation_actions_group.add_command(action_revert)

temp_voice_group.add_command(temp_voice_rename)
temp_voice_group.add_command(temp_voice_limit)

tree.add_command(moderation_group)
tree.add_command(temp_voice_group)
tree.add_command(rules_import_from_message_ctx)
tree.add_command(link_message_to_action_ctx)
tree.add_command(start_action_from_message_ctx)
tree.add_command(reply_as_bot_ctx)


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

@tree.command(name='change_birthday', description='Измени свой день рождения')
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
async def change_birthday_command(interaction: discord.Interaction, day: int, month: app_commands.Choice[str]):
    await change_birthday(client, interaction, month, day)


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


@tree.command(name='add_reply', description='Add a custom bot reply trigger.')
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


@tree.command(name='check_dr', description='Force birthday role check.')
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
    await interaction.response.defer(ephemeral=True)
    try:
        logger.info('validation process started (forced)')
        await main_validation_process(client)
    except Exception as error:
        logger.exception("Forced validation failed: %s", error)
        await interaction.followup.send(f'Ошибка при валидации: {error}', ephemeral=True)
        return
    await interaction.followup.send('команда выполнена', ephemeral=True)


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

    enqueue_message_ingestion(message)
    message_content_base = message.content.lower()
    link_deleted = await delete_server_links(message, message_content_base)
    if link_deleted is True:
        return
    if not await client.public_responses_paused(server.id):
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


@client.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
    if payload.guild_id is None or payload.channel_id is None:
        return
    content = payload.data.get("content")
    if not isinstance(content, str):
        return
    async with AsyncSession(engine) as session:
        try:
            updated = await sync_rules_from_source_message_edit(
                session=session,
                server_id=int(payload.guild_id),
                channel_id=int(payload.channel_id),
                message_id=int(payload.message_id),
                content=content,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Failed to sync rules from edited message %s", payload.message_id)
            return
    if updated and hasattr(client, "load_current_server_rules"):
        await client.load_current_server_rules()


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
    ban_processed, ban_failed = await process_expired_bans(client)
    if processed or failed:
        logger.info("Auto-unmute run finished. processed=%s failed=%s", processed, failed)
    if ban_processed or ban_failed:
        logger.info("Auto-unban run finished. processed=%s failed=%s", ban_processed, ban_failed)


@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    await create_voice_channel(member, before, after)
    if before.channel != after.channel and after.channel is not None:
        asyncio.create_task(record_voice_join_activity(member, after))


@client.event
async def on_thread_create(thread: discord.Thread):
    asyncio.create_task(record_thread_create_activity(thread))


@client.event
async def on_interaction(interaction: discord.Interaction):
    asyncio.create_task(record_bot_command_activity(interaction))


@client.event
async def on_guild_join(guild: discord.Guild):
    await mark_guild_presence(guild, is_active=True)


@client.event
async def on_member_join(member: discord.Member):
    async with get_async_session() as session:
        await check_if_server_exists(member.guild, session)
        await check_if_user_exists(member, member.guild, session)
        await session.commit()
    await handle_member_join_monitoring(member)


@client.event
async def on_member_update(before: discord.Member, after: discord.Member):
    await handle_newcomer_role_granted(before, after)


@client.event
async def on_member_remove(member: discord.Member):
    await flag_user(member.id, member.guild.id)


@client.event
async def on_guild_remove(guild: discord.Guild):
    await mark_guild_presence(guild, is_active=False)


# def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
#     logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
#     # Optionally, you can re-raise the exception or perform other actions

# sys.excepthook = handle_uncaught_exception


# EXECUTES THE BOT WITH THE SPECIFIED TOKEN.
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN, DISCORD_TOKEN_TEST, or DISCORD_TOKEN must be set")

client.run(DISCORD_TOKEN, root_logger=True)

import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from api.services.moderation_action_numbers import resolve_moderation_action_reference
from api.services.moderation_actions_service import (
    _dashboard_action_url,
    link_message_to_action,
)
from src.db.database import get_async_session
from src.db.models import ActionType, ServerModerationSettings
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.bot_rbac import ensure_bot_permission, has_bot_permission
from src.modules.moderation.bot_services import (
    build_moderator_action_receipt,
    create_bot_moderation_action,
    fetch_active_rule_models,
    find_rule,
    rule_label,
    validate_target_for_moderation,
)
from src.modules.moderation.durations import parse_duration_text
from src.modules.moderation.moderation_helpers import (
    check_if_server_exists,
    check_if_user_exists,
    log_message,
)
from src.modules.moderation.public_notices import send_public_action_notice


REPLY_LINK_PATTERN = re.compile(r"^!link_action\s+(?P<reference>#?[0-9a-fA-F-]+)\s*$", re.IGNORECASE)
ACTION_PERMISSION_KEYS = {
    ActionType.WARN: "moderation.actions.apply.warn",
    ActionType.MUTE: "moderation.actions.apply.mute",
    ActionType.KICK: "moderation.actions.apply.kick",
    ActionType.BAN: "moderation.actions.apply.ban",
}


def _has_discord_permission(member: discord.Member, action_type: ActionType) -> bool:
    permissions = member.guild_permissions
    if permissions.administrator:
        return True
    if action_type == ActionType.KICK:
        return permissions.kick_members
    if action_type == ActionType.BAN:
        return permissions.ban_members
    return permissions.moderate_members


async def _archive_source_message(
    session,
    *,
    source_message: discord.Message,
    moderator: discord.Member | discord.User,
) -> None:
    if source_message.guild is None:
        raise ValueError("Message must belong to a server")
    await check_if_server_exists(source_message.guild, session)
    await check_if_user_exists(source_message.author, source_message.guild, session)
    await check_if_user_exists(moderator, source_message.guild, session)
    await log_message(source_message, session)


class LinkMessageToActionModal(discord.ui.Modal):
    def __init__(self, *, source_message: discord.Message, locale: str):
        super().__init__(title=tr(locale, "action.message_link_modal_title"))
        self.source_message = source_message
        self.locale = locale
        self.action_reference = discord.ui.TextInput(
            label=tr(locale, "action.message_link_reference_label"),
            placeholder=tr(locale, "action.message_link_reference_placeholder"),
            max_length=64,
        )
        self.add_item(self.action_reference)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if not await ensure_bot_permission(
            interaction,
            "moderation.actions.link_messages",
            locale=self.locale,
        ):
            return

        try:
            async with get_async_session() as session:
                action = await resolve_moderation_action_reference(
                    session,
                    server_id=interaction.guild.id,
                    reference=str(self.action_reference.value),
                )
                if action is None:
                    await interaction.followup.send(tr(self.locale, "action.not_found"), ephemeral=True)
                    return
                await _archive_source_message(
                    session,
                    source_message=self.source_message,
                    moderator=interaction.user,
                )
                result = await link_message_to_action(
                    session,
                    action_id=action.id,
                    message_id=self.source_message.id,
                    linked_by_user_id=interaction.user.id,
                )
                await session.commit()
        except Exception as error:
            await interaction.followup.send(
                tr(self.locale, "action.message_link_failed", error=error),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            tr(
                self.locale,
                "action.message_linked",
                message_id=result.message_id,
                action_number=action.action_number,
                action_url=_dashboard_action_url(interaction.guild.id, action.id),
            ),
            ephemeral=True,
        )


async def link_message_to_action_context(
    interaction: discord.Interaction,
    message: discord.Message,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(
        interaction,
        "moderation.actions.link_messages",
        locale=locale,
    ):
        return
    await interaction.response.send_modal(
        LinkMessageToActionModal(source_message=message, locale=locale)
    )


class StartActionCommentaryModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        source_message: discord.Message,
        action_type: ActionType,
        rule_id: str,
        duration: str,
        locale: str,
    ):
        super().__init__(title=tr(locale, "action.message_start_modal_title"))
        self.source_message = source_message
        self.action_type = action_type
        self.rule_id = rule_id
        self.duration = duration
        self.locale = locale
        self.commentary = discord.ui.TextInput(
            label=tr(locale, "action.reason_label"),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
            placeholder=tr(locale, "action.message_start_commentary_placeholder"),
        )
        self.add_item(self.commentary)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        permission_key = ACTION_PERMISSION_KEYS[self.action_type]
        if not _has_discord_permission(interaction.user, self.action_type):
            await interaction.followup.send(
                tr(self.locale, "action.message_start_discord_permission"),
                ephemeral=True,
            )
            return
        if not await ensure_bot_permission(interaction, permission_key, locale=self.locale):
            return

        target = self.source_message.author
        if not isinstance(target, discord.Member):
            try:
                target = await interaction.guild.fetch_member(target.id)
            except (discord.NotFound, discord.HTTPException):
                await interaction.followup.send(
                    tr(self.locale, "action.message_start_target_missing"),
                    ephemeral=True,
                )
                return
        target_error = validate_target_for_moderation(interaction, target, self.locale)
        if target_error:
            await interaction.followup.send(target_error, ephemeral=True)
            return

        try:
            async with get_async_session() as session:
                rules = await fetch_active_rule_models(
                    session=session,
                    server_id=interaction.guild.id,
                )
                selected_rule = find_rule(rules, self.rule_id)
                if selected_rule is None:
                    await interaction.followup.send(
                        tr(self.locale, "action.invalid_rule"),
                        ephemeral=True,
                    )
                    return

                expires_at = None
                if self.action_type == ActionType.MUTE:
                    settings = await session.get(ServerModerationSettings, interaction.guild.id)
                    if settings is None or settings.default_mute_minutes is None:
                        raise ValueError(tr(self.locale, "action.message_start_mute_default_missing"))
                    minutes = settings.default_mute_minutes
                    if self.duration != "default":
                        minutes = parse_duration_text(
                            self.duration,
                            max_minutes=settings.max_mute_minutes,
                        ).minutes
                    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
                elif self.action_type == ActionType.BAN and self.duration != "default":
                    minutes = parse_duration_text(self.duration).minutes
                    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)

                await _archive_source_message(
                    session,
                    source_message=self.source_message,
                    moderator=interaction.user,
                )
                created = await create_bot_moderation_action(
                    session=session,
                    interaction=interaction,
                    user=target,
                    action_type=self.action_type,
                    rule_id=selected_rule.id,
                    commentary=str(self.commentary.value or "").strip() or None,
                    reason=None,
                    expires_at=expires_at,
                )
                await link_message_to_action(
                    session,
                    action_id=created.id,
                    message_id=self.source_message.id,
                    linked_by_user_id=interaction.user.id,
                )
                await session.commit()
        except Exception as error:
            detail = getattr(error, "detail", None) or str(error)
            await interaction.followup.send(
                tr(self.locale, "action.log_failed", error=detail),
                ephemeral=True,
            )
            return

        selected_rule_label = rule_label(selected_rule)
        public_message = tr(
            self.locale,
            "action.message_start_success",
            mention=target.mention,
            action_type=self.action_type.value,
            rule=selected_rule_label,
        )
        await send_public_action_notice(interaction, public_message)
        await interaction.followup.send(
            build_moderator_action_receipt(
                locale=self.locale,
                server_id=interaction.guild.id,
                public_message=public_message,
                action=created,
                rule=selected_rule_label,
                extra_lines=[
                    (
                        tr(self.locale, "action.message_link_label"),
                        str(self.source_message.id),
                    )
                ],
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class StartActionFromMessageView(discord.ui.View):
    def __init__(
        self,
        *,
        source_message: discord.Message,
        rules,
        locale: str,
        requesting_user_id: int,
    ):
        super().__init__(timeout=180)
        self.source_message = source_message
        self.locale = locale
        self.requesting_user_id = requesting_user_id
        self.action_type: ActionType | None = None
        self.rule_id: str | None = None
        self.duration = "default"

        action_select = discord.ui.Select(
            placeholder=tr(locale, "action.message_start_type_placeholder"),
            options=[
                discord.SelectOption(label=kind.value.title(), value=kind.value)
                for kind in (ActionType.WARN, ActionType.MUTE, ActionType.KICK, ActionType.BAN)
            ],
            min_values=1,
            max_values=1,
        )
        action_select.callback = self._select_action_type
        self.add_item(action_select)

        rule_select = discord.ui.Select(
            placeholder=tr(locale, "action.message_start_rule_placeholder"),
            options=[
                discord.SelectOption(label=rule_label(rule)[:100], value=str(rule.id))
                for rule in rules[:25]
            ],
            min_values=1,
            max_values=1,
        )
        rule_select.callback = self._select_rule
        self.add_item(rule_select)

        duration_select = discord.ui.Select(
            placeholder=tr(locale, "action.message_start_duration_placeholder"),
            options=[
                discord.SelectOption(
                    label=tr(locale, "action.message_start_duration_default"),
                    value="default",
                ),
                discord.SelectOption(label="10 minutes", value="10m"),
                discord.SelectOption(label="1 hour", value="1h"),
                discord.SelectOption(label="1 day", value="1d"),
                discord.SelectOption(label="1 week", value="1w"),
                discord.SelectOption(label="30 days", value="30d"),
            ],
            min_values=1,
            max_values=1,
        )
        duration_select.callback = self._select_duration
        self.add_item(duration_select)

        self.continue_button = discord.ui.Button(
            label=tr(locale, "action.message_start_continue"),
            style=discord.ButtonStyle.danger,
            disabled=True,
        )
        self.continue_button.callback = self._continue
        self.add_item(self.continue_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requesting_user_id:
            return True
        await interaction.response.send_message(
            tr(self.locale, "action.message_start_owner_only"),
            ephemeral=True,
        )
        return False

    async def _select_action_type(self, interaction: discord.Interaction) -> None:
        self.action_type = ActionType(interaction.data["values"][0])
        self.continue_button.disabled = self.rule_id is None
        await interaction.response.edit_message(view=self)

    async def _select_rule(self, interaction: discord.Interaction) -> None:
        self.rule_id = interaction.data["values"][0]
        self.continue_button.disabled = self.action_type is None
        await interaction.response.edit_message(view=self)

    async def _select_duration(self, interaction: discord.Interaction) -> None:
        self.duration = interaction.data["values"][0]
        await interaction.response.defer()

    async def _continue(self, interaction: discord.Interaction) -> None:
        if self.action_type is None or self.rule_id is None:
            await interaction.response.send_message(
                tr(self.locale, "action.message_start_selection_required"),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            StartActionCommentaryModal(
                source_message=self.source_message,
                action_type=self.action_type,
                rule_id=self.rule_id,
                duration=self.duration,
                locale=self.locale,
            )
        )


async def start_action_from_message_context(
    interaction: discord.Interaction,
    message: discord.Message,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.moderate_members:
        await interaction.followup.send(
            tr(locale, "action.message_start_discord_permission"),
            ephemeral=True,
        )
        return
    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(
                session=session,
                server_id=interaction.guild.id,
            )
    except Exception as error:
        await interaction.followup.send(
            tr(locale, "action.fetch_rules_failed", error=error),
            ephemeral=True,
        )
        return
    if not rules:
        await interaction.followup.send(tr(locale, "action.invalid_rule"), ephemeral=True)
        return
    await interaction.followup.send(
        tr(locale, "action.message_start_prompt", message_id=message.id),
        view=StartActionFromMessageView(
            source_message=message,
            rules=rules,
            locale=locale,
            requesting_user_id=interaction.user.id,
        ),
        ephemeral=True,
    )


async def handle_reply_action_link_command(message: discord.Message) -> bool:
    match = REPLY_LINK_PATTERN.fullmatch(message.content.strip())
    if match is None:
        return False
    if message.guild is None or message.reference is None or message.reference.message_id is None:
        await message.reply("Reply to the message you want to link, then use `!link_action #123`.")
        return True
    if not isinstance(message.author, discord.Member) or not message.author.guild_permissions.moderate_members:
        await message.reply("You need the Moderate Members permission to link action evidence.")
        return True
    locale = await get_server_locale(message.guild.id)
    if not await has_bot_permission(
        guild_id=message.guild.id,
        user_id=message.author.id,
        permission_key="moderation.actions.link_messages",
    ):
        await message.reply(
            tr(locale, "rbac.command_denied", permission="moderation.actions.link_messages")
        )
        return True

    try:
        async with get_async_session() as session:
            action = await resolve_moderation_action_reference(
                session,
                server_id=message.guild.id,
                reference=match.group("reference"),
            )
            if action is None:
                await message.reply(tr(locale, "action.not_found"))
                return True
            source_message = message.reference.resolved
            if isinstance(source_message, discord.Message):
                await _archive_source_message(
                    session,
                    source_message=source_message,
                    moderator=message.author,
                )
            result = await link_message_to_action(
                session,
                action_id=action.id,
                message_id=message.reference.message_id,
                linked_by_user_id=message.author.id,
            )
            await session.commit()
    except Exception as error:
        await message.reply(tr(locale, "action.message_link_failed", error=error))
        return True

    await message.reply(
        tr(
            locale,
            "action.message_linked",
            message_id=result.message_id,
            action_number=action.action_number,
            action_url=_dashboard_action_url(message.guild.id, action.id),
        ),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return True


link_message_to_action_ctx = app_commands.ContextMenu(
    name="Link Message to Action",
    callback=link_message_to_action_context,
)
link_message_to_action_ctx.default_permissions = discord.Permissions(moderate_members=True)
link_message_to_action_ctx.guild_only = True

start_action_from_message_ctx = app_commands.ContextMenu(
    name="Start Moderation Action",
    callback=start_action_from_message_context,
)
start_action_from_message_ctx.default_permissions = discord.Permissions(moderate_members=True)
start_action_from_message_ctx.guild_only = True

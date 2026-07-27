from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
from sqlmodel import select

from api.models.moderation_actions import ModerationActionMessageCleanupCreate
from api.services.moderation_action_numbers import resolve_moderation_action_reference
from api.services.moderation_actions_service import (
    _dashboard_action_url,
    create_action,
    list_action_summaries,
    send_action_revert_dm,
    send_manual_unban_dm,
)
from api.services.moderation_settings import get_or_create_server_moderation_settings
from src.db.database import get_async_session
from src.db.models import ActionType, GlobalUser, ModerationAction, ServerModerationSettings
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.bot_services import (
    CASE_NEW_VALUE,
    action_choices,
    action_message_cleanup_choices,
    build_moderator_action_receipt,
    case_choices,
    build_action_payload,
    build_message_cleanup_request,
    fetch_active_rule_models,
    fetch_case_autocomplete_models,
    find_rule,
    message_cleanup_receipt_lines,
    resolve_case_id_for_action,
    rule_choices,
    rule_label,
    validate_target_for_moderation,
)
from src.modules.moderation.bot_rbac import ensure_bot_permission, has_bot_permission
from src.modules.moderation.durations import (
    configured_duration_choices,
    resolve_configured_duration_selection,
)
from src.modules.moderation.mod_log import build_action_revert_log_embed, send_mod_log_message
from src.modules.moderation.public_notices import send_public_action_notice
from src.modules.moderation.mute_management import deactivate_user_bans


async def _fetch_action_for_server(
    session,
    server_id: int,
    action_id: str | int,
) -> ModerationAction | None:
    return await resolve_moderation_action_reference(
        session,
        server_id=server_id,
        reference=action_id,
    )


async def _resolve_global_username(user_id: int) -> str | None:
    async with get_async_session() as session:
        user = await session.get(GlobalUser, user_id)
    return user.username if user else None


def _can_use_action_revert_controls(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction, "permissions", None)
    if permissions is None:
        permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.moderate_members)


async def _revert_action(
    *,
    interaction: discord.Interaction,
    action: ModerationAction,
    locale: str,
    reason: str,
) -> tuple[bool, str | None]:
    if not action.is_active:
        return False, tr(locale, "action.revert_inactive")

    reverted = False
    if action.action_type == ActionType.MUTE:
        async with get_async_session() as session:
            settings = await session.get(ServerModerationSettings, action.server_id)
        role = interaction.guild.get_role(settings.mute_role_id) if settings and settings.mute_role_id else None
        member = interaction.guild.get_member(action.target_user_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(action.target_user_id)
            except (discord.NotFound, discord.HTTPException):
                member = None
        if role is not None and member is not None and role in member.roles:
            await member.remove_roles(role, reason=reason)
            reverted = True
    elif action.action_type == ActionType.BAN:
        try:
            await interaction.guild.unban(discord.Object(id=action.target_user_id), reason=reason)
            reverted = True
        except discord.NotFound:
            reverted = False
    elif action.action_type == ActionType.WARN:
        reverted = False
    else:
        return False, tr(locale, "action.revert_unavailable")

    async with get_async_session() as session:
        stored = await session.get(ModerationAction, action.id)
        if stored is not None:
            stored.is_active = False
            stored.expires_at = stored.expires_at or datetime.now(timezone.utc)
            session.add(stored)
            await session.commit()
            await send_action_revert_dm(
                session=session,
                action=stored,
                reason=reason,
            )

    async with get_async_session() as session:
        settings = await session.get(ServerModerationSettings, action.server_id)
    if settings and settings.mod_log_channel_id:
        embed = build_action_revert_log_embed(
            server_id=action.server_id,
            action_type=action.action_type.value,
            action_id=str(action.id),
            action_number=action.action_number,
            action_url=_dashboard_action_url(action.server_id, action.id),
            target_user_id=action.target_user_id,
            target_display=await _resolve_global_username(action.target_user_id),
            moderator_user_id=interaction.user.id,
            moderator_display=getattr(interaction.user, "display_name", None) or str(interaction.user),
            reason=reason,
            reverted=reverted,
            locale=locale,
        )
        await send_mod_log_message(interaction.guild, settings.mod_log_channel_id, embed=embed)

    return reverted, None


class ActionRevertReasonModal(discord.ui.Modal):
    def __init__(self, *, action_id: str, locale: str):
        super().__init__(title=tr(locale, "action.revert_modal_title"))
        self.action_id = action_id
        self.locale = locale
        self.reason = discord.ui.TextInput(
            label=tr(locale, "action.revert_reason_label"),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=800,
            placeholder=tr(locale, "action.revert_reason_placeholder"),
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        locale = await get_server_locale(interaction.guild.id)
        if not _can_use_action_revert_controls(interaction):
            await interaction.followup.send(
                tr(locale, "action.revert_discord_permission_required"),
                ephemeral=True,
            )
            return
        if not await ensure_bot_permission(interaction, "moderation.actions.revert", locale=locale):
            return
        async with get_async_session() as session:
            action = await _fetch_action_for_server(session, interaction.guild.id, self.action_id)
        if action is None:
            await interaction.followup.send(tr(locale, "action.not_found"), ephemeral=True)
            return
        reason = str(self.reason.value or "").strip() or tr(
            locale,
            "modlog.reason_reverted_by_discord",
            moderator=f"<@{interaction.user.id}>",
        )
        try:
            reverted, error = await _revert_action(
                interaction=interaction,
                action=action,
                locale=locale,
                reason=reason,
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return
        success_message = tr(
            locale,
            "action.revert_success",
            action_type=action.action_type.value,
            action_number=action.action_number,
            reverted=reverted,
        )
        await send_public_action_notice(interaction, success_message)
        await interaction.followup.send(
            build_moderator_action_receipt(
                locale=locale,
                server_id=interaction.guild.id,
                public_message=success_message,
                action=action,
                extra_lines=[
                    (tr(locale, "action.reason_label"), reason),
                    (tr(locale, "modlog.reverted_label"), reverted),
                ],
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class ActionRevertConfirmationView(discord.ui.View):
    def __init__(self, *, action_id: str, locale: str, requesting_user_id: int):
        super().__init__(timeout=60)
        self.action_id = action_id
        self.locale = locale
        self.requesting_user_id = requesting_user_id
        self.confirm_button.label = tr(locale, "action.revert_confirm_button")
        self.cancel_button.label = tr(locale, "action.revert_cancel_button")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requesting_user_id:
            return True
        await interaction.response.send_message(
            tr(self.locale, "action.revert_confirmation_owner_only"),
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Confirm revert", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.stop()
        await interaction.response.send_modal(
            ActionRevertReasonModal(action_id=self.action_id, locale=self.locale)
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content=tr(self.locale, "action.revert_cancelled"),
            view=None,
        )


async def _open_action_revert_confirmation(
    interaction: discord.Interaction,
    action_id: str,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not _can_use_action_revert_controls(interaction):
        await interaction.followup.send(
            tr(locale, "action.revert_discord_permission_required"),
            ephemeral=True,
        )
        return
    if not await ensure_bot_permission(
        interaction,
        "moderation.actions.revert",
        locale=locale,
    ):
        return
    async with get_async_session() as session:
        action = await _fetch_action_for_server(session, interaction.guild.id, action_id)
    if action is None:
        await interaction.followup.send(tr(locale, "action.not_found"), ephemeral=True)
        return
    if action.action_type not in {ActionType.WARN, ActionType.MUTE, ActionType.BAN}:
        await interaction.followup.send(tr(locale, "action.revert_unavailable"), ephemeral=True)
        return
    if not action.is_active:
        await interaction.followup.send(tr(locale, "action.revert_inactive"), ephemeral=True)
        return
    await interaction.followup.send(
        tr(
            locale,
            "action.revert_confirm_prompt",
            action_type=action.action_type.value,
            action_number=action.action_number,
            target=f"<@{action.target_user_id}>",
        ),
        view=ActionRevertConfirmationView(
            action_id=str(action.id),
            locale=locale,
            requesting_user_id=interaction.user.id,
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


class ActionLogRevertButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"mod-action:revert:(?P<action_id>[0-9a-fA-F-]{36})",
):
    def __init__(self, *, action_id: str):
        self.action_id = action_id
        super().__init__(
            discord.ui.Button(
                label="Revert",
                style=discord.ButtonStyle.danger,
                custom_id=f"mod-action:revert:{action_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item,
        match,
    ):
        return cls(action_id=match["action_id"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await _open_action_revert_confirmation(interaction, self.action_id)


def register_moderation_action_components(client: discord.Client) -> None:
    client.add_dynamic_items(ActionLogRevertButton)


async def _create_member_action(
    *,
    interaction: discord.Interaction,
    user: discord.Member | discord.User,
    action_type: ActionType,
    rule: str,
    commentary: str | None,
    case: str | None,
    expires_at: datetime | None = None,
    message_cleanup: ModerationActionMessageCleanupCreate | None = None,
    add_warn: bool = False,
):
    locale = await get_server_locale(interaction.guild.id)
    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild.id)
            settings = await get_or_create_server_moderation_settings(
                session=session,
                server_id=interaction.guild.id,
            )
    except Exception as error:
        await interaction.followup.send(tr(locale, "action.fetch_rules_failed", error=error), ephemeral=True)
        return None

    selected_rule = find_rule(rules, rule)
    if selected_rule is None:
        await interaction.followup.send(tr(locale, "action.invalid_rule"), ephemeral=True)
        return None

    ignored_role_ids = {settings.mute_role_id} if settings.mute_role_id else None
    target_error = validate_target_for_moderation(
        interaction,
        user,
        locale,
        ignored_role_ids=ignored_role_ids,
    )
    if target_error:
        await interaction.followup.send(target_error, ephemeral=True)
        return None

    commentary_text = commentary.strip() if commentary else None
    selected_rule_label = rule_label(selected_rule)
    try:
        async with get_async_session() as session:
            case_id = await resolve_case_id_for_action(
                session=session,
                interaction=interaction,
                user=user,
                action_type=action_type,
                selected_case=case or (CASE_NEW_VALUE if add_warn else None),
                selected_rule=selected_rule,
                selected_rule_label=selected_rule_label,
                commentary=commentary_text,
            )
            payload = build_action_payload(
                interaction=interaction,
                user=user,
                action_type=action_type,
                rule_id=selected_rule.id,
                commentary=commentary_text,
                reason=None,
                expires_at=expires_at,
                case_id=case_id,
                message_cleanup=message_cleanup,
            )
            created = await create_action(
                session=session,
                action=payload,
                moderator_user_id=interaction.user.id,
                apply_discord_effects=True,
            )
            linked_warn = None
            if add_warn:
                warn_payload = build_action_payload(
                    interaction=interaction,
                    user=user,
                    action_type=ActionType.WARN,
                    rule_id=selected_rule.id,
                    commentary=commentary_text,
                    reason=None,
                    case_id=case_id,
                )
                linked_warn = await create_action(
                    session=session,
                    action=warn_payload,
                    moderator_user_id=interaction.user.id,
                    apply_discord_effects=False,
                )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "action.log_failed", error=error), ephemeral=True)
        return None
    return created, selected_rule_label, linked_warn


def _linked_warn_receipt_lines(
    *,
    locale: str,
    server_id: int,
    linked_warn: ModerationAction | None,
) -> list[tuple[str, str]]:
    if linked_warn is None:
        return []
    return [
        (
            tr(locale, "action.linked_warn_label"),
            f"[`#{linked_warn.action_number}`]({_dashboard_action_url(server_id, linked_warn.id)})",
        )
    ]


@app_commands.checks.has_permissions(kick_members=True)
@app_commands.command(name="kick", description="Kick a user and log the action.")
@app_commands.describe(add_warn="Also create a warning for the same rule and commentary.")
async def kick(
    interaction: discord.Interaction,
    user: discord.Member,
    rule: str,
    commentary: str | None = None,
    case: str | None = None,
    add_warn: bool = False,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.apply.kick", locale=locale):
        return
    result = await _create_member_action(
        interaction=interaction,
        user=user,
        action_type=ActionType.KICK,
        rule=rule,
        commentary=commentary,
        case=case,
        add_warn=add_warn,
    )
    if result is None:
        return
    created, selected_rule_label, linked_warn = result
    success_message = tr(locale, "action.kick_success", mention=user.mention, rule=selected_rule_label)
    await send_public_action_notice(interaction, success_message)
    await interaction.followup.send(
        build_moderator_action_receipt(
            locale=locale,
            server_id=interaction.guild.id,
            public_message=success_message,
            action=created,
            rule=selected_rule_label,
            extra_lines=_linked_warn_receipt_lines(
                locale=locale,
                server_id=interaction.guild.id,
                linked_warn=linked_warn,
            ),
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@app_commands.checks.has_permissions(ban_members=True)
@app_commands.command(name="ban", description="Ban a user with an optional expiration and log the action.")
@app_commands.choices(
    delete_messages=action_message_cleanup_choices(),
)
@app_commands.describe(
    add_warn="Also create a warning for the same rule and commentary.",
    delete_messages="Delete recent logged messages by this user.",
    delete_message_limit="Maximum messages to delete when delete_messages is set.",
    delete_message_channel="Only delete messages from this channel.",
)
async def ban(
    interaction: discord.Interaction,
    user: discord.User,
    rule: str,
    duration: str | None = None,
    commentary: str | None = None,
    case: str | None = None,
    add_warn: bool = False,
    delete_messages: app_commands.Choice[int] | None = None,
    delete_message_limit: app_commands.Range[int, 1, 100] | None = None,
    delete_message_channel: discord.TextChannel | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.apply.ban", locale=locale):
        return
    async with get_async_session() as session:
        settings = await get_or_create_server_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
        )
        try:
            duration_selection = resolve_configured_duration_selection(
                selection=duration,
                default_minutes=settings.default_ban_minutes,
                presets_minutes=settings.ban_duration_presets,
                allow_permanent=True,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

    expires_at = None
    if duration_selection.minutes is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=duration_selection.minutes)
    message_cleanup = build_message_cleanup_request(
        delete_messages=delete_messages,
        delete_message_limit=delete_message_limit,
        delete_message_channel=delete_message_channel,
    )
    result = await _create_member_action(
        interaction=interaction,
        user=user,
        action_type=ActionType.BAN,
        rule=rule,
        commentary=commentary,
        case=case,
        expires_at=expires_at,
        message_cleanup=message_cleanup,
        add_warn=add_warn,
    )
    if result is None:
        return
    created, selected_rule_label, linked_warn = result
    duration = (
        tr(locale, "action.ban_duration_suffix", duration=duration_selection.label)
        if duration_selection.minutes is not None
        else ""
    )
    success_message = tr(locale, "action.ban_success", mention=user.mention, rule=selected_rule_label, duration=duration)
    await send_public_action_notice(interaction, success_message)
    await interaction.followup.send(
        build_moderator_action_receipt(
            locale=locale,
            server_id=interaction.guild.id,
            public_message=success_message,
            action=created,
            rule=selected_rule_label,
            extra_lines=[
                *_linked_warn_receipt_lines(
                    locale=locale,
                    server_id=interaction.guild.id,
                    linked_warn=linked_warn,
                ),
                *message_cleanup_receipt_lines(
                    locale=locale,
                    cleanup=message_cleanup,
                    channel=delete_message_channel,
                ),
            ],
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@app_commands.checks.has_permissions(ban_members=True)
@app_commands.command(name="unban", description="Unban a user and close active ban actions.")
async def unban(interaction: discord.Interaction, user: discord.User, reason: str | None = None):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.apply.ban", locale=locale):
        return
    note = reason.strip() if reason else "Manual unban"
    try:
        await interaction.guild.unban(user, reason=f"Unbanned by {interaction.user} ({interaction.user.id}). {note}")
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
        await interaction.followup.send(tr(locale, "action.unban_failed", error=error), ephemeral=True)
        return
    async with get_async_session() as session:
        deactivated = await deactivate_user_bans(session, interaction.guild.id, user.id)
        await send_manual_unban_dm(
            session=session,
            server_id=interaction.guild.id,
            target_user_id=user.id,
            reason=note,
        )
        await session.commit()
    success_message = tr(locale, "action.unban_success", mention=user.mention, deactivated=deactivated)
    await send_public_action_notice(interaction, success_message)
    await interaction.followup.send(
        build_moderator_action_receipt(
            locale=locale,
            server_id=interaction.guild.id,
            public_message=success_message,
            action_type="unban",
            extra_lines=[
                (tr(locale, "action.reason_label"), note),
                (tr(locale, "modlog.closed_actions_label"), deactivated),
            ],
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@kick.autocomplete("rule")
@ban.autocomplete("rule")
async def action_rule_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild_id)
    except Exception:
        return []
    return rule_choices(rules, current)


@ban.autocomplete("duration")
async def ban_duration_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    try:
        async with get_async_session() as session:
            settings = await get_or_create_server_moderation_settings(
                session=session,
                server_id=interaction.guild_id,
            )
            choices = configured_duration_choices(
                settings.ban_duration_presets,
                include_default=True,
                include_permanent=True,
            )
    except Exception:
        return []
    normalized = current.casefold().strip()
    return [choice for choice in choices if not normalized or normalized in choice.name.casefold()][:25]


@kick.autocomplete("case")
@ban.autocomplete("case")
async def action_case_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    command_name = getattr(getattr(interaction, "command", None), "name", "")
    permission_key = (
        "moderation.actions.apply.ban"
        if command_name == "ban"
        else "moderation.actions.apply.kick"
    )
    if not await has_bot_permission(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        permission_key=permission_key,
    ):
        return []
    target = getattr(getattr(interaction, "namespace", None), "user", None)
    target_id = getattr(target, "id", None)
    try:
        async with get_async_session() as session:
            cases = await fetch_case_autocomplete_models(session=session, server_id=interaction.guild_id, user_id=target_id)
    except Exception:
        return []
    return case_choices(cases, current)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="list", description="List recent moderation actions.")
async def actions_list(
    interaction: discord.Interaction,
    user: discord.Member | None = None,
    limit: app_commands.Range[int, 1, 10] = 5,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.view", locale=locale):
        return
    async with get_async_session() as session:
        actions = await list_action_summaries(
            session=session,
            server_id=interaction.guild.id,
            target_user_id=user.id if user else None,
            limit=limit,
        )
    if not actions:
        await interaction.followup.send(tr(locale, "action.none"), ephemeral=True)
        return
    embed = discord.Embed(title=tr(locale, "action.list_title"), color=discord.Color.blurple())
    for action in actions:
        action_type = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        value = "\n".join(
            [
                f"{tr(locale, 'modlog.target_label')}: <@{action.target_user_id}>",
                f"{tr(locale, 'modlog.reason_label')}: {action.reason[:220]}",
                *(
                    [f"{tr(locale, 'modlog.created_at_label')}: {action.created_at_label}"]
                    if getattr(action, "created_at_label", None)
                    else []
                ),
                f"{tr(locale, 'modlog.action_number_label')}: [#{action.action_number}]({_dashboard_action_url(interaction.guild.id, action.id)})",
                f"Active: `{action.is_active}`",
            ]
        )
        embed.add_field(name=f"{action_type} #{action.action_number}", value=value, inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="undo", description="Undo an active warn, mute, or ban action by its number.")
@app_commands.describe(
    action_number="Sequential moderation action number.",
    reason="Optional reason for undoing the action.",
)
async def action_revert(
    interaction: discord.Interaction,
    action_number: int,
    reason: str | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.revert", locale=locale):
        return
    async with get_async_session() as session:
        action = await _fetch_action_for_server(session, interaction.guild.id, action_number)
    if action is None:
        await interaction.followup.send(tr(locale, "action.not_found"), ephemeral=True)
        return
    resolved_reason = reason.strip() if reason else tr(
        locale,
        "modlog.reason_reverted_by_discord",
        moderator=f"<@{interaction.user.id}>",
    )
    try:
        reverted, error = await _revert_action(
            interaction=interaction,
            action=action,
            locale=locale,
            reason=resolved_reason,
        )
    except (discord.Forbidden, discord.HTTPException) as error:
        await interaction.followup.send(str(error), ephemeral=True)
        return
    if error:
        await interaction.followup.send(error, ephemeral=True)
        return
    success_message = tr(
        locale,
        "action.revert_success",
        action_type=action.action_type.value,
        action_number=action.action_number,
        reverted=reverted,
    )
    await send_public_action_notice(interaction, success_message)
    await interaction.followup.send(
        build_moderator_action_receipt(
            locale=locale,
            server_id=interaction.guild.id,
            public_message=success_message,
            action=action,
            extra_lines=[
                (tr(locale, "action.reason_label"), resolved_reason),
                (tr(locale, "modlog.reverted_label"), reverted),
            ],
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@action_revert.autocomplete("action_number")
async def action_revert_autocomplete(interaction: discord.Interaction, current: int | float):
    if interaction.guild_id is None:
        return []
    if not await has_bot_permission(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        permission_key="moderation.actions.revert",
    ):
        return []
    try:
        async with get_async_session() as session:
            actions = await list_action_summaries(
                session=session,
                server_id=interaction.guild_id,
                limit=100,
                action_types={ActionType.WARN, ActionType.MUTE, ActionType.BAN},
                is_active=True,
            )
    except Exception:
        return []
    current_text = str(int(current)) if current else ""
    return [
        app_commands.Choice(name=choice.name, value=int(choice.value))
        for choice in action_choices(actions, current_text)
    ]

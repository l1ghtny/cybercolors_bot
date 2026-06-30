from datetime import datetime, timedelta, timezone
from uuid import UUID

import discord
from discord import app_commands
from fastapi import HTTPException
from sqlmodel import select

from api.services.moderation_actions_service import (
    _dashboard_action_url,
    create_action,
    get_action_details,
    list_action_summaries,
)
from src.db.database import get_async_session
from src.db.models import ActionType, ModerationAction, ServerModerationSettings
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.bot_services import (
    build_moderator_action_receipt,
    case_choices,
    build_action_payload,
    fetch_active_rule_models,
    fetch_open_case_models,
    find_rule,
    resolve_case_id_for_action,
    rule_choices,
    rule_label,
    validate_target_for_moderation,
)
from src.modules.moderation.bot_rbac import ensure_bot_permission, has_bot_permission
from src.modules.moderation.durations import (
    action_duration_choices,
    duration_unit_choices,
    resolve_duration_selection,
)
from src.modules.moderation.mod_log import build_action_revert_log_message, send_mod_log_message
from src.modules.moderation.public_notices import send_public_action_notice
from src.modules.moderation.mute_management import deactivate_user_bans


async def _fetch_action_for_server(session, server_id: int, action_id: str) -> ModerationAction | None:
    try:
        parsed_id = UUID(str(action_id))
    except ValueError:
        return None
    action = await session.get(ModerationAction, parsed_id)
    if action is None or action.server_id != server_id:
        return None
    return action


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
    else:
        return False, tr(locale, "action.revert_unavailable")

    async with get_async_session() as session:
        stored = await session.get(ModerationAction, action.id)
        if stored is not None:
            stored.is_active = False
            stored.expires_at = stored.expires_at or datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(stored)
            await session.commit()

    async with get_async_session() as session:
        settings = await session.get(ServerModerationSettings, action.server_id)
    if settings and settings.mod_log_channel_id:
        content = build_action_revert_log_message(
            action_type=action.action_type.value,
            action_id=str(action.id),
            target_user_id=action.target_user_id,
            moderator_user_id=interaction.user.id,
            reason=reason,
            reverted=reverted,
            locale=locale,
        )
        await send_mod_log_message(interaction.guild, settings.mod_log_channel_id, content)

    return reverted, None


class ActionManageView(discord.ui.View):
    def __init__(self, *, server_id: int, action_id: str, can_revert: bool, locale: str):
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Button(
                label=tr(locale, "action.open_dashboard"),
                style=discord.ButtonStyle.link,
                url=_dashboard_action_url(server_id, action_id),
            )
        )
        self.add_item(
            discord.ui.Button(
                label=tr(locale, "action.add_info_dashboard"),
                style=discord.ButtonStyle.link,
                url=_dashboard_action_url(server_id, action_id),
            )
        )
        self.revert_button.label = tr(locale, "action.revert_button")
        self.revert_button.disabled = not can_revert

    @discord.ui.button(label="Revert", style=discord.ButtonStyle.danger)
    async def revert_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        locale = await get_server_locale(interaction.guild.id)
        if not await ensure_bot_permission(interaction, "moderation.actions.revert", locale=locale):
            return
        custom_id = interaction.message.embeds[0].footer.text if interaction.message and interaction.message.embeds else ""
        action_id = custom_id.replace("Action ID: ", "").strip()
        async with get_async_session() as session:
            action = await _fetch_action_for_server(session, interaction.guild.id, action_id)
        if action is None:
            await interaction.followup.send(tr(locale, "action.not_found"), ephemeral=True)
            return
        try:
            reverted, error = await _revert_action(
                interaction=interaction,
                action=action,
                locale=locale,
                reason=f"Reverted by {interaction.user} ({interaction.user.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return
        success_message = tr(locale, "action.revert_success", action_type=action.action_type.value, action_id=str(action.id)[:8], reverted=reverted)
        await send_public_action_notice(interaction, success_message)
        await interaction.followup.send(
            build_moderator_action_receipt(
                locale=locale,
                server_id=interaction.guild.id,
                public_message=success_message,
                action=action,
                extra_lines=[(tr(locale, "modlog.reverted_label"), reverted)],
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


def _action_embed(action, locale: str, server_id: int) -> discord.Embed:
    action_type = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
    embed = discord.Embed(
        title=f"{tr(locale, 'modlog.title')}: {action_type}",
        url=_dashboard_action_url(server_id, action.id),
        color=discord.Color.blurple(),
    )
    embed.add_field(name=tr(locale, "modlog.target_label"), value=f"<@{action.target_user_id}> (`{action.target_user_username}`)", inline=True)
    embed.add_field(name=tr(locale, "modlog.moderator_label"), value=f"<@{action.moderator_user_id}> (`{action.moderator_username}`)", inline=True)
    embed.add_field(name=tr(locale, "modlog.reason_label"), value=action.reason[:1024], inline=False)
    if action.case_id:
        embed.add_field(name=tr(locale, "modlog.case_label"), value=action.case_title or action.case_id, inline=False)
    if action.expires_at:
        embed.add_field(name=tr(locale, "modlog.expires_at_label"), value=action.expires_at.isoformat(), inline=True)
    if getattr(action, "created_at_label", None):
        embed.add_field(name=tr(locale, "modlog.created_at_label"), value=action.created_at_label, inline=False)
    embed.add_field(name="Active", value=str(action.is_active), inline=True)
    embed.set_footer(text=f"Action ID: {action.id}")
    return embed


async def _create_member_action(
    *,
    interaction: discord.Interaction,
    user: discord.Member,
    action_type: ActionType,
    rule: str,
    commentary: str | None,
    case: str | None,
    expires_at: datetime | None = None,
):
    locale = await get_server_locale(interaction.guild.id)
    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild.id)
    except Exception as error:
        await interaction.followup.send(tr(locale, "action.fetch_rules_failed", error=error), ephemeral=True)
        return None

    selected_rule = find_rule(rules, rule)
    if selected_rule is None:
        await interaction.followup.send(tr(locale, "action.invalid_rule"), ephemeral=True)
        return None

    target_error = validate_target_for_moderation(interaction, user, locale)
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
                selected_case=case,
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
            )
            created = await create_action(
                session=session,
                action=payload,
                moderator_user_id=interaction.user.id,
                apply_discord_effects=True,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "action.log_failed", error=error), ephemeral=True)
        return None
    return created, selected_rule_label


@app_commands.checks.has_permissions(kick_members=True)
@app_commands.command(name="kick", description="Kick a user and log the action.")
async def kick(
    interaction: discord.Interaction,
    user: discord.Member,
    rule: str,
    commentary: str | None = None,
    case: str | None = None,
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
    )
    if result is None:
        return
    created, selected_rule_label = result
    success_message = tr(locale, "action.kick_success", mention=user.mention, rule=selected_rule_label)
    await send_public_action_notice(interaction, success_message)
    await interaction.followup.send(
        build_moderator_action_receipt(
            locale=locale,
            server_id=interaction.guild.id,
            public_message=success_message,
            action=created,
            rule=selected_rule_label,
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@app_commands.checks.has_permissions(ban_members=True)
@app_commands.command(name="ban", description="Ban a user with an optional expiration and log the action.")
@app_commands.choices(
    duration=action_duration_choices(include_permanent=True),
    duration_unit=duration_unit_choices(),
)
async def ban(
    interaction: discord.Interaction,
    user: discord.Member,
    rule: str,
    duration: app_commands.Choice[str] | None = None,
    duration_value: app_commands.Range[int, 1, 999] | None = None,
    duration_unit: app_commands.Choice[str] | None = None,
    commentary: str | None = None,
    case: str | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.apply.ban", locale=locale):
        return
    try:
        duration_selection = resolve_duration_selection(
            preset=duration,
            custom_value=duration_value,
            custom_unit=duration_unit,
            default_minutes=None,
            allow_default=False,
            allow_permanent=True,
        )
    except ValueError as error:
        await interaction.followup.send(str(error), ephemeral=True)
        return

    expires_at = None
    if duration_selection.minutes is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=duration_selection.minutes)
    result = await _create_member_action(
        interaction=interaction,
        user=user,
        action_type=ActionType.BAN,
        rule=rule,
        commentary=commentary,
        case=case,
        expires_at=expires_at,
    )
    if result is None:
        return
    created, selected_rule_label = result
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
    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild_id)
    except Exception:
        return []
    return rule_choices(rules, current)


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
            cases = await fetch_open_case_models(session=session, server_id=interaction.guild_id, user_id=target_id)
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
                f"{tr(locale, 'modlog.action_id_label')}: [`{action.id[:8]}`]({_dashboard_action_url(interaction.guild.id, action.id)})",
                f"Active: `{action.is_active}`",
            ]
        )
        embed.add_field(name=f"{action_type} #{action.id[:8]}", value=value, inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="manage", description="Show action controls for a moderation action.")
async def action_manage(interaction: discord.Interaction, action_id: str):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.view", locale=locale):
        return
    try:
        async with get_async_session() as session:
            action = await get_action_details(session=session, server_id=interaction.guild.id, action_id=UUID(action_id))
    except (ValueError, HTTPException):
        await interaction.followup.send(tr(locale, "action.not_found"), ephemeral=True)
        return
    embed = _action_embed(action, locale, interaction.guild.id)
    can_revert = action.action_type in {ActionType.MUTE, ActionType.BAN} and action.is_active
    await interaction.followup.send(
        embed=embed,
        view=ActionManageView(server_id=interaction.guild.id, action_id=action.id, can_revert=can_revert, locale=locale),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="revert", description="Revert an active mute or ban action.")
async def action_revert(interaction: discord.Interaction, action_id: str, reason: str | None = None):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.revert", locale=locale):
        return
    async with get_async_session() as session:
        action = await _fetch_action_for_server(session, interaction.guild.id, action_id)
    if action is None:
        await interaction.followup.send(tr(locale, "action.not_found"), ephemeral=True)
        return
    try:
        reverted, error = await _revert_action(
            interaction=interaction,
            action=action,
            locale=locale,
            reason=reason.strip() if reason else f"Reverted by {interaction.user} ({interaction.user.id})",
        )
    except (discord.Forbidden, discord.HTTPException) as error:
        await interaction.followup.send(str(error), ephemeral=True)
        return
    if error:
        await interaction.followup.send(error, ephemeral=True)
        return
    success_message = tr(locale, "action.revert_success", action_type=action.action_type.value, action_id=str(action.id)[:8], reverted=reverted)
    await send_public_action_notice(interaction, success_message)
    await interaction.followup.send(
        build_moderator_action_receipt(
            locale=locale,
            server_id=interaction.guild.id,
            public_message=success_message,
            action=action,
            extra_lines=[
                (tr(locale, "action.reason_label"), reason.strip() if reason else None),
                (tr(locale, "modlog.reverted_label"), reverted),
            ],
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )

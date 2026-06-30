from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from api.models.moderation_settings import ServerModerationSettingsUpdateModel
from api.models.server_localization import ServerLocalizationSettingsUpdateModel
from api.services.moderation_settings import (
    get_or_create_server_moderation_settings,
    update_server_moderation_settings,
)
from api.services.server_localization import update_server_localization_settings
from src.db.database import get_async_session
from src.db.models import ActionType
from src.modules.localization.catalog import SUPPORTED_LOCALES
from src.modules.localization.service import get_server_locale, is_supported_locale, tr
from src.modules.moderation.bot_services import (
    build_moderator_action_receipt,
    case_choices,
    create_bot_moderation_action,
    fetch_active_rule_models,
    fetch_open_case_models,
    find_rule,
    resolve_case_id_for_action,
    rule_choices,
    rule_label,
    validate_target_for_moderation,
)
from src.modules.moderation.durations import (
    action_duration_choices,
    duration_unit_choices,
    resolve_duration_selection,
)
from src.modules.moderation.mute_management import (
    deactivate_user_mutes,
)
from src.modules.moderation.mod_log import build_unmute_log_message, send_mod_log_message
from src.modules.moderation.public_notices import send_public_action_notice


def _localized_bool(locale: str, value: bool) -> str:
    return tr(locale, "common.bool_true" if value else "common.bool_false")


async def _apply_mute_overwrites(guild: discord.Guild, role: discord.Role) -> tuple[int, int]:
    edited = 0
    failed = 0
    supported_types = (
        discord.TextChannel,
        discord.VoiceChannel,
        discord.StageChannel,
        discord.ForumChannel,
        discord.CategoryChannel,
    )
    for channel in guild.channels:
        if not isinstance(channel, supported_types):
            continue
        try:
            overwrite = channel.overwrites_for(role)
            overwrite.send_messages = False
            overwrite.add_reactions = False
            overwrite.send_messages_in_threads = False
            overwrite.create_public_threads = False
            overwrite.create_private_threads = False
            overwrite.speak = False
            overwrite.stream = False
            await channel.set_permissions(role, overwrite=overwrite, reason="Configure mute role defaults")
            edited += 1
        except Exception:
            failed += 1
    return edited, failed


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="moderation_settings",
    description="Show moderation settings for this server.",
)
async def moderation_settings(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    not_configured = tr(locale, "common.not_configured")
    async with get_async_session() as session:
        settings = await get_or_create_server_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
        )
        mute_role = interaction.guild.get_role(settings.mute_role_id) if settings.mute_role_id else None
        mute_role_name = mute_role.name if mute_role else not_configured
        mod_log_channel = (
            interaction.guild.get_channel(settings.mod_log_channel_id)
            if settings.mod_log_channel_id
            else None
        )
        mod_log_channel_label = (
            f"{mod_log_channel.mention} (`{settings.mod_log_channel_id}`)"
            if mod_log_channel is not None
            else (
                tr(locale, "settings.channel_not_found", channel_id=settings.mod_log_channel_id)
                if settings.mod_log_channel_id
                else not_configured
            )
        )
        await session.commit()

    await interaction.followup.send(
        "\n".join(
            [
                tr(locale, "settings.show_title"),
                tr(locale, "settings.mute_role", value=mute_role_name),
                tr(locale, "settings.mod_log_channel", value=mod_log_channel_label),
                tr(locale, "settings.language", value=locale),
                tr(locale, "settings.default_mute_minutes", value=settings.default_mute_minutes),
                tr(locale, "settings.max_mute_minutes", value=settings.max_mute_minutes),
                tr(locale, "settings.auto_reconnect", value=_localized_bool(locale, settings.auto_reconnect_voice_on_mute)),
            ]
        ),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="moderation_set_mute_role",
    description="Set the existing role to use for mutes.",
)
async def moderation_set_mute_role(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    async with get_async_session() as session:
        await update_server_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            body=ServerModerationSettingsUpdateModel(mute_role_id=str(role.id)),
        )
        await session.commit()

    locale = await get_server_locale(interaction.guild.id)
    await interaction.followup.send(tr(locale, "settings.mute_role_set", role_name=role.name), ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="moderation_set_log_channel",
    description="Set the moderation log channel.",
)
async def moderation_set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    try:
        async with get_async_session() as session:
            await update_server_moderation_settings(
                session=session,
                server_id=interaction.guild.id,
                body=ServerModerationSettingsUpdateModel(mod_log_channel_id=str(channel.id)),
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(str(error), ephemeral=True)
        return
    await interaction.followup.send(
        tr(locale, "settings.log_channel_set", mention=channel.mention),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="moderation_clear_log_channel",
    description="Clear moderation log channel setting.",
)
async def moderation_clear_log_channel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    async with get_async_session() as session:
        await update_server_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            body=ServerModerationSettingsUpdateModel(mod_log_channel_id=""),
        )
        await session.commit()
    await interaction.followup.send(tr(locale, "settings.log_channel_cleared"), ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="moderation_set_language",
    description="Set bot language for this server.",
)
@app_commands.choices(
    language=[
        app_commands.Choice(name="English", value="en"),
        app_commands.Choice(name="Russian", value="ru"),
    ]
)
async def moderation_set_language(interaction: discord.Interaction, language: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    current_locale = await get_server_locale(interaction.guild.id)
    requested = language.value.lower().strip()
    if not is_supported_locale(requested):
        await interaction.followup.send(
            tr(current_locale, "settings.language_not_supported", supported=", ".join(SUPPORTED_LOCALES)),
            ephemeral=True,
        )
        return
    async with get_async_session() as session:
        settings = await update_server_localization_settings(
            session=session,
            server_id=interaction.guild.id,
            body=ServerLocalizationSettingsUpdateModel(locale_code=requested),
        )
        updated = settings.locale_code
        await session.commit()
    await interaction.followup.send(
        tr(updated, "settings.language_updated", locale=updated),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="moderation_create_mute_role",
    description="Create a new mute role and attach it to moderation settings.",
)
async def moderation_create_mute_role(interaction: discord.Interaction, role_name: str = "Muted"):
    await interaction.response.defer(ephemeral=True)
    role = await interaction.guild.create_role(
        name=role_name,
        permissions=discord.Permissions.none(),
        reason=f"Created by {interaction.user} for moderation mute workflow",
    )
    edited, failed = await _apply_mute_overwrites(interaction.guild, role)

    async with get_async_session() as session:
        await update_server_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            body=ServerModerationSettingsUpdateModel(mute_role_id=str(role.id)),
        )
        await session.commit()

    locale = await get_server_locale(interaction.guild.id)
    await interaction.followup.send(
        tr(locale, "settings.mute_role_created", role_name=role.name, edited=edited, failed=failed),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="moderation_set_mute_defaults",
    description="Set default and maximum mute durations.",
)
async def moderation_set_mute_defaults(
    interaction: discord.Interaction,
    default_minutes: app_commands.Range[int, 1, 43200],
    max_minutes: app_commands.Range[int, 1, 43200] = 10080,
    auto_reconnect_on_mute: bool = True,
):
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if default_minutes > max_minutes:
        await interaction.followup.send(tr(locale, "settings.default_over_max"), ephemeral=True)
        return

    async with get_async_session() as session:
        await update_server_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            body=ServerModerationSettingsUpdateModel(
                default_mute_minutes=default_minutes,
                max_mute_minutes=max_minutes,
                auto_reconnect_voice_on_mute=auto_reconnect_on_mute,
            ),
        )
        await session.commit()

    await interaction.followup.send(
        tr(
            locale,
            "settings.defaults_updated",
            default_minutes=default_minutes,
            max_minutes=max_minutes,
            auto_reconnect=_localized_bool(locale, auto_reconnect_on_mute),
        ),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(
    name="mute",
    description="Apply role-based mute with rule + optional commentary.",
)
@app_commands.choices(
    duration=action_duration_choices(include_default=True),
    duration_unit=duration_unit_choices(),
)
async def mute(
    interaction: discord.Interaction,
    user: discord.Member,
    rule: str,
    duration: app_commands.Choice[str] | None = None,
    duration_value: app_commands.Range[int, 1, 999] | None = None,
    duration_unit: app_commands.Choice[str] | None = None,
    commentary: str | None = None,
    case: str | None = None,
):
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)

    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild.id)
    except Exception as error:
        await interaction.followup.send(tr(locale, "mute.fetch_rules_failed", error=error), ephemeral=True)
        return
    selected_rule = find_rule(rules, rule)
    if not selected_rule:
        await interaction.followup.send(tr(locale, "mute.invalid_rule"), ephemeral=True)
        return
    selected_rule_label = rule_label(selected_rule)

    moderation_target_error = validate_target_for_moderation(interaction, user, locale)
    if moderation_target_error:
        await interaction.followup.send(moderation_target_error, ephemeral=True)
        return

    async with get_async_session() as session:
        settings = await get_or_create_server_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
        )
        if not settings.mute_role_id:
            await interaction.followup.send(
                tr(locale, "mute.role_not_configured"),
                ephemeral=True,
            )
            return
        mute_role = interaction.guild.get_role(settings.mute_role_id)
        if mute_role is None:
            await interaction.followup.send(
                tr(locale, "mute.role_missing"),
                ephemeral=True,
            )
            return
        if interaction.guild.me and mute_role >= interaction.guild.me.top_role:
            await interaction.followup.send(
                tr(locale, "mute.role_too_high"),
                ephemeral=True,
            )
            return

        try:
            duration_selection = resolve_duration_selection(
                preset=duration,
                custom_value=duration_value,
                custom_unit=duration_unit,
                default_minutes=settings.default_mute_minutes,
                max_minutes=settings.max_mute_minutes,
                allow_default=True,
                allow_permanent=False,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

    effective_duration = duration_selection.minutes
    if effective_duration is None:
        await interaction.followup.send("Mute duration is required.", ephemeral=True)
        return
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=effective_duration)
    commentary_text = commentary.strip() if commentary else None
    try:
        async with get_async_session() as session:
            case_id = await resolve_case_id_for_action(
                session=session,
                interaction=interaction,
                user=user,
                action_type=ActionType.MUTE,
                selected_case=case,
                selected_rule=selected_rule,
                selected_rule_label=selected_rule_label,
                commentary=commentary_text,
            )
            created_action = await create_bot_moderation_action(
                session=session,
                interaction=interaction,
                user=user,
                action_type=ActionType.MUTE,
                rule_id=selected_rule.id,
                commentary=commentary_text,
                reason=None,
                expires_at=expires_at,
                case_id=case_id,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(
            tr(locale, "mute.log_failed", error=error),
            ephemeral=True,
        )
        return

    success_message = tr(
        locale,
        "mute.success",
        mention=user.mention,
        duration=duration_selection.label,
        rule=selected_rule_label,
        note="",
    )
    await send_public_action_notice(interaction, success_message)
    await interaction.followup.send(
        build_moderator_action_receipt(
            locale=locale,
            server_id=interaction.guild.id,
            public_message=success_message,
            action=created_action,
            rule=selected_rule_label,
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )

@mute.autocomplete("rule")
async def mute_rule_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild_id)
    except Exception:
        return []
    return rule_choices(rules, current)


@mute.autocomplete("case")
async def mute_case_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []

    target = getattr(getattr(interaction, "namespace", None), "user", None)
    target_id = getattr(target, "id", None)
    try:
        async with get_async_session() as session:
            cases = await fetch_open_case_models(
                session=session,
                server_id=interaction.guild_id,
                user_id=target_id,
            )
    except Exception:
        return []

    return case_choices(cases, current)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(
    name="unmute",
    description="Remove role-based mute and close active mute actions.",
)
async def unmute(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str | None = None,
):
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    note = reason.strip() if reason else tr(locale, "common.manual_unmute_reason")
    moderation_target_error = validate_target_for_moderation(interaction, user, locale)
    if moderation_target_error:
        await interaction.followup.send(moderation_target_error, ephemeral=True)
        return

    async with get_async_session() as session:
        settings = await get_or_create_server_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
        )

        removed_role = False
        if settings.mute_role_id:
            mute_role = interaction.guild.get_role(settings.mute_role_id)
            if mute_role and mute_role in user.roles:
                try:
                    await user.remove_roles(
                        mute_role,
                        reason=f"Unmuted by {interaction.user} ({interaction.user.id}). {note}",
                    )
                except discord.Forbidden:
                    await interaction.followup.send(
                        tr(locale, "unmute.remove_forbidden"),
                        ephemeral=True,
                    )
                    return
                except discord.HTTPException as error:
                    await interaction.followup.send(
                        tr(locale, "unmute.remove_failed", error=error),
                        ephemeral=True,
                    )
                    return
                removed_role = True

        deactivated = await deactivate_user_mutes(session, interaction.guild.id, user.id)
        await session.commit()

    if settings.mod_log_channel_id:
        content = build_unmute_log_message(
            target_user_id=user.id,
            target_display=user.display_name,
            moderator_user_id=interaction.user.id,
            moderator_display=interaction.user.display_name,
            reason=note,
            removed_role=removed_role,
            closed_actions=deactivated,
            is_auto=False,
            locale=locale,
        )
        await send_mod_log_message(
            guild=interaction.guild,
            mod_log_channel_id=settings.mod_log_channel_id,
            content=content,
        )

    success_message = tr(
        locale,
        "unmute.success",
        mention=user.mention,
        removed_role=_localized_bool(locale, removed_role),
        deactivated=deactivated,
    )
    await send_public_action_notice(interaction, success_message)
    await interaction.followup.send(
        build_moderator_action_receipt(
            locale=locale,
            server_id=interaction.guild.id,
            public_message=success_message,
            action_type="unmute",
            extra_lines=[
                (tr(locale, "action.reason_label"), note),
                (tr(locale, "modlog.removed_role_label"), _localized_bool(locale, removed_role)),
                (tr(locale, "modlog.closed_actions_label"), deactivated),
            ],
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )

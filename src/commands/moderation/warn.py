import discord
from discord import app_commands

from src.db.database import get_async_session
from src.db.models import ActionType
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.public_notices import send_public_action_notice
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
from src.modules.moderation.bot_rbac import ensure_bot_permission, has_bot_permission


@app_commands.command(
    name="warn",
    description="Warns a user and logs the action.",
)
async def warn(
    interaction: discord.Interaction,
    user: discord.Member,
    rule: str,
    commentary: str | None = None,
    case: str | None = None,
):
    """Handles /warn: select a declared server rule, add optional commentary, and log action."""
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.apply.warn", locale=locale):
        return

    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild.id)
    except Exception as error:
        await interaction.followup.send(
            tr(locale, "warn.fetch_rules_failed", error=error),
            ephemeral=True,
        )
        return

    selected_rule = find_rule(rules, rule)
    if not selected_rule:
        await interaction.followup.send(
            tr(locale, "warn.invalid_rule"),
            ephemeral=True,
        )
        return

    selected_rule_label = rule_label(selected_rule)
    commentary_text = commentary.strip() if commentary else None
    target_error = validate_target_for_moderation(interaction, user, locale)
    if target_error:
        await interaction.followup.send(target_error, ephemeral=True)
        return

    try:
        async with get_async_session() as session:
            case_id = await resolve_case_id_for_action(
                session=session,
                interaction=interaction,
                user=user,
                action_type=ActionType.WARN,
                selected_case=case,
                selected_rule=selected_rule,
                selected_rule_label=selected_rule_label,
                commentary=commentary_text,
            )
            created_action = await create_bot_moderation_action(
                session=session,
                interaction=interaction,
                user=user,
                action_type=ActionType.WARN,
                rule_id=selected_rule.id,
                commentary=commentary_text,
                reason=None,
                case_id=case_id,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(
            tr(
                locale,
                "warn.api_http_error",
                status=type(error).__name__,
                text=str(error),
            ),
            ephemeral=True,
        )
        return

    success_message = tr(locale, "warn.success", mention=user.mention, rule=selected_rule_label)
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


@warn.autocomplete("rule")
async def warn_rule_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    if not await has_bot_permission(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        permission_key="moderation.actions.apply.warn",
    ):
        return []

    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild_id)
    except Exception:
        return []

    return rule_choices(rules, current)


@warn.autocomplete("case")
async def warn_case_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    if not await has_bot_permission(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        permission_key="moderation.actions.apply.warn",
    ):
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

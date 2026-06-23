import discord
from discord import app_commands

from src.db.database import get_async_session
from src.db.models import ActionType
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.bot_services import (
    create_bot_moderation_action,
    fetch_active_rule_models,
    find_rule,
    rule_choices,
    rule_label,
    validate_target_for_moderation,
)


@app_commands.command(
    name="warn",
    description="Warns a user and logs the action.",
)
async def warn(
    interaction: discord.Interaction,
    user: discord.Member,
    rule: str,
    commentary: str | None = None,
):
    """Handles /warn: select a declared server rule, add optional commentary, and log action."""
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)

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
            await create_bot_moderation_action(
                session=session,
                interaction=interaction,
                user=user,
                action_type=ActionType.WARN,
                rule_id=selected_rule.id,
                commentary=commentary_text,
                reason=None,
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

    await interaction.followup.send(
        tr(locale, "warn.success", mention=user.mention, rule=selected_rule_label),
        ephemeral=False,
    )


@warn.autocomplete("rule")
async def warn_rule_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []

    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild_id)
    except Exception:
        return []

    return rule_choices(rules, current)

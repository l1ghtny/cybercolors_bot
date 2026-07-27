from __future__ import annotations

import logging

import discord
from discord import app_commands

from src.modules.localization.service import get_server_locale, tr


def _permission_names(permissions: list[str]) -> str:
    return ", ".join(permission.replace("_", " ") for permission in permissions)


def _user_message(error: app_commands.AppCommandError, locale: str | None) -> str:
    if isinstance(error, app_commands.MissingPermissions):
        return tr(
            locale,
            "command.error_user_permissions",
            permissions=_permission_names(error.missing_permissions),
        )
    if isinstance(error, app_commands.BotMissingPermissions):
        return tr(
            locale,
            "command.error_bot_permissions",
            permissions=_permission_names(error.missing_permissions),
        )
    if isinstance(error, app_commands.CommandOnCooldown):
        return tr(locale, "command.error_cooldown", retry_after=error.retry_after)
    if isinstance(error, app_commands.CommandSignatureMismatch):
        return tr(locale, "command.error_signature")
    if isinstance(error, app_commands.TransformerError):
        return tr(locale, "command.error_transform")
    if isinstance(error, app_commands.CheckFailure):
        return tr(locale, "command.error_check")
    return tr(locale, "command.error_unexpected")


async def _interaction_locale(interaction: discord.Interaction, logger: logging.Logger) -> str | None:
    if interaction.guild_id is not None:
        try:
            return await get_server_locale(interaction.guild_id)
        except Exception:
            logger.warning(
                "Failed to resolve guild locale for Discord command error",
                extra={"guild_id": interaction.guild_id, "interaction_id": interaction.id},
                exc_info=True,
            )

    interaction_locale = getattr(interaction, "locale", None)
    locale_value = getattr(interaction_locale, "value", interaction_locale)
    if locale_value:
        return str(locale_value).split("-")[0].lower()
    return None


async def handle_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
    *,
    logger: logging.Logger,
) -> None:
    command_name = interaction.command.qualified_name if interaction.command else "<unknown>"
    if isinstance(error, app_commands.CommandInvokeError):
        logged_error = error.original
    else:
        logged_error = error

    log_context = {
        "command": command_name,
        "guild_id": interaction.guild_id,
        "user_id": interaction.user.id,
        "interaction_id": interaction.id,
    }
    if isinstance(error, app_commands.CheckFailure):
        logger.warning("Discord app command check failed: %s", log_context, exc_info=logged_error)
    else:
        logger.error("Discord app command failed: %s", log_context, exc_info=logged_error)

    locale = await _interaction_locale(interaction, logger)
    message = _user_message(error, locale)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        logger.exception("Failed to send Discord app command error response: %s", log_context)

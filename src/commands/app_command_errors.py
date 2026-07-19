from __future__ import annotations

import logging

import discord
from discord import app_commands


def _permission_names(permissions: list[str]) -> str:
    return ", ".join(permission.replace("_", " ") for permission in permissions)


def _user_message(error: app_commands.AppCommandError) -> str:
    if isinstance(error, app_commands.MissingPermissions):
        return (
            "You need the following Discord permission(s) to use this command: "
            f"`{_permission_names(error.missing_permissions)}`."
        )
    if isinstance(error, app_commands.BotMissingPermissions):
        return (
            "I need the following Discord permission(s) to run this command: "
            f"`{_permission_names(error.missing_permissions)}`."
        )
    if isinstance(error, app_commands.CommandOnCooldown):
        return f"This command is on cooldown. Try again in {error.retry_after:.1f} seconds."
    if isinstance(error, app_commands.CheckFailure):
        return "You cannot use this command in the current context."
    return "This command failed unexpectedly. The error has been logged."


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

    message = _user_message(error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        logger.exception("Failed to send Discord app command error response: %s", log_context)

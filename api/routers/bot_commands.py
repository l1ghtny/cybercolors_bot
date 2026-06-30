from fastapi import APIRouter, HTTPException, Query, status

from api.models.bot_commands import BotCommandDocModel, BotCommandDocsResponseModel
from api.services.bot_command_catalog import (
    AVAILABLE_BOT_COMMAND_LOCALES,
    get_bot_command,
    list_bot_commands,
    normalize_bot_command_locale,
)


bot_commands = APIRouter(prefix="/bot-commands", tags=["bot-commands"])


@bot_commands.get("", response_model=BotCommandDocsResponseModel)
async def get_bot_commands(
    category: str | None = Query(default=None),
    discord_type: str | None = Query(default=None),
    locale: str = Query(default="en"),
):
    resolved_locale = normalize_bot_command_locale(locale)
    return BotCommandDocsResponseModel(
        version="2026-06-30",
        locale=resolved_locale,
        available_locales=list(AVAILABLE_BOT_COMMAND_LOCALES),
        commands=list_bot_commands(category=category, discord_type=discord_type, locale=resolved_locale),
    )


@bot_commands.get("/{command_id}", response_model=BotCommandDocModel)
async def get_bot_command_details(command_id: str, locale: str = Query(default="en")):
    command = get_bot_command(command_id, locale=normalize_bot_command_locale(locale))
    if command is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot command not found")
    return command

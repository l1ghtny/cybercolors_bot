import discord
from fastapi import HTTPException, status

from api.services.rbac_service import assert_user_has_permission
from src.db.database import get_async_session
from src.modules.localization.service import get_server_locale, tr


async def _send_ephemeral(interaction: discord.Interaction, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


async def has_bot_permission(
    *,
    guild_id: int,
    user_id: int,
    permission_key: str,
) -> bool:
    try:
        async with get_async_session() as session:
            await assert_user_has_permission(
                session=session,
                server_id=guild_id,
                user_id=user_id,
                permission_key=permission_key,
            )
    except HTTPException as error:
        return False
    return True


async def ensure_bot_permission(
    interaction: discord.Interaction,
    permission_key: str,
    *,
    locale: str | None = None,
) -> bool:
    if interaction.guild is None:
        await _send_ephemeral(interaction, tr(None, "common.server_only"))
        return False

    resolved_locale = locale or await get_server_locale(interaction.guild.id)
    try:
        async with get_async_session() as session:
            await assert_user_has_permission(
                session=session,
                server_id=interaction.guild.id,
                user_id=interaction.user.id,
                permission_key=permission_key,
            )
    except HTTPException as error:
        if error.status_code == status.HTTP_403_FORBIDDEN:
            await _send_ephemeral(
                interaction,
                tr(resolved_locale, "rbac.command_denied", permission=permission_key),
            )
            return False
        await _send_ephemeral(
            interaction,
            tr(resolved_locale, "rbac.check_failed", error=error.detail),
        )
        return False

    return True

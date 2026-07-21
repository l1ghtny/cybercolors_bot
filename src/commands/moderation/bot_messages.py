import discord
from discord import app_commands
from fastapi import HTTPException, status

from api.models.bot_messages import BotMessageCreateModel
from api.services.bot_messages import send_bot_message
from src.db.database import get_async_session
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.bot_rbac import ensure_bot_permission


SEND_AS_BOT_PERMISSION = "communications.send_as_bot"


async def _send_ephemeral(interaction: discord.Interaction, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


def _has_discord_moderator_permission(interaction: discord.Interaction) -> bool:
    return isinstance(interaction.user, discord.Member) and (
        interaction.user.guild_permissions.administrator
        or interaction.user.guild_permissions.moderate_members
    )


class ReplyAsBotModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        server_id: int,
        channel_id: int,
        message_id: int,
        requesting_user_id: int,
        locale: str,
    ):
        super().__init__(title=tr(locale, "bot_message.modal_title"), timeout=300)
        self.server_id = server_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.requesting_user_id = requesting_user_id
        self.locale = locale
        self.content_input = discord.ui.TextInput(
            label=tr(locale, "bot_message.content_label"),
            placeholder=tr(locale, "bot_message.content_placeholder"),
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=2000,
            required=True,
        )
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.requesting_user_id:
            await _send_ephemeral(interaction, tr(self.locale, "bot_message.owner_only"))
            return
        if interaction.guild is None or interaction.guild.id != self.server_id:
            await _send_ephemeral(interaction, tr(self.locale, "common.server_only"))
            return
        if not _has_discord_moderator_permission(interaction):
            await _send_ephemeral(interaction, tr(self.locale, "bot_message.discord_permission"))
            return
        if not await ensure_bot_permission(
            interaction,
            SEND_AS_BOT_PERMISSION,
            locale=self.locale,
        ):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            async with get_async_session() as session:
                result = await send_bot_message(
                    session,
                    server_id=self.server_id,
                    actor_user_id=interaction.user.id,
                    body=BotMessageCreateModel(
                        channel_id=str(self.channel_id),
                        content=str(self.content_input.value),
                        reply_to_message_id=str(self.message_id),
                    ),
                    source="discord_context",
                )
        except HTTPException as error:
            key = (
                "bot_message.paused"
                if error.status_code == status.HTTP_423_LOCKED
                else "bot_message.failed"
            )
            await interaction.followup.send(
                tr(self.locale, key, error=error.detail),
                ephemeral=True,
            )
            return
        except Exception as error:
            await interaction.followup.send(
                tr(self.locale, "bot_message.failed", error=error),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            tr(self.locale, "bot_message.success", message_url=result.jump_url),
            ephemeral=True,
        )


async def reply_as_bot_context(
    interaction: discord.Interaction,
    message: discord.Message,
) -> None:
    if interaction.guild is None:
        await _send_ephemeral(interaction, tr(None, "common.server_only"))
        return
    locale = await get_server_locale(interaction.guild.id)
    if not _has_discord_moderator_permission(interaction):
        await _send_ephemeral(interaction, tr(locale, "bot_message.discord_permission"))
        return
    if not await ensure_bot_permission(
        interaction,
        SEND_AS_BOT_PERMISSION,
        locale=locale,
    ):
        return
    await interaction.response.send_modal(
        ReplyAsBotModal(
            server_id=interaction.guild.id,
            channel_id=message.channel.id,
            message_id=message.id,
            requesting_user_id=interaction.user.id,
            locale=locale,
        )
    )


reply_as_bot_ctx = app_commands.ContextMenu(
    name="Reply as Modral",
    callback=reply_as_bot_context,
)
reply_as_bot_ctx.default_permissions = discord.Permissions(moderate_members=True)
reply_as_bot_ctx.guild_only = True

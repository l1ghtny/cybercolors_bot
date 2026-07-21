import os

import discord
from discord import app_commands
from fastapi import HTTPException, status

from api.models.bot_messages import BotMessageCreateModel
from api.services.bot_messages import send_bot_message
from src.db.database import get_async_session
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.bot_rbac import ensure_bot_permission


SEND_AS_BOT_PERMISSION = "communications.send_as_bot"
DEFAULT_BOT_NAME = "Modral"
CYBERCOLORS_BOT_NAME = "CyberColors"
CYBERCOLORS_REPLY_TRANSLATIONS = {
    discord.Locale.american_english.value: "Reply as CyberColors",
    discord.Locale.british_english.value: "Reply as CyberColors",
    discord.Locale.russian.value: "Ответить от имени CyberColors",
}


def bot_display_name(server_id: int) -> str:
    branded_guild_id = os.getenv("TEST_GUILD_ID", "").strip()
    if branded_guild_id and str(server_id) == branded_guild_id:
        return CYBERCOLORS_BOT_NAME
    return DEFAULT_BOT_NAME


class StaticCommandTranslator(app_commands.Translator):
    async def translate(self, string, locale, context):
        translations = string.extras.get("translations")
        if not isinstance(translations, dict):
            return None
        translation = translations.get(locale.value)
        return translation if isinstance(translation, str) else None


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
        bot_name: str,
    ):
        super().__init__(
            title=tr(locale, "bot_message.modal_title", bot_name=bot_name),
            timeout=300,
        )
        self.server_id = server_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.requesting_user_id = requesting_user_id
        self.locale = locale
        self.bot_name = bot_name
        self.content_input = discord.ui.TextInput(
            placeholder=tr(
                locale,
                "bot_message.content_placeholder",
                bot_name=bot_name,
            ),
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=2000,
            required=True,
        )
        self.add_item(
            discord.ui.Label(
                text=tr(locale, "bot_message.content_label"),
                component=self.content_input,
            )
        )
        self.notify_replied_user_input = discord.ui.Checkbox(
            custom_id="notify_replied_user",
            default=False,
        )
        self.add_item(
            discord.ui.Label(
                text=tr(locale, "bot_message.notify_author_label"),
                description=tr(locale, "bot_message.notify_author_description"),
                component=self.notify_replied_user_input,
            )
        )

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
                        notify_replied_user=self.notify_replied_user_input.value,
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
            tr(
                self.locale,
                "bot_message.success",
                bot_name=self.bot_name,
                message_url=result.jump_url,
            ),
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
            bot_name=bot_display_name(interaction.guild.id),
        )
    )


reply_as_bot_ctx = app_commands.ContextMenu(
    name="Reply as Modral",
    callback=reply_as_bot_context,
)
reply_as_bot_ctx.default_permissions = discord.Permissions(moderate_members=True)
reply_as_bot_ctx.guild_only = True

reply_as_cybercolors_ctx = app_commands.ContextMenu(
    # The raw name intentionally matches the global command. Discord lets a
    # guild command with the same name and type override the global command,
    # while localized clients display the CyberColors-specific label.
    name=app_commands.locale_str(
        "Reply as Modral",
        translations=CYBERCOLORS_REPLY_TRANSLATIONS,
    ),
    callback=reply_as_bot_context,
)
reply_as_cybercolors_ctx.default_permissions = discord.Permissions(moderate_members=True)
reply_as_cybercolors_ctx.guild_only = True

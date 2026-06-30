import re

import discord
from discord import app_commands

from api.models.moderation_rules import ModerationRuleMessageRefModel
from api.services.moderation_rules_service import (
    create_manual_rule,
    get_rule_parse_guide,
    import_rules_from_message,
    import_rules_from_messages,
)
from src.db.database import get_async_session
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.bot_rbac import ensure_bot_permission
from src.modules.moderation.bot_services import fetch_active_rule_models, rule_label


MESSAGE_LINK_RE = re.compile(
    r"^https?://(?:canary\.|ptb\.)?discord\.com/channels/(?P<guild_id>\d+)/(?P<channel_id>\d+)/(?P<message_id>\d+)$"
)


async def _refresh_rules_cache(interaction: discord.Interaction):
    client = interaction.client
    if hasattr(client, "load_current_server_rules"):
        await client.load_current_server_rules()


def _error_text(error: Exception) -> str:
    detail = getattr(error, "detail", None)
    return str(detail if detail is not None else error)


async def _import_rules_from_message(
    interaction: discord.Interaction,
    channel_id: int,
    message_id: int,
    replace_existing: bool,
    locale: str,
):
    try:
        async with get_async_session() as session:
            imported = await import_rules_from_message(
                session=session,
                server_id=interaction.guild.id,
                channel_id=channel_id,
                message_id=message_id,
                created_by_user_id=interaction.user.id,
                replace_existing=replace_existing,
            )
            imported_count = len(imported)
            await session.commit()

        await _refresh_rules_cache(interaction)
        await interaction.followup.send(
            tr(locale, "rules.import_message_success", imported_count=imported_count, message_id=message_id),
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(
            tr(locale, "rules.import_failed_generic", error=_error_text(error)),
            ephemeral=True,
        )


async def _import_rules_from_messages(
    interaction: discord.Interaction,
    messages: list[dict[str, str]],
    replace_existing: bool,
    locale: str,
):
    try:
        refs = [ModerationRuleMessageRefModel(**message) for message in messages]
        async with get_async_session() as session:
            imported = await import_rules_from_messages(
                session=session,
                server_id=interaction.guild.id,
                message_refs=refs,
                created_by_user_id=interaction.user.id,
                replace_existing=replace_existing,
            )
            imported_count = len(imported)
            await session.commit()

        await _refresh_rules_cache(interaction)
        await interaction.followup.send(
            tr(
                locale,
                "rules.import_messages_success",
                imported_count=imported_count,
                message_count=len(messages),
            ),
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(tr(locale, "rules.import_failed_generic", error=_error_text(error)), ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="rules_import_message",
    description="Import moderation rules from a Discord message link.",
)
async def rules_import_message(interaction: discord.Interaction, message_link: str, replace_existing: bool = True):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.rules.manage", locale=locale):
        return

    match = MESSAGE_LINK_RE.match(message_link.strip())
    if not match:
        await interaction.followup.send(tr(locale, "rules.invalid_message_link"), ephemeral=True)
        return

    guild_id = int(match.group("guild_id"))
    channel_id = int(match.group("channel_id"))
    message_id = int(match.group("message_id"))
    if guild_id != interaction.guild.id:
        await interaction.followup.send(tr(locale, "rules.message_other_server"), ephemeral=True)
        return

    await _import_rules_from_message(
        interaction=interaction,
        channel_id=channel_id,
        message_id=message_id,
        replace_existing=replace_existing,
        locale=locale,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="rules_import_messages",
    description="Import moderation rules from multiple Discord message links (space/newline separated).",
)
async def rules_import_messages(
    interaction: discord.Interaction,
    message_links: str,
    replace_existing: bool = True,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.rules.manage", locale=locale):
        return

    links_raw = re.split(r"[\s,]+", message_links.strip())
    links = [item for item in links_raw if item]
    if not links:
        await interaction.followup.send(tr(locale, "rules.links_required"), ephemeral=True)
        return
    if len(links) > 25:
        await interaction.followup.send(tr(locale, "rules.too_many_links"), ephemeral=True)
        return

    parsed_messages: list[dict[str, str]] = []
    for link in links:
        match = MESSAGE_LINK_RE.match(link)
        if not match:
            await interaction.followup.send(tr(locale, "rules.invalid_message_link_item", link=link), ephemeral=True)
            return

        guild_id = int(match.group("guild_id"))
        if guild_id != interaction.guild.id:
            await interaction.followup.send(tr(locale, "rules.other_server_link_item", link=link), ephemeral=True)
            return

        parsed_messages.append(
            {
                "channel_id": match.group("channel_id"),
                "message_id": match.group("message_id"),
            }
        )

    await _import_rules_from_messages(
        interaction=interaction,
        messages=parsed_messages,
        replace_existing=replace_existing,
        locale=locale,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="rule_add",
    description="Add one moderation rule manually.",
)
async def rule_add(
    interaction: discord.Interaction,
    title: str,
    description: str | None = None,
    code: str | None = None,
    sort_order: app_commands.Range[int, 0, 999] = 0,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.rules.manage", locale=locale):
        return

    try:
        async with get_async_session() as session:
            rule = await create_manual_rule(
                session=session,
                server_id=interaction.guild.id,
                title=title,
                description=description,
                code=code,
                sort_order=sort_order,
                created_by_user_id=interaction.user.id,
            )
            label = f"{rule.code or ''} {rule.title or ''}".strip()
            await session.commit()

        await _refresh_rules_cache(interaction)
        await interaction.followup.send(tr(locale, "rules.rule_added", label=label), ephemeral=True)
    except Exception as error:
        await interaction.followup.send(tr(locale, "rules.rule_add_failed_generic", error=_error_text(error)), ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="rules_list",
    description="Show active moderation rules configured for this server.",
)
async def rules_list(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.rules.view", locale=locale):
        return

    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild.id)

        if not rules:
            await interaction.followup.send(tr(locale, "rules.none_configured"), ephemeral=True)
            return

        body = "\n".join(f"- {rule_label(item)}" for item in rules)
        if len(body) > 1900:
            body = body[:1890] + "\n..."
        await interaction.followup.send(tr(locale, "rules.active_header", body=body), ephemeral=True)
    except Exception as error:
        await interaction.followup.send(tr(locale, "rules.fetch_failed_generic", error=_error_text(error)), ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="rules_parse_guide",
    description="Show formatting guide for parseable moderation rules.",
)
async def rules_parse_guide(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.rules.view", locale=locale):
        return

    try:
        guide = get_rule_parse_guide(locale=locale)
    except Exception as error:
        await interaction.followup.send(tr(locale, "rules.guide_fetch_failed", error=_error_text(error)), ephemeral=True)
        return

    lines = [f"- {item}" for item in guide.guidance]
    text = "\n".join(lines)
    if guide.example:
        text += f"\n\n{tr(locale, 'rules.guide_example')}\n```text\n{guide.example}\n```"
    await interaction.followup.send(text or tr(locale, "rules.guide_empty"), ephemeral=True)


async def import_rules_from_message_context(interaction: discord.Interaction, message: discord.Message):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_guild:
        locale = await get_server_locale(interaction.guild.id)
        await interaction.response.send_message(tr(locale, "rules.manage_server_required"), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.rules.manage", locale=locale):
        return
    await _import_rules_from_message(
        interaction=interaction,
        channel_id=message.channel.id,
        message_id=message.id,
        replace_existing=False,
        locale=locale,
    )


rules_import_from_message_ctx = app_commands.ContextMenu(
    name="Import Rules From Message",
    callback=import_rules_from_message_context,
)
rules_import_from_message_ctx.default_permissions = discord.Permissions(manage_guild=True)
rules_import_from_message_ctx.guild_only = True

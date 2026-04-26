import os
import re

import discord
from discord import app_commands
import httpx

from src.modules.localization.service import get_server_locale, tr


MESSAGE_LINK_RE = re.compile(
    r"^https?://(?:canary\.|ptb\.)?discord\.com/channels/(?P<guild_id>\d+)/(?P<channel_id>\d+)/(?P<message_id>\d+)$"
)


def _bot_api_url() -> str:
    return os.getenv("BOT_API_URL", "").rstrip("/")


async def _refresh_rules_cache(interaction: discord.Interaction):
    client = interaction.client
    if hasattr(client, "load_current_server_rules"):
        await client.load_current_server_rules()


async def _import_rules_from_message(
    interaction: discord.Interaction,
    channel_id: int,
    message_id: int,
    replace_existing: bool,
    locale: str,
):
    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send(tr(locale, "common.api_missing"), ephemeral=True)
        return

    payload = {
        "channel_id": str(channel_id),
        "message_id": str(message_id),
        "replace_existing": replace_existing,
        "created_by_user_id": str(interaction.user.id),
    }
    api_url = f"{base_url}/moderation/rules/{interaction.guild.id}/import-message"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()
            data = response.json()

        imported_count = len(data.get("imported", [])) if isinstance(data, dict) else 0
        await _refresh_rules_cache(interaction)
        await interaction.followup.send(
            tr(locale, "rules.import_message_success", imported_count=imported_count, message_id=message_id),
            ephemeral=True,
        )
    except httpx.HTTPStatusError as error:
        await interaction.followup.send(
            tr(
                locale,
                "rules.import_failed_http",
                status=error.response.status_code,
                text=error.response.text,
            ),
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(
            tr(locale, "rules.import_failed_generic", error=error),
            ephemeral=True,
        )


async def _import_rules_from_messages(
    interaction: discord.Interaction,
    messages: list[dict[str, str]],
    replace_existing: bool,
    locale: str,
):
    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send(tr(locale, "common.api_missing"), ephemeral=True)
        return

    payload = {
        "messages": messages,
        "replace_existing": replace_existing,
        "created_by_user_id": str(interaction.user.id),
    }
    api_url = f"{base_url}/moderation/rules/{interaction.guild.id}/import-messages"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()
            data = response.json()

        imported_count = len(data.get("imported", [])) if isinstance(data, dict) else 0
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
    except httpx.HTTPStatusError as error:
        await interaction.followup.send(
            tr(
                locale,
                "rules.import_failed_http",
                status=error.response.status_code,
                text=error.response.text,
            ),
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(tr(locale, "rules.import_failed_generic", error=error), ephemeral=True)


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

    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send(tr(locale, "common.api_missing"), ephemeral=True)
        return

    api_url = f"{base_url}/moderation/rules/{interaction.guild.id}"
    payload = {
        "code": code,
        "title": title,
        "description": description,
        "sort_order": sort_order,
        "created_by_user_id": str(interaction.user.id),
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()
            rule = response.json()

        await _refresh_rules_cache(interaction)
        label = f"{rule.get('code', '')} {rule.get('title', '')}".strip()
        await interaction.followup.send(tr(locale, "rules.rule_added", label=label), ephemeral=True)
    except httpx.HTTPStatusError as error:
        await interaction.followup.send(
            tr(
                locale,
                "rules.rule_add_failed_http",
                status=error.response.status_code,
                text=error.response.text,
            ),
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(tr(locale, "rules.rule_add_failed_generic", error=error), ephemeral=True)


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

    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send(tr(locale, "common.api_missing"), ephemeral=True)
        return

    api_url = f"{base_url}/moderation/rules/{interaction.guild.id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url)
            response.raise_for_status()
            rules = response.json()

        if not isinstance(rules, list) or not rules:
            await interaction.followup.send(tr(locale, "rules.none_configured"), ephemeral=True)
            return

        lines: list[str] = []
        for item in rules:
            code = (item.get("code") or "").strip()
            title = (item.get("title") or "").strip()
            label = f"{code} {title}".strip()
            lines.append(f"- {label}")
        body = "\n".join(lines)
        if len(body) > 1900:
            body = body[:1890] + "\n..."
        await interaction.followup.send(tr(locale, "rules.active_header", body=body), ephemeral=True)
    except httpx.HTTPStatusError as error:
        await interaction.followup.send(
            tr(
                locale,
                "rules.fetch_failed_http",
                status=error.response.status_code,
                text=error.response.text,
            ),
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(tr(locale, "rules.fetch_failed_generic", error=error), ephemeral=True)


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

    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send(tr(locale, "common.api_missing"), ephemeral=True)
        return

    api_url = f"{base_url}/moderation/rules/{interaction.guild.id}/parse-guide"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, params={"locale": locale})
            response.raise_for_status()
            guide = response.json()
    except Exception as error:
        await interaction.followup.send(tr(locale, "rules.guide_fetch_failed", error=error), ephemeral=True)
        return

    guidance = guide.get("guidance", []) if isinstance(guide, dict) else []
    example = guide.get("example", "") if isinstance(guide, dict) else ""
    lines = [f"- {item}" for item in guidance]
    text = "\n".join(lines)
    if example:
        text += f"\n\n{tr(locale, 'rules.guide_example')}\n```text\n{example}\n```"
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

import os
import re

import discord
from discord import app_commands
import httpx


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
):
    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send("BOT_API_URL is not configured.", ephemeral=True)
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
            f"Imported `{imported_count}` moderation rules from message `{message_id}`.",
            ephemeral=True,
        )
    except httpx.HTTPStatusError as error:
        await interaction.followup.send(
            f"Import failed: {error.response.status_code} - {error.response.text}",
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(
            f"Import failed: {error}",
            ephemeral=True,
        )


async def _import_rules_from_messages(
    interaction: discord.Interaction,
    messages: list[dict[str, str]],
    replace_existing: bool,
):
    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send("BOT_API_URL is not configured.", ephemeral=True)
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
            f"Imported `{imported_count}` moderation rules from `{len(messages)}` messages.",
            ephemeral=True,
        )
    except httpx.HTTPStatusError as error:
        await interaction.followup.send(
            f"Import failed: {error.response.status_code} - {error.response.text}",
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(f"Import failed: {error}", ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="rules_import_message",
    description="Import moderation rules from a Discord message link.",
)
async def rules_import_message(interaction: discord.Interaction, message_link: str, replace_existing: bool = True):
    await interaction.response.defer(ephemeral=True)
    if interaction.guild is None:
        await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
        return

    match = MESSAGE_LINK_RE.match(message_link.strip())
    if not match:
        await interaction.followup.send("Invalid Discord message link format.", ephemeral=True)
        return

    guild_id = int(match.group("guild_id"))
    channel_id = int(match.group("channel_id"))
    message_id = int(match.group("message_id"))
    if guild_id != interaction.guild.id:
        await interaction.followup.send("That message is not from this server.", ephemeral=True)
        return

    await _import_rules_from_message(
        interaction=interaction,
        channel_id=channel_id,
        message_id=message_id,
        replace_existing=replace_existing,
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
    await interaction.response.defer(ephemeral=True)
    if interaction.guild is None:
        await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
        return

    links_raw = re.split(r"[\s,]+", message_links.strip())
    links = [item for item in links_raw if item]
    if not links:
        await interaction.followup.send("Provide at least one Discord message link.", ephemeral=True)
        return
    if len(links) > 25:
        await interaction.followup.send("Too many links. Maximum is 25 per command.", ephemeral=True)
        return

    parsed_messages: list[dict[str, str]] = []
    for link in links:
        match = MESSAGE_LINK_RE.match(link)
        if not match:
            await interaction.followup.send(f"Invalid message link: `{link}`", ephemeral=True)
            return

        guild_id = int(match.group("guild_id"))
        if guild_id != interaction.guild.id:
            await interaction.followup.send(f"Link is from another server: `{link}`", ephemeral=True)
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
    await interaction.response.defer(ephemeral=True)
    if interaction.guild is None:
        await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
        return

    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send("BOT_API_URL is not configured.", ephemeral=True)
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
        await interaction.followup.send(f"Rule added: `{label}`", ephemeral=True)
    except httpx.HTTPStatusError as error:
        await interaction.followup.send(
            f"Failed to add rule: {error.response.status_code} - {error.response.text}",
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(f"Failed to add rule: {error}", ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="rules_list",
    description="Show active moderation rules configured for this server.",
)
async def rules_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if interaction.guild is None:
        await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
        return

    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send("BOT_API_URL is not configured.", ephemeral=True)
        return

    api_url = f"{base_url}/moderation/rules/{interaction.guild.id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url)
            response.raise_for_status()
            rules = response.json()

        if not isinstance(rules, list) or not rules:
            await interaction.followup.send("No active moderation rules configured.", ephemeral=True)
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
        await interaction.followup.send(f"Active moderation rules:\n{body}", ephemeral=True)
    except httpx.HTTPStatusError as error:
        await interaction.followup.send(
            f"Failed to fetch rules: {error.response.status_code} - {error.response.text}",
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(f"Failed to fetch rules: {error}", ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="rules_parse_guide",
    description="Show formatting guide for parseable moderation rules.",
)
async def rules_parse_guide(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if interaction.guild is None:
        await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
        return

    base_url = _bot_api_url()
    if not base_url:
        await interaction.followup.send("BOT_API_URL is not configured.", ephemeral=True)
        return

    api_url = f"{base_url}/moderation/rules/{interaction.guild.id}/parse-guide"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url)
            response.raise_for_status()
            guide = response.json()
    except Exception as error:
        await interaction.followup.send(f"Failed to fetch guide: {error}", ephemeral=True)
        return

    guidance = guide.get("guidance", []) if isinstance(guide, dict) else []
    example = guide.get("example", "") if isinstance(guide, dict) else ""
    lines = [f"- {item}" for item in guidance]
    text = "\n".join(lines)
    if example:
        text += f"\n\nExample:\n```text\n{example}\n```"
    await interaction.followup.send(text or "No guide available.", ephemeral=True)


async def import_rules_from_message_context(interaction: discord.Interaction, message: discord.Message):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    await _import_rules_from_message(
        interaction=interaction,
        channel_id=message.channel.id,
        message_id=message.id,
        replace_existing=False,
    )


rules_import_from_message_ctx = app_commands.ContextMenu(
    name="Import Rules From Message",
    callback=import_rules_from_message_context,
)
rules_import_from_message_ctx.default_permissions = discord.Permissions(manage_guild=True)
rules_import_from_message_ctx.guild_only = True

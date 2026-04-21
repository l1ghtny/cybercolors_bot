import os
from datetime import datetime, timezone

import discord
from discord import app_commands
import httpx


def _bot_api_url() -> str:
    return os.getenv("BOT_API_URL", "").rstrip("/")


async def _fetch_server_rules(server_id: int) -> list[dict]:
    api_url = f"{_bot_api_url()}/moderation/rules/{server_id}"
    async with httpx.AsyncClient() as client:
        response = await client.get(api_url)
        response.raise_for_status()
        payload = response.json()
    if isinstance(payload, list):
        return payload
    return []


def _find_rule(rules: list[dict], rule_id: str) -> dict | None:
    for rule in rules:
        if str(rule.get("id")) == rule_id:
            return rule
    return None


def _rule_label(rule: dict) -> str:
    code = (rule.get("code") or "").strip()
    title = (rule.get("title") or "").strip()
    if code:
        return f"{code} {title}".strip()
    return title or "Rule"


@app_commands.command(name="warn", description="Warns a user and logs the action.")
async def warn(
    interaction: discord.Interaction,
    user: discord.Member,
    rule: str,
    commentary: str | None = None,
):
    """Handles /warn: select a declared server rule, add optional commentary, and log action."""
    await interaction.response.defer(ephemeral=True)

    try:
        rules = await _fetch_server_rules(interaction.guild.id)
    except Exception as error:
        await interaction.followup.send(
            f"Could not fetch moderation rules from API: {error}",
            ephemeral=True,
        )
        return

    selected_rule = _find_rule(rules, rule)
    if not selected_rule:
        await interaction.followup.send(
            "Selected rule is invalid or no longer active. Please choose from autocomplete suggestions.",
            ephemeral=True,
        )
        return

    selected_rule_label = _rule_label(selected_rule)
    commentary_text = commentary.strip() if commentary else None

    # 1. Perform Discord-specific actions
    try:
        dm_message = (
            f"You have been warned in **{interaction.guild.name}** for the following rule:\n"
            f"> {selected_rule_label}"
        )
        if commentary_text:
            dm_message += f"\n\nModerator commentary:\n> {commentary_text}"
        await user.send(dm_message)
    except discord.Forbidden:
        await interaction.followup.send(
            "Could not send a DM to the user, but the warning will still be logged.",
            ephemeral=True,
        )

    # 2. Prepare data for the API POST request
    api_url = f"{_bot_api_url()}/moderation/create_action"
    payload = {
        "action_type": "warn",
        "moderator_user_id": interaction.user.id,
        "rule_id": rule,
        "commentary": commentary_text,
        "reason": None,
        "target_user_id": user.id,
        "target_user_name": user.name,
        "target_user_joined_at": (
            user.joined_at.isoformat()
            if user.joined_at is not None
            else datetime.now(timezone.utc).isoformat()
        ),
        "target_user_server_nickname": user.nick,
        "server_id": interaction.guild.id,
        "server_name": interaction.guild.name,
    }

    # 3. Make the POST request to the internal API
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()
        await interaction.followup.send(
            f"Successfully warned {user.mention} for `{selected_rule_label}` and logged the action.",
            ephemeral=False,
        )
    except httpx.RequestError as error:
        await interaction.followup.send(
            f"An error occurred while communicating with the API: {error}",
            ephemeral=True,
        )
    except httpx.HTTPStatusError as error:
        await interaction.followup.send(
            f"The API responded with an error: {error.response.status_code} - {error.response.text}",
            ephemeral=True,
        )


@warn.autocomplete("rule")
async def warn_rule_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []

    try:
        rules = await _fetch_server_rules(interaction.guild_id)
    except Exception:
        return []

    current_lower = current.lower().strip()
    choices: list[app_commands.Choice[str]] = []
    for item in rules:
        label = _rule_label(item)
        if current_lower and current_lower not in label.lower():
            continue
        display_name = label if len(label) <= 100 else f"{label[:97]}..."
        choices.append(app_commands.Choice(name=display_name, value=str(item.get("id"))))
        if len(choices) >= 25:
            break
    return choices

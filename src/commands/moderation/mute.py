import os
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
import httpx

from src.db.database import get_async_session
from src.modules.moderation.mute_management import (
    deactivate_user_mutes,
    get_or_create_moderation_settings,
    try_reconnect_voice_member,
)
from src.modules.moderation.mod_log import build_unmute_log_message, send_mod_log_message


def _bot_api_url() -> str:
    return os.getenv("BOT_API_URL", "").rstrip("/")


async def _fetch_server_rules(server_id: int) -> list[dict]:
    base_url = _bot_api_url()
    if not base_url:
        raise RuntimeError("BOT_API_URL is not configured")
    api_url = f"{base_url}/moderation/rules/{server_id}"
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


def _validate_target_for_moderation(
    interaction: discord.Interaction,
    target: discord.Member,
) -> str | None:
    guild = interaction.guild
    if guild is None:
        return "This command can only be used in a server."
    if target.id == interaction.user.id:
        return "You cannot use this command on yourself."
    if target.id == guild.owner_id:
        return "You cannot moderate the server owner."

    actor = interaction.user if isinstance(interaction.user, discord.Member) else None
    if actor and guild.owner_id != actor.id and target.top_role >= actor.top_role:
        return "You cannot moderate a member with equal or higher role."

    me = guild.me
    if me and target.top_role >= me.top_role:
        return "I cannot moderate this member due to role hierarchy."
    return None


async def _log_moderation_action(
    interaction: discord.Interaction,
    user: discord.Member,
    action_type: str,
    rule_id: str | None,
    commentary: str | None,
    reason: str | None,
    expires_at: datetime | None = None,
):
    base_url = _bot_api_url()
    if not base_url:
        raise RuntimeError("BOT_API_URL is not configured")

    payload = {
        "action_type": action_type,
        "moderator_user_id": interaction.user.id,
        "rule_id": rule_id,
        "commentary": commentary,
        "reason": reason,
        "expires_at": expires_at.isoformat() if expires_at else None,
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

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{base_url}/moderation/create_action", json=payload)
        response.raise_for_status()


async def _apply_mute_overwrites(guild: discord.Guild, role: discord.Role) -> tuple[int, int]:
    edited = 0
    failed = 0
    supported_types = (
        discord.TextChannel,
        discord.VoiceChannel,
        discord.StageChannel,
        discord.ForumChannel,
        discord.CategoryChannel,
    )
    for channel in guild.channels:
        if not isinstance(channel, supported_types):
            continue
        try:
            overwrite = channel.overwrites_for(role)
            overwrite.send_messages = False
            overwrite.add_reactions = False
            overwrite.send_messages_in_threads = False
            overwrite.create_public_threads = False
            overwrite.create_private_threads = False
            overwrite.speak = False
            overwrite.stream = False
            await channel.set_permissions(role, overwrite=overwrite, reason="Configure mute role defaults")
            edited += 1
        except Exception:
            failed += 1
    return edited, failed


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="moderation_settings",
    description="Show moderation settings for this server.",
)
async def moderation_settings(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with get_async_session() as session:
        settings = await get_or_create_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            server_name=interaction.guild.name,
        )
        mute_role = interaction.guild.get_role(settings.mute_role_id) if settings.mute_role_id else None
        mute_role_name = mute_role.name if mute_role else "Not configured"
        mod_log_channel = (
            interaction.guild.get_channel(settings.mod_log_channel_id)
            if settings.mod_log_channel_id
            else None
        )
        mod_log_channel_label = (
            f"{mod_log_channel.mention} (`{settings.mod_log_channel_id}`)"
            if mod_log_channel is not None
            else (
                f"`{settings.mod_log_channel_id}` (not found)"
                if settings.mod_log_channel_id
                else "Not configured"
            )
        )
        await session.commit()

    await interaction.followup.send(
        "Moderation settings:\n"
        f"- Mute role: `{mute_role_name}`\n"
        f"- Mod log channel: {mod_log_channel_label}\n"
        f"- Default mute minutes: `{settings.default_mute_minutes}`\n"
        f"- Max mute minutes: `{settings.max_mute_minutes}`\n"
        f"- Voice reconnect on mute: `{settings.auto_reconnect_voice_on_mute}`",
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="moderation_set_mute_role",
    description="Set the existing role to use for mutes.",
)
async def moderation_set_mute_role(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    async with get_async_session() as session:
        settings = await get_or_create_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            server_name=interaction.guild.name,
        )
        settings.mute_role_id = role.id
        settings.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(settings)
        await session.commit()

    await interaction.followup.send(f'Mute role set to `{role.name}`.', ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="moderation_set_log_channel",
    description="Set the moderation log channel.",
)
async def moderation_set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    async with get_async_session() as session:
        settings = await get_or_create_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            server_name=interaction.guild.name,
        )
        settings.mod_log_channel_id = channel.id
        settings.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(settings)
        await session.commit()
    await interaction.followup.send(f"Moderation log channel set to {channel.mention}.", ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="moderation_clear_log_channel",
    description="Clear moderation log channel setting.",
)
async def moderation_clear_log_channel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with get_async_session() as session:
        settings = await get_or_create_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            server_name=interaction.guild.name,
        )
        settings.mod_log_channel_id = None
        settings.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(settings)
        await session.commit()
    await interaction.followup.send("Moderation log channel cleared.", ephemeral=True)


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="moderation_create_mute_role",
    description="Create a new mute role and attach it to moderation settings.",
)
async def moderation_create_mute_role(interaction: discord.Interaction, role_name: str = "Muted"):
    await interaction.response.defer(ephemeral=True)
    role = await interaction.guild.create_role(
        name=role_name,
        permissions=discord.Permissions.none(),
        reason=f"Created by {interaction.user} for moderation mute workflow",
    )
    edited, failed = await _apply_mute_overwrites(interaction.guild, role)

    async with get_async_session() as session:
        settings = await get_or_create_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            server_name=interaction.guild.name,
        )
        settings.mute_role_id = role.id
        settings.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(settings)
        await session.commit()

    await interaction.followup.send(
        f'Created mute role `{role.name}` and updated `{edited}` channel overwrites'
        f' (failed: {failed}).',
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="moderation_set_mute_defaults",
    description="Set default and maximum mute durations.",
)
async def moderation_set_mute_defaults(
    interaction: discord.Interaction,
    default_minutes: app_commands.Range[int, 1, 43200],
    max_minutes: app_commands.Range[int, 1, 43200] = 10080,
    auto_reconnect_on_mute: bool = True,
):
    await interaction.response.defer(ephemeral=True)
    if default_minutes > max_minutes:
        await interaction.followup.send("Default minutes cannot be greater than max minutes.", ephemeral=True)
        return

    async with get_async_session() as session:
        settings = await get_or_create_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            server_name=interaction.guild.name,
        )
        settings.default_mute_minutes = default_minutes
        settings.max_mute_minutes = max_minutes
        settings.auto_reconnect_voice_on_mute = auto_reconnect_on_mute
        settings.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(settings)
        await session.commit()

    await interaction.followup.send(
        f"Mute defaults updated: default={default_minutes}m, max={max_minutes}m, "
        f"auto_reconnect={auto_reconnect_on_mute}.",
        ephemeral=True,
    )


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="mute", description="Apply role-based mute with rule + optional commentary.")
async def mute(
    interaction: discord.Interaction,
    user: discord.Member,
    rule: str,
    duration_minutes: app_commands.Range[int, 1, 43200] | None = None,
    commentary: str | None = None,
):
    await interaction.response.defer(ephemeral=True)

    try:
        rules = await _fetch_server_rules(interaction.guild.id)
    except Exception as error:
        await interaction.followup.send(f"Could not fetch moderation rules: {error}", ephemeral=True)
        return
    selected_rule = _find_rule(rules, rule)
    if not selected_rule:
        await interaction.followup.send("Invalid rule selected.", ephemeral=True)
        return
    selected_rule_label = _rule_label(selected_rule)

    moderation_target_error = _validate_target_for_moderation(interaction, user)
    if moderation_target_error:
        await interaction.followup.send(moderation_target_error, ephemeral=True)
        return

    async with get_async_session() as session:
        settings = await get_or_create_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            server_name=interaction.guild.name,
        )
        if not settings.mute_role_id:
            await interaction.followup.send(
                "Mute role is not configured. Use `/moderation_set_mute_role` or `/moderation_create_mute_role`.",
                ephemeral=True,
            )
            return
        mute_role = interaction.guild.get_role(settings.mute_role_id)
        if mute_role is None:
            await interaction.followup.send(
                "Configured mute role is missing on this server. Reconfigure it.",
                ephemeral=True,
            )
            return
        if interaction.guild.me and mute_role >= interaction.guild.me.top_role:
            await interaction.followup.send(
                "I cannot assign this mute role because it is above or equal to my highest role.",
                ephemeral=True,
            )
            return

        effective_duration = duration_minutes or settings.default_mute_minutes
        if effective_duration > settings.max_mute_minutes:
            await interaction.followup.send(
                f"Duration exceeds server max mute time ({settings.max_mute_minutes} minutes).",
                ephemeral=True,
            )
            return

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=effective_duration)
        await deactivate_user_mutes(session, interaction.guild.id, user.id)

        if mute_role not in user.roles:
            try:
                await user.add_roles(
                    mute_role,
                    reason=f"Muted by {interaction.user} ({interaction.user.id})",
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "I do not have permission to assign the mute role.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as error:
                await interaction.followup.send(
                    f"Failed to assign mute role: {error}",
                    ephemeral=True,
                )
                return

        reconnect_note = ""
        if settings.auto_reconnect_voice_on_mute and user.voice and user.voice.channel:
            try:
                await try_reconnect_voice_member(user, reason="Apply mute role changes")
                reconnect_note = " Voice reconnect applied."
            except Exception:
                reconnect_note = " Could not reconnect user in voice (check move permissions)."

        await session.commit()

    commentary_text = commentary.strip() if commentary else None
    try:
        await _log_moderation_action(
            interaction=interaction,
            user=user,
            action_type="mute",
            rule_id=rule,
            commentary=commentary_text,
            reason=None,
            expires_at=expires_at,
        )
    except Exception as error:
        await interaction.followup.send(
            f"User muted, but logging action failed: {error}",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"{user.mention} muted for `{effective_duration}` minutes by rule `{selected_rule_label}`."
        f"{reconnect_note}",
        ephemeral=False,
    )


@mute.autocomplete("rule")
async def mute_rule_autocomplete(interaction: discord.Interaction, current: str):
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


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="unmute", description="Remove role-based mute and close active mute actions.")
async def unmute(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str | None = None,
):
    await interaction.response.defer(ephemeral=True)
    note = reason.strip() if reason else "Manual unmute"
    moderation_target_error = _validate_target_for_moderation(interaction, user)
    if moderation_target_error:
        await interaction.followup.send(moderation_target_error, ephemeral=True)
        return

    async with get_async_session() as session:
        settings = await get_or_create_moderation_settings(
            session=session,
            server_id=interaction.guild.id,
            server_name=interaction.guild.name,
        )

        removed_role = False
        if settings.mute_role_id:
            mute_role = interaction.guild.get_role(settings.mute_role_id)
            if mute_role and mute_role in user.roles:
                try:
                    await user.remove_roles(
                        mute_role,
                        reason=f"Unmuted by {interaction.user} ({interaction.user.id}). {note}",
                    )
                except discord.Forbidden:
                    await interaction.followup.send(
                        "I do not have permission to remove the mute role.",
                        ephemeral=True,
                    )
                    return
                except discord.HTTPException as error:
                    await interaction.followup.send(
                        f"Failed to remove mute role: {error}",
                        ephemeral=True,
                    )
                    return
                removed_role = True

        deactivated = await deactivate_user_mutes(session, interaction.guild.id, user.id)
        await session.commit()

    if settings.mod_log_channel_id:
        content = build_unmute_log_message(
            target_user_id=user.id,
            target_display=user.display_name,
            moderator_user_id=interaction.user.id,
            moderator_display=interaction.user.display_name,
            reason=note,
            removed_role=removed_role,
            closed_actions=deactivated,
            is_auto=False,
        )
        await send_mod_log_message(
            guild=interaction.guild,
            mod_log_channel_id=settings.mod_log_channel_id,
            content=content,
        )

    await interaction.followup.send(
        f"{user.mention} unmuted. Removed role: `{removed_role}`. Closed active mute actions: `{deactivated}`.",
        ephemeral=False,
    )

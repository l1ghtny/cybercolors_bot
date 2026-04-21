from datetime import datetime, timezone

import discord
from discord import app_commands

from src.db.database import get_async_session
from src.db.models import Server, ServerSecuritySettings


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_or_create_security_settings(server_id: int, server_name: str) -> ServerSecuritySettings:
    async with get_async_session() as session:
        server = await session.get(Server, server_id)
        if not server:
            server = Server(server_id=server_id, server_name=server_name)
            session.add(server)
            await session.flush()

        settings = await session.get(ServerSecuritySettings, server_id)
        if settings:
            return settings

        settings = ServerSecuritySettings(server_id=server_id)
        session.add(settings)
        await session.flush()
        await session.refresh(settings)
        return settings


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="security_set_verified_role",
    description="Set the role granted to members who finished onboarding.",
)
async def security_set_verified_role(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    settings = await _get_or_create_security_settings(interaction.guild.id, interaction.guild.name)

    async with get_async_session() as session:
        settings = await session.get(ServerSecuritySettings, interaction.guild.id)
        settings.verified_role_id = role.id
        if settings.normal_permissions is None:
            settings.normal_permissions = role.permissions.value
        settings.updated_at = _utcnow_naive()
        session.add(settings)
        await session.flush()
    await interaction.followup.send(
        f'Verified role set to "{role.name}".',
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="security_capture_permissions",
    description="Capture current verified role permissions as normal or lockdown template.",
)
@app_commands.choices(
    mode=[
        app_commands.Choice(name="normal", value="normal"),
        app_commands.Choice(name="lockdown", value="lockdown"),
    ]
)
async def security_capture_permissions(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    settings = await _get_or_create_security_settings(interaction.guild.id, interaction.guild.name)
    role = interaction.guild.get_role(settings.verified_role_id) if settings.verified_role_id else None
    if not role:
        await interaction.followup.send("Verified role is not configured or not found on this server.", ephemeral=True)
        return

    async with get_async_session() as session:
        settings = await session.get(ServerSecuritySettings, interaction.guild.id)
        if mode.value == "normal":
            settings.normal_permissions = role.permissions.value
        else:
            settings.lockdown_permissions = role.permissions.value
        settings.updated_at = _utcnow_naive()
        session.add(settings)
        await session.flush()

    await interaction.followup.send(
        f'Captured current "{role.name}" permissions into `{mode.value}` template.',
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="security_lockdown",
    description="Enable or disable lockdown permissions for the verified role.",
)
async def security_lockdown(interaction: discord.Interaction, enabled: bool):
    await interaction.response.defer(ephemeral=True)
    settings = await _get_or_create_security_settings(interaction.guild.id, interaction.guild.name)
    role = interaction.guild.get_role(settings.verified_role_id) if settings.verified_role_id else None
    if not role:
        await interaction.followup.send("Verified role is not configured or not found on this server.", ephemeral=True)
        return

    target_permissions = settings.lockdown_permissions if enabled else settings.normal_permissions
    template_name = "lockdown" if enabled else "normal"
    if target_permissions is None:
        await interaction.followup.send(
            f"No `{template_name}` permissions template configured yet. Use `/security_capture_permissions` first.",
            ephemeral=True,
        )
        return

    await role.edit(permissions=discord.Permissions(target_permissions))

    async with get_async_session() as session:
        settings = await session.get(ServerSecuritySettings, interaction.guild.id)
        settings.lockdown_enabled = enabled
        settings.updated_at = _utcnow_naive()
        session.add(settings)
        await session.flush()

    state = "enabled" if enabled else "disabled"
    await interaction.followup.send(
        f"Lockdown {state}. Updated role `{role.name}` permissions from `{template_name}` template.",
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="verify_member",
    description="Grant the configured verified role to a member.",
)
async def verify_member(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    settings = await _get_or_create_security_settings(interaction.guild.id, interaction.guild.name)
    role = interaction.guild.get_role(settings.verified_role_id) if settings.verified_role_id else None
    if not role:
        await interaction.followup.send("Verified role is not configured or not found on this server.", ephemeral=True)
        return

    if role in user.roles:
        await interaction.followup.send(f"{user.mention} already has `{role.name}`.", ephemeral=True)
        return

    await user.add_roles(role, reason=f"Verified by {interaction.user} ({interaction.user.id})")
    await interaction.followup.send(
        f"Granted `{role.name}` to {user.mention}.",
        ephemeral=True,
    )

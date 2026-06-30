from datetime import datetime, timezone

import discord
from discord import app_commands

from api.models.server_security import (
    ServerSecurityCreateNewcomerRoleModel,
    ServerSecurityNewcomerRoleUpdateModel,
    ServerSecurityPermissionsUpdateModel,
)
from api.services.server_security import (
    build_newcomer_role_suggestion,
    create_newcomer_role_and_attach,
    get_or_create_server_security_settings,
    update_newcomer_role,
    update_permission_templates,
)
from src.db.database import get_async_session
from src.db.models import ServerSecuritySettings
from src.modules.localization.service import get_server_locale, tr


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_or_create_security_settings(server_id: int, server_name: str | None = None) -> ServerSecuritySettings:
    async with get_async_session() as session:
        settings = await get_or_create_server_security_settings(session=session, server_id=server_id, server_name=server_name)
        await session.commit()
        return settings


def _parse_color_hex(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip().removeprefix("#")
    if not normalized:
        return None
    if len(normalized) != 6:
        raise ValueError("Color must be a 6-digit hex value like F2C94C.")
    return int(normalized, 16)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="security_set_verified_role",
    description="Set the role granted to members who finished onboarding.",
)
async def security_set_verified_role(interaction: discord.Interaction, role: discord.Role):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)

    async with get_async_session() as session:
        settings = await get_or_create_server_security_settings(session=session, server_id=interaction.guild.id, server_name=interaction.guild.name)
        settings.verified_role_id = role.id
        if settings.normal_permissions is None:
            settings.normal_permissions = role.permissions.value
        settings.updated_at = _utcnow_naive()
        session.add(settings)
        await session.commit()

    await interaction.followup.send(
        tr(locale, "security.verified_role_set", role_name=role.name),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="newcomer_role_suggest",
    description="Show recommended restricted newcomer role settings.",
)
async def security_newcomer_role_suggestion(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    suggestion = build_newcomer_role_suggestion()
    await interaction.followup.send(
        tr(
            locale,
            "security.newcomer_role_suggestion",
            role_name=suggestion.role_name,
            permissions=suggestion.permissions,
            mentionable=suggestion.mentionable,
            hoist=suggestion.hoist,
            color=f"#{suggestion.color:06X}" if suggestion.color is not None else tr(locale, "common.not_configured"),
            reason=suggestion.reason,
        ),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="security_set_newcomer_role",
    description="Set the restricted role used for new members.",
)
async def security_set_newcomer_role(
    interaction: discord.Interaction,
    role: discord.Role,
    enabled: bool = True,
    manual_release: bool = False,
    auto_release_minutes: app_commands.Range[int, 1, 43200] | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    async with get_async_session() as session:
        settings = await update_newcomer_role(
            session=session,
            server_id=interaction.guild.id,
            body=ServerSecurityNewcomerRoleUpdateModel(
                role_id=str(role.id),
                enabled=enabled,
                auto_release_minutes=0 if manual_release else auto_release_minutes,
            ),
            server_name=interaction.guild.name,
        )
        await session.commit()
    await interaction.followup.send(
        tr(
            locale,
            "security.newcomer_role_set",
            role_name=role.name,
            enabled=settings.newcomer_restriction_enabled,
            auto_release_minutes=settings.newcomer_auto_release_minutes or tr(locale, "security.manual_release"),
        ),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="security_create_newcomer_role",
    description="Create and attach a restricted newcomer role.",
)
async def security_create_newcomer_role(
    interaction: discord.Interaction,
    role_name: str = "Newcomer",
    enabled: bool = True,
    manual_release: bool = True,
    auto_release_minutes: app_commands.Range[int, 1, 43200] | None = None,
    mentionable: bool = False,
    hoist: bool = False,
    color_hex: str | None = "F2C94C",
    permissions: str = "0",
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    try:
        color = _parse_color_hex(color_hex)
        body = ServerSecurityCreateNewcomerRoleModel(
            role_name=role_name,
            permissions=permissions,
            mentionable=mentionable,
            hoist=hoist,
            color=color,
            enabled=enabled,
            auto_release_minutes=0 if manual_release else auto_release_minutes,
        )
        async with get_async_session() as session:
            settings = await create_newcomer_role_and_attach(
                session=session,
                server_id=interaction.guild.id,
                body=body,
                server_name=interaction.guild.name,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(str(error), ephemeral=True)
        return

    role = interaction.guild.get_role(settings.newcomer_role_id) if settings.newcomer_role_id else None
    await interaction.followup.send(
        tr(
            locale,
            "security.newcomer_role_created",
            role_name=role.name if role else role_name,
            enabled=settings.newcomer_restriction_enabled,
            auto_release_minutes=settings.newcomer_auto_release_minutes or tr(locale, "security.manual_release"),
        ),
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
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    settings = await _get_or_create_security_settings(interaction.guild.id, interaction.guild.name)
    role = interaction.guild.get_role(settings.verified_role_id) if settings.verified_role_id else None
    if not role:
        await interaction.followup.send(tr(locale, "security.verified_role_missing"), ephemeral=True)
        return

    body = ServerSecurityPermissionsUpdateModel(
        normal_permissions=str(role.permissions.value) if mode.value == "normal" else None,
        lockdown_permissions=str(role.permissions.value) if mode.value == "lockdown" else None,
    )
    async with get_async_session() as session:
        await update_permission_templates(
            session=session,
            server_id=interaction.guild.id,
            body=body,
        )
        await session.commit()

    await interaction.followup.send(
        tr(locale, "security.permissions_captured", role_name=role.name, mode=mode.value),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(
    name="security_lockdown",
    description="Enable or disable lockdown permissions for the verified role.",
)
async def security_lockdown(interaction: discord.Interaction, enabled: bool):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    settings = await _get_or_create_security_settings(interaction.guild.id, interaction.guild.name)
    role = interaction.guild.get_role(settings.verified_role_id) if settings.verified_role_id else None
    if not role:
        await interaction.followup.send(tr(locale, "security.verified_role_missing"), ephemeral=True)
        return

    target_permissions = settings.lockdown_permissions if enabled else settings.normal_permissions
    template_name = "lockdown" if enabled else "normal"
    if target_permissions is None:
        await interaction.followup.send(
            tr(locale, "security.template_missing", template_name=template_name),
            ephemeral=True,
        )
        return

    await role.edit(permissions=discord.Permissions(target_permissions))

    async with get_async_session() as session:
        settings = await get_or_create_server_security_settings(session=session, server_id=interaction.guild.id, server_name=interaction.guild.name)
        settings.lockdown_enabled = enabled
        settings.updated_at = _utcnow_naive()
        session.add(settings)
        await session.commit()

    state = tr(locale, "security.state_enabled" if enabled else "security.state_disabled")
    await interaction.followup.send(
        tr(
            locale,
            "security.lockdown_updated",
            state=state,
            role_name=role.name,
            template_name=template_name,
        ),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.command(
    name="verify_member",
    description="Grant the configured verified role to a member.",
)
async def verify_member(interaction: discord.Interaction, user: discord.Member):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    settings = await _get_or_create_security_settings(interaction.guild.id, interaction.guild.name)
    role = interaction.guild.get_role(settings.verified_role_id) if settings.verified_role_id else None
    if not role:
        await interaction.followup.send(tr(locale, "security.verified_role_missing"), ephemeral=True)
        return

    if role in user.roles:
        await interaction.followup.send(
            tr(locale, "security.verify_already_has", mention=user.mention, role_name=role.name),
            ephemeral=True,
        )
        return

    await user.add_roles(role, reason=f"Verified by {interaction.user} ({interaction.user.id})")
    await interaction.followup.send(
        tr(locale, "security.verify_granted", role_name=role.name, mention=user.mention),
        ephemeral=True,
    )

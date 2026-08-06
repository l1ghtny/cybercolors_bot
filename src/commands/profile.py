from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands

from src.modules.localization.service import get_server_locale, tr


PROFILE_EMBED_COLOR = discord.Color.from_rgb(88, 101, 242)


def _avatar_url(user: discord.abc.User) -> str | None:
    display_avatar = getattr(user, "display_avatar", None)
    value = str(getattr(display_avatar, "url", "") or "")
    return value if value.startswith(("https://", "http://")) else None


def _discord_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"{discord.utils.format_dt(value, style='D')} ({discord.utils.format_dt(value, style='R')})"


def _presence_label(member: discord.Member, locale: str | None) -> str:
    status = str(getattr(member, "status", discord.Status.offline)).lower()
    status_key = status if status in {"online", "idle", "dnd", "offline"} else "offline"
    return tr(locale, f"public_profile.status_{status_key}")


def build_public_profile_embed(
    *,
    member: discord.Member,
    locale: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=tr(locale, "public_profile.title", member=member.display_name),
        description=(
            f"**{tr(locale, 'public_profile.user_id')}:** `{member.id}`\n"
            f"**{tr(locale, 'public_profile.username')}:** @{member.name}\n"
            f"**{tr(locale, 'public_profile.status')}:** {_presence_label(member, locale)}"
        ),
        color=PROFILE_EMBED_COLOR,
    )
    avatar_url = _avatar_url(member)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(
        name=tr(locale, "public_profile.joined_server"),
        value=_discord_datetime(member.joined_at),
        inline=False,
    )
    embed.add_field(
        name=tr(locale, "public_profile.joined_discord"),
        value=_discord_datetime(member.created_at),
        inline=False,
    )
    embed.set_footer(text=tr(locale, "public_profile.footer"))
    return embed


@app_commands.guild_only()
@app_commands.checks.cooldown(1, 5.0, key=lambda interaction: (interaction.guild_id, interaction.user.id))
@app_commands.command(name="profile", description="Show a member's public profile.")
async def profile(interaction: discord.Interaction, user: discord.Member | None = None):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return

    await interaction.response.defer()
    locale = await get_server_locale(interaction.guild.id)
    target = user or interaction.user
    await interaction.followup.send(
        embed=build_public_profile_embed(member=target, locale=locale),
        allowed_mentions=discord.AllowedMentions.none(),
    )

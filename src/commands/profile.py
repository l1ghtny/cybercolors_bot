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


def _cached_member(member: discord.Member) -> discord.Member:
    guild = getattr(member, "guild", None)
    get_member = getattr(guild, "get_member", None)
    if callable(get_member):
        cached = get_member(member.id)
        if cached is not None:
            return cached
    return member


def _member_roles(member: discord.Member) -> list[discord.Role]:
    guild_id = getattr(getattr(member, "guild", None), "id", None)
    return [
        role
        for role in getattr(member, "roles", ())
        if getattr(role, "id", None) != guild_id and getattr(role, "name", "") != "@everyone"
    ]


def _profile_color(member: discord.Member) -> discord.Color:
    color = getattr(member, "color", None)
    if isinstance(color, discord.Color) and color.value:
        return color
    return PROFILE_EMBED_COLOR


def _badge_labels(member: discord.Member, locale: str | None) -> list[str]:
    badges: list[str] = []
    guild = getattr(member, "guild", None)
    if getattr(guild, "owner_id", None) == member.id:
        badges.append(tr(locale, "public_profile.badge_owner"))
    if getattr(member, "premium_since", None) is not None:
        badges.append(tr(locale, "public_profile.badge_booster"))
    if getattr(member, "bot", False):
        badges.append(tr(locale, "public_profile.badge_bot"))
    return badges


def _activity_label(member: discord.Member, locale: str | None) -> str | None:
    custom_activity: str | None = None
    activity_keys = {
        discord.ActivityType.playing: "playing",
        discord.ActivityType.streaming: "streaming",
        discord.ActivityType.listening: "listening",
        discord.ActivityType.watching: "watching",
        discord.ActivityType.competing: "competing",
    }
    for activity in getattr(member, "activities", ()):
        activity_type = getattr(activity, "type", None)
        if activity_type == discord.ActivityType.custom:
            state = getattr(activity, "state", None)
            if state:
                custom_activity = f"💬 {discord.utils.escape_markdown(str(state))}"
            continue

        activity_key = activity_keys.get(activity_type)
        if activity_key is None:
            continue
        activity_name = getattr(activity, "title", None) or getattr(activity, "name", None)
        if activity_name:
            return tr(
                locale,
                f"public_profile.activity_{activity_key}",
                activity=discord.utils.escape_markdown(str(activity_name)),
            )
    return custom_activity


def build_public_profile_embed(
    *,
    member: discord.Member,
    requester: discord.abc.User | None = None,
    locale: str | None = None,
) -> discord.Embed:
    member = _cached_member(member)
    roles = _member_roles(member)
    top_role = discord.utils.escape_markdown(roles[-1].name) if roles else "—"
    badges = _badge_labels(member, locale)
    activity = _activity_label(member, locale)
    description_lines = [
        f"**{tr(locale, 'public_profile.user_id')}:** `{member.id}`",
        f"**{tr(locale, 'public_profile.username')}:** @{member.name}",
        f"**{tr(locale, 'public_profile.status')}:** {_presence_label(member, locale)}",
        f"**{tr(locale, 'public_profile.top_role')}:** {top_role}",
        f"**{tr(locale, 'public_profile.role_count')}:** {len(roles)}",
    ]
    if badges:
        description_lines.append(f"**{tr(locale, 'public_profile.badges')}:** {' · '.join(badges)}")
    if activity:
        description_lines.append(f"**{tr(locale, 'public_profile.activity')}:** {activity}")

    embed = discord.Embed(
        title=tr(locale, "public_profile.title", member=member.display_name),
        description="\n".join(description_lines),
        color=_profile_color(member),
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
    if requester is None:
        embed.set_footer(text=tr(locale, "public_profile.footer"))
    else:
        embed.set_footer(
            text=tr(locale, "public_profile.requested_by", member=requester.display_name),
            icon_url=_avatar_url(requester),
        )
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
        embed=build_public_profile_embed(member=target, requester=interaction.user, locale=locale),
        allowed_mentions=discord.AllowedMentions.none(),
    )

from __future__ import annotations

from datetime import datetime, timezone
import os

import discord
from discord import app_commands

from api.models.user_profiles import UserProfileCardModel
from api.services.moderation_actions_service import DEFAULT_DASHBOARD_BASE_URL
from api.services.moderation_users_service import build_user_profile_card
from src.db.database import get_async_session
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.bot_rbac import ensure_bot_permission
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists


MODRAL_EMBED_COLOR = discord.Color.from_rgb(88, 101, 242)


def _dashboard_profile_url(server_id: int, user_id: int) -> str:
    base_url = os.getenv("DASHBOARD_BASE_URL", DEFAULT_DASHBOARD_BASE_URL).rstrip("/")
    return f"{base_url}/dashboard/{server_id}/users?id={user_id}"


def _discord_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"{discord.utils.format_dt(value, style='D')} ({discord.utils.format_dt(value, style='R')})"


def _is_timed_out(member: discord.Member) -> bool:
    timed_out_until = getattr(member, "communication_disabled_until", None)
    if timed_out_until is None:
        return False
    if timed_out_until.tzinfo is None:
        timed_out_until = timed_out_until.replace(tzinfo=timezone.utc)
    return timed_out_until > datetime.now(timezone.utc)


def _recent_actions(profile: UserProfileCardModel, *, server_id: int) -> str | None:
    if not profile.recent_actions:
        return None
    lines: list[str] = []
    for action in profile.recent_actions[:3]:
        action_url = (
            f"{os.getenv('DASHBOARD_BASE_URL', DEFAULT_DASHBOARD_BASE_URL).rstrip('/')}"
            f"/dashboard/{server_id}/moderation/actions/{action.id}"
        )
        created_at = ""
        if action.created_at:
            timestamp = action.created_at
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            created_at = f" · {discord.utils.format_dt(timestamp, style='R')}"
        lines.append(f"[`{action.action_type}` #{action.action_number}]({action_url}){created_at}")
    return "\n".join(lines)


def build_member_profile_embed(
    profile: UserProfileCardModel,
    *,
    member: discord.Member,
    server_id: int,
    locale: str | None = None,
) -> discord.Embed:
    dashboard_url = _dashboard_profile_url(server_id, member.id)
    username = profile.username or member.name
    statuses = [
        tr(locale, "profile.status_member" if profile.is_member else "profile.status_left"),
    ]
    if _is_timed_out(member):
        statuses.append(tr(locale, "profile.status_timed_out"))
    if profile.monitored:
        statuses.append(tr(locale, "profile.status_monitored"))

    embed = discord.Embed(
        title=tr(locale, "profile.embed_title", member=profile.display_name),
        url=dashboard_url,
        description=(
            f"**{tr(locale, 'profile.user_id')}:** `{member.id}`\n"
            f"**{tr(locale, 'profile.username')}:** @{username}\n"
            f"**{tr(locale, 'profile.status')}:** {' · '.join(statuses)}"
        ),
        color=MODRAL_EMBED_COLOR,
    )
    display_avatar = getattr(member, "display_avatar", None)
    avatar_url = str(getattr(display_avatar, "url", "") or profile.avatar_hash or "")
    if avatar_url.startswith(("https://", "http://")):
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(
        name=tr(locale, "profile.joined_server"),
        value=_discord_datetime(profile.joined_server_at),
        inline=False,
    )
    embed.add_field(
        name=tr(locale, "profile.joined_discord"),
        value=_discord_datetime(profile.joined_discord),
        inline=False,
    )
    embed.add_field(
        name=tr(locale, "profile.moderation"),
        value=tr(
            locale,
            "profile.moderation_summary",
            actions=profile.moderation_actions_count,
            cases=profile.open_cases_count,
        ),
        inline=False,
    )

    if profile.top_rules_violated:
        top_rules = "\n".join(
            f"• {item.title} × **{item.usage_count}**"
            for item in profile.top_rules_violated[:3]
        )
        embed.add_field(name=tr(locale, "profile.top_rules"), value=top_rules, inline=False)

    recent_actions = _recent_actions(profile, server_id=server_id)
    if recent_actions:
        embed.add_field(name=tr(locale, "profile.recent_actions"), value=recent_actions, inline=False)

    embed.set_footer(text=tr(locale, "profile.footer"))
    return embed


class MemberProfileView(discord.ui.View):
    def __init__(self, *, server_id: int, user_id: int, locale: str | None = None):
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Button(
                label=tr(locale, "action.open_dashboard"),
                style=discord.ButtonStyle.link,
                url=_dashboard_profile_url(server_id, user_id),
            )
        )


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="profile", description="Show a member profile and moderation summary.")
async def member_profile(interaction: discord.Interaction, user: discord.Member):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.actions.view", locale=locale):
        return
    if not await ensure_bot_permission(interaction, "moderation.cases.view", locale=locale):
        return

    try:
        async with get_async_session() as session:
            await check_if_server_exists(interaction.guild, session)
            await check_if_user_exists(user, interaction.guild, session)
            profile = await build_user_profile_card(
                session=session,
                server_id=interaction.guild.id,
                user_id=user.id,
                history_limit=5,
                actions_limit=3,
                cases_limit=3,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "profile.load_failed", error=error), ephemeral=True)
        return

    await interaction.followup.send(
        embed=build_member_profile_embed(
            profile,
            member=user,
            server_id=interaction.guild.id,
            locale=locale,
        ),
        view=MemberProfileView(server_id=interaction.guild.id, user_id=user.id, locale=locale),
        ephemeral=True,
    )

from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands

from src.db.database import get_async_session
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.public_warnings import PublicWarning, list_active_public_warnings


WARN_EMBED_COLOR = discord.Color.from_rgb(242, 153, 74)
PUBLIC_WARNING_LIMIT = 10
PUBLIC_WARNING_REASON_LIMIT = 600


def _avatar_url(user: discord.abc.User) -> str | None:
    display_avatar = getattr(user, "display_avatar", None)
    value = str(getattr(display_avatar, "url", "") or "")
    return value if value.startswith(("https://", "http://")) else None


def _warning_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"{discord.utils.format_dt(value, style='D')} ({discord.utils.format_dt(value, style='R')})"


def _truncate_reason(value: str) -> str:
    if len(value) <= PUBLIC_WARNING_REASON_LIMIT:
        return value
    return f"{value[: PUBLIC_WARNING_REASON_LIMIT - 3]}..."


def build_public_warns_embed(
    *,
    target: discord.Member,
    requester: discord.abc.User,
    warnings: list[PublicWarning],
    total: int,
    locale: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=tr(locale, "warns.title"),
        description=tr(locale, "warns.member", member=target.mention),
        color=WARN_EMBED_COLOR,
    )
    target_avatar_url = _avatar_url(target)
    if target_avatar_url:
        embed.set_thumbnail(url=target_avatar_url)

    if not warnings:
        embed.add_field(
            name=tr(locale, "warns.active_heading"),
            value=tr(locale, "warns.none"),
            inline=False,
        )
    else:
        for index, warning in enumerate(warnings, start=1):
            sections = []
            if warning.rule_labels:
                rules = "\n".join(f"• {label}" for label in warning.rule_labels)
                sections.append(f"**{tr(locale, 'warns.rule_label')}:**\n{rules}")
            if warning.reason:
                sections.append(
                    f"**{tr(locale, 'warns.reason_label')}:**\n{_truncate_reason(warning.reason)}"
                )
            sections.append(
                f"**{tr(locale, 'warns.issued_label')}:** {_warning_timestamp(warning.created_at)}"
            )
            embed.add_field(
                name=tr(locale, "warns.item_title", number=index),
                value="\n".join(sections),
                inline=False,
            )
        if total > len(warnings):
            embed.add_field(
                name=tr(locale, "warns.summary_heading"),
                value=tr(locale, "warns.showing", shown=len(warnings), total=total),
                inline=False,
            )

    embed.set_footer(
        text=tr(locale, "warns.requested_by", member=requester.display_name),
        icon_url=_avatar_url(requester),
    )
    return embed


@app_commands.guild_only()
@app_commands.checks.cooldown(1, 5.0, key=lambda interaction: (interaction.guild_id, interaction.user.id))
@app_commands.command(name="warns", description="Show a member's active warnings.")
async def warns(interaction: discord.Interaction, user: discord.Member | None = None):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return

    await interaction.response.defer()
    locale = await get_server_locale(interaction.guild.id)
    target = user or interaction.user
    try:
        async with get_async_session() as session:
            warnings, total = await list_active_public_warnings(
                session,
                server_id=interaction.guild.id,
                user_id=target.id,
                locale=locale,
                limit=PUBLIC_WARNING_LIMIT,
            )
    except Exception:
        await interaction.followup.send(tr(locale, "warns.load_failed"), ephemeral=True)
        return

    await interaction.followup.send(
        embed=build_public_warns_embed(
            target=target,
            requester=interaction.user,
            warnings=warnings,
            total=total,
            locale=locale,
        ),
        allowed_mentions=discord.AllowedMentions.none(),
    )

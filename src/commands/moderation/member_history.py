from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.user_profiles import MemberNoteCreateModel
from api.services.discord_profiles import dashboard_base_url_for_server
from api.services.member_history import create_member_note, list_member_history, list_member_notes
from api.services.moderation_core import build_optional_actor
from src.db.database import get_async_session
from src.db.models import GlobalUser
from src.modules.localization.service import get_server_locale, tr
from src.modules.logs_setup import logger
from src.modules.moderation.bot_rbac import ensure_bot_permission
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists


log = logger.logging.getLogger("bot")


def _dashboard_history_url(server_id: int, user_id: int) -> str:
    base_url = dashboard_base_url_for_server(server_id).rstrip("/")
    return f"{base_url}/dashboard/{server_id}/users?id={user_id}&profileTab=timeline"


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return discord.utils.format_dt(value, style="f")


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


async def _resolve_target(
    *,
    interaction: discord.Interaction,
    session: AsyncSession,
    user: discord.User | None,
    user_id: str | None,
    locale: str,
) -> tuple[int, str] | None:
    if user is not None:
        await check_if_user_exists(user, interaction.guild, session)
        return user.id, getattr(user, "display_name", None) or user.name
    candidate = (user_id or "").strip()
    if not candidate:
        await interaction.followup.send(tr(locale, "member_history.target_required"), ephemeral=True)
        return None
    if not candidate.isdigit():
        await interaction.followup.send(tr(locale, "member_history.target_invalid"), ephemeral=True)
        return None
    target_id = int(candidate)
    stored = await session.get(GlobalUser, target_id)
    if stored is None:
        await interaction.followup.send(tr(locale, "member_history.target_not_found"), ephemeral=True)
        return None
    actor = await build_optional_actor(session, interaction.guild.id, target_id)
    return target_id, actor.display_name if actor is not None else candidate


def _history_event_title(locale: str, event) -> str:
    key = f"member_history.event.{event.event_type}"
    return tr(
        locale,
        key,
        action_type=(event.action_type or "action").upper(),
        action_number=event.action_number or "—",
        case_title=event.case_title or "—",
    )


def _history_event_value(locale: str, event, *, server_id: int) -> str:
    lines = [_format_time(event.occurred_at)]
    if event.actor is not None and event.actor.user_id.isdigit():
        lines.append(f"**{tr(locale, 'member_history.actor')}:** <@{event.actor.user_id}>")
    if event.note:
        lines.append(_truncate(event.note, 600))
    if event.reason:
        lines.append(f"**{tr(locale, 'member_history.reason')}:** {_truncate(event.reason, 500)}")
    if event.commentary:
        lines.append(f"**{tr(locale, 'member_history.commentary')}:** {_truncate(event.commentary, 400)}")
    if event.action_id:
        base_url = dashboard_base_url_for_server(server_id).rstrip("/")
        lines.append(
            f"[{tr(locale, 'member_history.open_action')}]"
            f"({base_url}/dashboard/{server_id}/moderation/actions/{event.action_id})"
        )
    elif event.case_id:
        base_url = dashboard_base_url_for_server(server_id).rstrip("/")
        lines.append(
            f"[{tr(locale, 'member_history.open_case')}]"
            f"({base_url}/dashboard/{server_id}/moderation/cases/{event.case_id})"
        )
    if event.source and event.source != "modral":
        lines.append(f"**{tr(locale, 'member_history.source')}:** `{event.source}`")
    return _truncate("\n".join(lines), 1024)


class MemberHistoryDashboardView(discord.ui.View):
    def __init__(self, *, server_id: int, user_id: int, locale: str):
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Button(
                label=tr(locale, "action.open_dashboard"),
                style=discord.ButtonStyle.link,
                url=_dashboard_history_url(server_id, user_id),
            )
        )


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="history", description="Show a user's unified moderation history.")
@app_commands.describe(
    user="Discord user whose history should be shown.",
    user_id="Discord user ID for someone who is no longer on the server.",
    limit="Number of recent events to show.",
)
async def member_history(
    interaction: discord.Interaction,
    user: discord.User | None = None,
    user_id: str | None = None,
    limit: app_commands.Range[int, 1, 20] = 10,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.member_history.view", locale=locale):
        return
    try:
        async with get_async_session() as session:
            await check_if_server_exists(interaction.guild, session)
            target = await _resolve_target(
                interaction=interaction,
                session=session,
                user=user,
                user_id=user_id,
                locale=locale,
            )
            if target is None:
                return
            target_id, target_name = target
            events = await list_member_history(
                session=session,
                server_id=interaction.guild.id,
                user_id=target_id,
                limit=limit,
            )
            await session.commit()
    except Exception:
        log.exception("Failed to load member history in guild %s", interaction.guild.id)
        await interaction.followup.send(
            tr(locale, "member_history.load_failed"),
            ephemeral=True,
        )
        return
    if not events:
        await interaction.followup.send(tr(locale, "member_history.empty"), ephemeral=True)
        return
    embed = discord.Embed(
        title=tr(locale, "member_history.title", member=target_name),
        color=discord.Color.blurple(),
    )
    displayed = 0
    for event in events:
        title = _truncate(_history_event_title(locale, event), 256)
        value = _history_event_value(locale, event, server_id=interaction.guild.id)
        if len(embed) + len(title) + len(value) > 5_700:
            break
        embed.add_field(
            name=title,
            value=value,
            inline=False,
        )
        displayed += 1
    embed.set_footer(text=tr(locale, "member_history.footer", count=displayed))
    await interaction.followup.send(
        embed=embed,
        view=MemberHistoryDashboardView(
            server_id=interaction.guild.id,
            user_id=target_id,
            locale=locale,
        ),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="add", description="Add a private moderator note about a user.")
@app_commands.describe(
    note="Private note shared with the moderation team.",
    user="Discord user the note is about.",
    user_id="Discord user ID for someone who is no longer on the server.",
)
async def member_note_add(
    interaction: discord.Interaction,
    note: app_commands.Range[str, 1, 4000],
    user: discord.User | None = None,
    user_id: str | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.member_notes.manage", locale=locale):
        return
    try:
        async with get_async_session() as session:
            await check_if_server_exists(interaction.guild, session)
            await check_if_user_exists(interaction.user, interaction.guild, session)
            target = await _resolve_target(
                interaction=interaction,
                session=session,
                user=user,
                user_id=user_id,
                locale=locale,
            )
            if target is None:
                return
            target_id, target_name = target
            await create_member_note(
                session=session,
                server_id=interaction.guild.id,
                user_id=target_id,
                author_user_id=interaction.user.id,
                body=MemberNoteCreateModel(note=note),
            )
            await session.commit()
    except Exception:
        log.exception("Failed to add member note in guild %s", interaction.guild.id)
        await interaction.followup.send(tr(locale, "member_note.add_failed"), ephemeral=True)
        return
    await interaction.followup.send(
        tr(locale, "member_note.added", member=target_name),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="list", description="List private moderator notes about a user.")
@app_commands.describe(
    user="Discord user whose notes should be shown.",
    user_id="Discord user ID for someone who is no longer on the server.",
    limit="Number of recent notes to show.",
)
async def member_notes_list(
    interaction: discord.Interaction,
    user: discord.User | None = None,
    user_id: str | None = None,
    limit: app_commands.Range[int, 1, 20] = 10,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.member_history.view", locale=locale):
        return
    try:
        async with get_async_session() as session:
            await check_if_server_exists(interaction.guild, session)
            target = await _resolve_target(
                interaction=interaction,
                session=session,
                user=user,
                user_id=user_id,
                locale=locale,
            )
            if target is None:
                return
            target_id, target_name = target
            notes = await list_member_notes(
                session=session,
                server_id=interaction.guild.id,
                user_id=target_id,
                limit=limit,
            )
            await session.commit()
    except Exception:
        log.exception("Failed to list member notes in guild %s", interaction.guild.id)
        await interaction.followup.send(tr(locale, "member_note.load_failed"), ephemeral=True)
        return
    if not notes:
        await interaction.followup.send(tr(locale, "member_note.empty"), ephemeral=True)
        return
    embed = discord.Embed(
        title=tr(locale, "member_note.list_title", member=target_name),
        color=discord.Color.blurple(),
    )
    for item in notes:
        author = (
            f"<@{item.author.user_id}>"
            if item.author and item.author.user_id.isdigit()
            else tr(locale, "member_history.system")
        )
        name = f"{_format_time(item.created_at)} · {author}"
        value = _truncate(item.note or "—", 1024)
        if len(embed) + len(name) + len(value) > 5_700:
            break
        embed.add_field(
            name=name,
            value=value,
            inline=False,
        )
    embed.set_footer(text=tr(locale, "member_note.footer"))
    await interaction.followup.send(
        embed=embed,
        view=MemberHistoryDashboardView(
            server_id=interaction.guild.id,
            user_id=target_id,
            locale=locale,
        ),
        ephemeral=True,
    )

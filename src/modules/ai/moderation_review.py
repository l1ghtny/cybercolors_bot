from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import discord
from fastapi import HTTPException

from api.models.moderation_cases import ModerationCaseCreateModel
from api.services.moderation_cases_service import create_case
from api.services.ai_settings import get_or_create_server_ai_settings, should_moderate_message_channel
from src.db.database import get_async_session
from src.db.models import AIModerationDecision, CaseStatus, ModerationCase, ServerAISettings, ServerModerationSettings
from src.modules.ai.ai_main import ai_main_class
from src.modules.ai.models import MessageModerationInput, ModerationVerdict
from src.modules.logs_setup import logger
from src.modules.moderation.bot_services import fetch_open_case_models
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists

logger = logger.logging.getLogger("bot")


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _truncate(value: str | None, limit: int) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _attachment_payload(message: discord.Message) -> list[dict]:
    payload: list[dict] = []
    for attachment in message.attachments:
        payload.append(
            {
                "id": str(attachment.id),
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "size": attachment.size,
                "url": attachment.url,
            }
        )
    return payload


def _content_for_moderation(message: discord.Message, *, include_attachments: bool) -> str:
    content = message.content or ""
    if not include_attachments or not message.attachments:
        return content
    attachment_lines = [
        f"- {item.get('filename')} ({item.get('content_type') or 'unknown'}, {item.get('size')} bytes): {item.get('url')}"
        for item in _attachment_payload(message)
    ]
    return f"{content}\n\nAttachments:\n" + "\n".join(attachment_lines)


def _raw_response_text(verdict: ModerationVerdict) -> str | None:
    response = verdict.raw_response
    if response is None:
        return None
    return response.content


def _parse_error(verdict: ModerationVerdict) -> str | None:
    if "parse_error" in verdict.categories:
        return verdict.reason
    return None


async def create_ai_moderation_decision(
    *,
    session,
    message: discord.Message,
    verdict: ModerationVerdict,
    settings: ServerAISettings,
    attachments: list[dict],
) -> AIModerationDecision:
    raw_response = verdict.raw_response
    decision = AIModerationDecision(
        server_id=message.guild.id,
        channel_id=message.channel.id,
        message_id=message.id,
        author_user_id=message.author.id,
        message_content=message.content or None,
        attachments_json=attachments,
        provider=raw_response.provider if raw_response else None,
        model=raw_response.model if raw_response else None,
        strictness=settings.moderation_strictness,
        flagged=verdict.flagged,
        severity=verdict.severity,
        categories=verdict.categories,
        reason=verdict.reason,
        suggested_action=verdict.suggested_action,
        rule_ids=verdict.rule_ids,
        raw_response=_raw_response_text(verdict),
        parse_error=_parse_error(verdict),
        status="pending_review" if verdict.flagged else "no_action_needed",
    )
    session.add(decision)
    await session.flush()
    await session.refresh(decision)
    return decision


def build_ai_moderation_embed(decision: AIModerationDecision, message: discord.Message) -> discord.Embed:
    color = discord.Color.orange()
    if decision.severity == "high":
        color = discord.Color.red()
    elif decision.severity == "low":
        color = discord.Color.gold()

    jump_url = getattr(message, "jump_url", None)
    embed = discord.Embed(
        title="AI moderation review",
        description=_truncate(decision.reason, 350) or "The AI flagged this message for moderator review.",
        color=color,
        url=jump_url,
    )
    embed.add_field(name="Author", value=f"<@{decision.author_user_id}> (`{decision.author_user_id}`)", inline=True)
    embed.add_field(name="Channel", value=f"<#{decision.channel_id}> (`{decision.channel_id}`)", inline=True)
    embed.add_field(name="Severity", value=f"`{decision.severity}`", inline=True)
    embed.add_field(name="Suggested action", value=f"`{decision.suggested_action}`", inline=True)
    embed.add_field(name="Strictness", value=f"`{decision.strictness}`", inline=True)
    if decision.categories:
        embed.add_field(name="Categories", value=", ".join(f"`{item}`" for item in decision.categories[:8]), inline=False)
    if decision.rule_ids:
        embed.add_field(name="Possible rules", value=", ".join(f"`{item}`" for item in decision.rule_ids[:8]), inline=False)
    if decision.message_content:
        embed.add_field(name="Message", value=_truncate(decision.message_content, 900), inline=False)
    if decision.attachments_json:
        attachment_names = [item.get("filename") or item.get("url") or "attachment" for item in decision.attachments_json[:5]]
        embed.add_field(name="Attachments", value="\n".join(_truncate(item, 120) for item in attachment_names), inline=False)
    embed.set_footer(text=f"AI decision ID: {decision.id}")
    return embed


async def _moderator_allowed(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.moderate_members)


async def _set_decision_status(
    decision_id: UUID,
    *,
    status: str,
    reviewer_id: int,
    linked_case_id: UUID | None = None,
) -> AIModerationDecision | None:
    async with get_async_session() as session:
        decision = await session.get(AIModerationDecision, decision_id)
        if decision is None:
            return None
        decision.status = status
        decision.reviewed_by_user_id = reviewer_id
        decision.reviewed_at = _naive_utcnow()
        decision.updated_at = _naive_utcnow()
        if linked_case_id is not None:
            decision.linked_case_id = linked_case_id
        session.add(decision)
        await session.commit()
        await session.refresh(decision)
        return decision


class AICaseSelect(discord.ui.Select):
    def __init__(self, *, decision_id: UUID, cases):
        options = []
        for item in cases[:25]:
            label = f"#{item.id[:8]} {item.title}"
            if len(label) > 100:
                label = f"{label[:97]}..."
            options.append(
                discord.SelectOption(
                    label=label,
                    value=item.id,
                    description=(item.target_user.display_name or item.target_user.user_id)[:100],
                )
            )
        super().__init__(placeholder="Attach this AI review to an open case", min_values=1, max_values=1, options=options)
        self.decision_id = decision_id

    async def callback(self, interaction: discord.Interaction):
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        case_id = UUID(self.values[0])
        decision = await _set_decision_status(
            self.decision_id,
            status="case_linked",
            reviewer_id=interaction.user.id,
            linked_case_id=case_id,
        )
        if decision is None:
            await interaction.response.send_message("AI decision was not found.", ephemeral=True)
            return
        await interaction.response.send_message(f"Linked AI review to case `{str(case_id)[:8]}`.", ephemeral=True)


class AIModerationReviewView(discord.ui.View):
    def __init__(self, *, decision_id: UUID, open_cases):
        super().__init__(timeout=86400)
        self.decision_id = decision_id
        if open_cases:
            self.add_item(AICaseSelect(decision_id=decision_id, cases=open_cases))

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.secondary)
    async def dismiss_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        decision = await _set_decision_status(self.decision_id, status="dismissed", reviewer_id=interaction.user.id)
        if decision is None:
            await interaction.response.send_message("AI decision was not found.", ephemeral=True)
            return
        await interaction.response.send_message("AI review dismissed.", ephemeral=True)

    @discord.ui.button(label="Needs action", style=discord.ButtonStyle.primary)
    async def action_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        decision = await _set_decision_status(self.decision_id, status="action_requested", reviewer_id=interaction.user.id)
        if decision is None:
            await interaction.response.send_message("AI decision was not found.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Marked as needing moderator action. Use `/mod warn`, `/mod mute`, `/mod kick`, or `/mod ban` and attach the selected case if needed.",
            ephemeral=True,
        )

    @discord.ui.button(label="Create case", style=discord.ButtonStyle.success)
    async def create_case_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with get_async_session() as session:
            decision = await session.get(AIModerationDecision, self.decision_id)
            if decision is None:
                await interaction.followup.send("AI decision was not found.", ephemeral=True)
                return
            try:
                await check_if_server_exists(interaction.guild, session)
                await check_if_user_exists(interaction.user, interaction.guild, session)
                member = interaction.guild.get_member(decision.author_user_id)
                if member is None:
                    member = await interaction.guild.fetch_member(decision.author_user_id)
                await check_if_user_exists(member, interaction.guild, session)
                created = await create_case(
                    session=session,
                    server_id=interaction.guild.id,
                    body=ModerationCaseCreateModel(
                        target_user_id=str(decision.author_user_id),
                        opened_by_user_id=str(interaction.user.id),
                        title=f"AI review - {decision.severity}: {decision.suggested_action}"[:300],
                        summary=_truncate(decision.reason, 1000) or None,
                        rule_ids=decision.rule_ids,
                    ),
                    opened_by_user_id=interaction.user.id,
                )
                decision.status = "case_created"
                decision.linked_case_id = UUID(created.id)
                decision.reviewed_by_user_id = interaction.user.id
                decision.reviewed_at = _naive_utcnow()
                decision.updated_at = _naive_utcnow()
                session.add(decision)
                await session.commit()
            except Exception as error:
                await interaction.followup.send(f"Could not create case: {error}", ephemeral=True)
                return
        await interaction.followup.send(f"Created case `{created.id[:8]}` for this AI review.", ephemeral=True)


async def send_ai_moderation_review(
    *,
    guild: discord.Guild,
    message: discord.Message,
    decision: AIModerationDecision,
) -> bool:
    async with get_async_session() as session:
        mod_settings = await session.get(ServerModerationSettings, guild.id)
        if not mod_settings or not mod_settings.mod_log_channel_id:
            return False
        open_cases = await fetch_open_case_models(
            session=session,
            server_id=guild.id,
            user_id=decision.author_user_id,
            limit=25,
        )

    channel = guild.get_channel(mod_settings.mod_log_channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(mod_settings.mod_log_channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            logger.warning("Cannot resolve AI moderation log channel %s in guild %s: %s", mod_settings.mod_log_channel_id, guild.id, error)
            return False
    send_method = getattr(channel, "send", None)
    if send_method is None:
        return False
    try:
        await send_method(
            embed=build_ai_moderation_embed(decision, message),
            view=AIModerationReviewView(decision_id=decision.id, open_cases=open_cases),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True
    except (discord.Forbidden, discord.HTTPException) as error:
        logger.warning("Failed to send AI moderation review in guild %s: %s", guild.id, error)
        return False


async def screen_message_with_ai(message: discord.Message) -> None:
    if message.guild is None:
        return

    async with get_async_session() as session:
        settings = await get_or_create_server_ai_settings(session, message.guild.id, server_name=message.guild.name)
        if message.author.bot and not settings.moderation_monitor_bots:
            return
        if not should_moderate_message_channel(settings, channel_id=message.channel.id):
            return
        attachments = _attachment_payload(message)
        if attachments and not settings.moderation_monitor_attachments and not (message.content or "").strip():
            return
        content = _content_for_moderation(message, include_attachments=settings.moderation_monitor_attachments)
        if not content.strip():
            return
        verdict = await ai_main_class.check_message(
            MessageModerationInput(
                content=content,
                server_id=message.guild.id,
                author_user_id=message.author.id,
                channel_id=message.channel.id,
                message_id=message.id,
                author_display_name=getattr(message.author, "display_name", None) or getattr(message.author, "name", None),
            ),
            session=session,
            include_member_profile=True,
            moderation_strictness=settings.moderation_strictness,
        )
        decision = None
        if verdict.flagged or settings.log_ai_decisions:
            decision = await create_ai_moderation_decision(
                session=session,
                message=message,
                verdict=verdict,
                settings=settings,
                attachments=attachments if settings.moderation_monitor_attachments else [],
            )
            await session.commit()

    if decision is not None and verdict.flagged:
        await send_ai_moderation_review(guild=message.guild, message=message, decision=decision)

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import discord
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from api.models.moderation_cases import ModerationCaseCreateModel
from api.services.ai_settings import can_invoke_answer_flow, get_or_create_server_ai_settings, should_moderate_message_channel
from api.services.monitoring_service import upsert_monitored_user
from api.services.moderation_cases_service import create_case
from src.db.database import get_async_session
from src.db.models import (
    AIModerationDecision,
    ActionType,
    ModerationRule,
    ServerAISettings,
    ServerLocalizationSettings,
    ServerModerationSettings,
)
from src.modules.ai.ai_main import ai_main_class
from src.modules.ai.discord_media import ai_images_from_discord_message
from src.modules.ai.models import MessageModerationInput, ModerationVerdict
from src.modules.localization.service import normalize_locale_code, tr
from src.modules.logs_setup import logger
from src.modules.moderation.durations import parse_duration_text
from src.modules.moderation.bot_services import (
    create_bot_moderation_action,
    fetch_active_rule_models,
    fetch_open_case_models,
    rule_label,
    validate_target_for_moderation,
)
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists

logger = logger.logging.getLogger("bot")

AI_MOD_COMPONENT_PREFIX = "ai_mod"
AI_REVIEW_ACTIVE_STATUSES = {"pending_review", "action_requested", "case_created", "case_linked"}
AI_MODERATION_DEFAULT_TIMEOUT_SECONDS = 20
ACTIONABLE_AI_ACTIONS = {
    "warn": ActionType.WARN,
    "mute": ActionType.MUTE,
    "kick": ActionType.KICK,
    "ban": ActionType.BAN,
}
AI_RULE_SELECTION_LIMIT = 25


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _truncate(value: str | None, limit: int) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _decision_component_id(action: str, decision_id: UUID) -> str:
    return f"{AI_MOD_COMPONENT_PREFIX}:{action}:{decision_id}"


def _first_valid_uuid(raw_ids: list[str] | None) -> UUID | None:
    for raw_id in raw_ids or []:
        try:
            return UUID(str(raw_id))
        except (TypeError, ValueError):
            continue
    return None


def _is_action_override(decision: AIModerationDecision, selected_action: str) -> bool:
    return (decision.suggested_action or "none") != selected_action


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


async def _referenced_message_for_moderation(message: discord.Message):
    reference = getattr(message, "reference", None)
    if reference is None:
        return None

    resolved = getattr(reference, "resolved", None)
    if resolved is not None and getattr(resolved, "id", None) is not None:
        return resolved

    message_id = getattr(reference, "message_id", None)
    if message_id is None:
        return None

    channel = message.channel
    channel_id = getattr(reference, "channel_id", None)
    if channel_id is not None and getattr(channel, "id", None) != channel_id and message.guild is not None:
        channel = message.guild.get_channel(channel_id) or channel
        if getattr(channel, "id", None) != channel_id:
            try:
                channel = await message.guild.fetch_channel(channel_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                return None

    fetch_message = getattr(channel, "fetch_message", None)
    if fetch_message is None:
        return None
    try:
        fetched = await fetch_message(message_id)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return None
    return fetched if fetched is not None and getattr(fetched, "id", None) is not None else None


async def _reply_context_payload(message: discord.Message) -> dict[str, int | str | bool | None]:
    referenced = await _referenced_message_for_moderation(message)
    if referenced is None:
        return {}
    author = getattr(referenced, "author", None)
    return {
        "reply_to_message_id": getattr(referenced, "id", None),
        "reply_to_author_user_id": getattr(author, "id", None),
        "reply_to_author_display_name": getattr(author, "display_name", None) or getattr(author, "name", None),
        "reply_to_author_is_bot": bool(getattr(author, "bot", False)),
        "reply_to_content": _truncate(_content_for_moderation(referenced, include_attachments=True), 1500),
    }


def _mentioned_user_payload(message: discord.Message) -> list[dict]:
    bot_user_id = _current_bot_user_id(message)
    payload: list[dict] = []
    for user in getattr(message, "mentions", []) or []:
        user_id = getattr(user, "id", None)
        payload.append(
            {
                "user_id": str(user_id) if user_id is not None else None,
                "display_name": getattr(user, "display_name", None) or getattr(user, "global_name", None),
                "username": getattr(user, "name", None),
                "is_bot": bool(getattr(user, "bot", False)),
                "is_current_bot": user_id is not None and bot_user_id is not None and int(user_id) == int(bot_user_id),
            }
        )
    return payload


def _current_bot_user_id(message: discord.Message) -> int | None:
    guild = getattr(message, "guild", None)
    bot_member = getattr(guild, "me", None)
    if bot_member is not None and getattr(bot_member, "id", None) is not None:
        return int(bot_member.id)
    client_user = getattr(getattr(message, "_state", None), "user", None)
    if client_user is not None and getattr(client_user, "id", None) is not None:
        return int(client_user.id)
    return None


def _current_bot_mentioned(message: discord.Message) -> bool:
    bot_user_id = _current_bot_user_id(message)
    if bot_user_id is None:
        return False
    return any(getattr(user, "id", None) == bot_user_id for user in getattr(message, "mentions", []) or [])


def _message_author_role_ids(message: discord.Message) -> list[int]:
    return [int(role.id) for role in getattr(getattr(message, "author", None), "roles", []) if getattr(role, "id", None) is not None]


def _is_allowed_answer_flow_invocation(settings: ServerAISettings, message: discord.Message) -> bool:
    if not _current_bot_mentioned(message):
        return False
    return can_invoke_answer_flow(
        settings,
        channel_id=message.channel.id,
        role_ids=_message_author_role_ids(message),
    )


def _raw_response_text(verdict: ModerationVerdict) -> str | None:
    response = verdict.raw_response
    if response is None:
        return None
    return response.content


def _parse_error(verdict: ModerationVerdict) -> str | None:
    if "parse_error" in verdict.categories:
        return verdict.reason
    return None


def _valid_rule_uuid_map(raw_ids: list[str] | None) -> dict[str, UUID]:
    parsed: dict[str, UUID] = {}
    for raw_id in raw_ids or []:
        try:
            parsed[str(raw_id)] = UUID(str(raw_id))
        except (TypeError, ValueError):
            continue
    return parsed


def _valid_rule_id_strings(raw_ids: list[str] | None) -> list[str]:
    return [str(item) for item in _valid_rule_uuid_map(raw_ids).values()]


def _ai_rule_defaults(decision: AIModerationDecision, available_rule_ids: set[str]) -> set[str]:
    return {rule_id for rule_id in _valid_rule_id_strings(decision.rule_ids) if rule_id in available_rule_ids}


def _rule_select_options(rules, default_rule_ids: set[str]) -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []
    for rule in rules[:AI_RULE_SELECTION_LIMIT]:
        rule_id = str(rule.id)
        label = rule_label(rule)
        description = (rule.description or "").replace("\n", " ").strip()
        if len(description) > 100:
            description = f"{description[:97]}..."
        options.append(
            discord.SelectOption(
                label=label[:100],
                value=rule_id,
                description=description or None,
                default=rule_id in default_rule_ids,
            )
        )
    return options


def _rule_matches_query(rule, query: str) -> bool:
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return True
    haystack = " ".join(
        str(item or "")
        for item in (
            rule_label(rule),
            getattr(rule, "code", None),
            getattr(rule, "title", None),
            getattr(rule, "description", None),
        )
    ).casefold()
    return normalized_query in haystack


def _localized_rule_label(rule: ModerationRule, locale: str | None) -> str:
    code = (rule.code or "").strip()
    title = (rule.title or "").strip()
    if code.isdigit():
        keycap_code = "".join(f"{digit}\ufe0f\u20e3" for digit in code)
        return f"{tr(locale, 'modlog.rule_label')} {keycap_code}: {title}".strip(": ")
    if code:
        return f"{code} {title}".strip()
    return title or tr(locale, "common.rule_fallback")


async def _server_locale(session, server_id: int) -> str:
    if not hasattr(session, "get"):
        return normalize_locale_code(None)
    settings = await session.get(ServerLocalizationSettings, server_id)
    return normalize_locale_code(settings.locale_code if settings else None)


async def _rule_labels_for_decision(session, decision: AIModerationDecision, locale: str | None) -> list[str]:
    uuid_by_raw = _valid_rule_uuid_map(decision.rule_ids)
    labels_by_id: dict[UUID, str] = {}
    if uuid_by_raw:
        rules = (
            await session.exec(
                select(ModerationRule).where(
                    ModerationRule.server_id == decision.server_id,
                    ModerationRule.id.in_(list(uuid_by_raw.values())),
                )
            )
        ).all()
        labels_by_id = {rule.id: _localized_rule_label(rule, locale) for rule in rules}

    labels: list[str] = []
    for raw_id in (decision.rule_ids or [])[:8]:
        parsed_id = uuid_by_raw.get(str(raw_id))
        labels.append(labels_by_id.get(parsed_id, str(raw_id)) if parsed_id else str(raw_id))
    return labels


def _bot_member_for_guild(guild: discord.Guild):
    bot_member = getattr(guild, "me", None)
    if bot_member is not None:
        return bot_member
    client_user = getattr(getattr(guild, "_state", None), "user", None)
    get_member = getattr(guild, "get_member", None)
    if client_user is not None and get_member is not None:
        return get_member(client_user.id)
    return None


def _permissions_for_bot(guild: discord.Guild, channel):
    permissions_for = getattr(channel, "permissions_for", None)
    bot_member = _bot_member_for_guild(guild)
    if permissions_for is None or bot_member is None:
        return None
    return permissions_for(bot_member)


def _bot_can_read_message_channel(message: discord.Message) -> bool:
    permissions = _permissions_for_bot(message.guild, message.channel)
    if permissions is None:
        return True
    return bool(
        getattr(permissions, "view_channel", False)
        and getattr(permissions, "read_messages", True)
        and getattr(permissions, "read_message_history", True)
    )


def _bot_can_send_ai_mod_log(guild: discord.Guild, channel) -> bool:
    permissions = _permissions_for_bot(guild, channel)
    if permissions is None:
        return True
    can_send = getattr(permissions, "send_messages", False)
    if getattr(channel, "type", None) == discord.ChannelType.public_thread:
        can_send = can_send or getattr(permissions, "send_messages_in_threads", False)
    return bool(
        getattr(permissions, "view_channel", False)
        and can_send
        and getattr(permissions, "embed_links", True)
    )


async def _daily_ai_moderation_tokens_used(session, *, server_id: int, now: datetime | None = None) -> int:
    if not hasattr(session, "exec"):
        return 0
    now = now or _naive_utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.exec(
        select(func.coalesce(func.sum(AIModerationDecision.total_tokens), 0)).where(
            AIModerationDecision.server_id == server_id,
            AIModerationDecision.created_at >= day_start,
        )
    )
    value = result.one()
    return int(value or 0)


async def _usage_cap_reached(session, settings: ServerAISettings) -> bool:
    limit = settings.moderation_daily_token_limit
    if limit is None:
        return False
    used = await _daily_ai_moderation_tokens_used(session, server_id=settings.server_id)
    return used >= limit


async def _find_existing_decision(session, *, server_id: int, message_id: int) -> AIModerationDecision | None:
    if not hasattr(session, "exec"):
        return None
    result = await session.exec(
        select(AIModerationDecision).where(
            AIModerationDecision.server_id == server_id,
            AIModerationDecision.message_id == message_id,
        )
    )
    return result.first()


async def create_ai_moderation_decision(
    *,
    session,
    message: discord.Message,
    verdict: ModerationVerdict,
    settings: ServerAISettings,
    attachments: list[dict],
) -> AIModerationDecision:
    existing = await _find_existing_decision(session, server_id=message.guild.id, message_id=message.id)
    if existing is not None:
        return existing

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
        total_tokens=raw_response.total_tokens if raw_response else 0,
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
    try:
        await session.flush()
    except IntegrityError:
        if hasattr(session, "rollback"):
            await session.rollback()
        existing = await _find_existing_decision(session, server_id=message.guild.id, message_id=message.id)
        if existing is not None:
            return existing
        raise
    await session.refresh(decision)
    return decision


def build_ai_moderation_embed(
    decision: AIModerationDecision,
    message: discord.Message | None = None,
    *,
    rule_labels: list[str] | None = None,
) -> discord.Embed:
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
    if decision.archive_channel_id and decision.archive_message_id:
        archive_url = f"https://discord.com/channels/{decision.server_id}/{decision.archive_channel_id}/{decision.archive_message_id}"
        embed.add_field(
            name="Original channel deleted",
            value=f"The source channel was deleted. [Open transcript archive]({archive_url}).",
            inline=False,
        )
    embed.add_field(name="Severity", value=f"`{decision.severity}`", inline=True)
    embed.add_field(name="Suggested action", value=f"`{decision.suggested_action}`", inline=True)
    embed.add_field(name="Strictness", value=f"`{decision.strictness}`", inline=True)
    if decision.selected_action:
        override = " yes" if decision.action_override else " no"
        embed.add_field(name="Moderator action", value=f"`{decision.selected_action}` (override:{override})", inline=True)
    if decision.categories:
        embed.add_field(name="Categories", value=", ".join(f"`{item}`" for item in decision.categories[:8]), inline=False)
    display_rules = rule_labels if rule_labels is not None else list(decision.rule_ids or [])[:8]
    if display_rules:
        embed.add_field(name="Possible rules", value=", ".join(f"`{item}`" for item in display_rules), inline=False)
    if decision.message_content:
        embed.add_field(name="Message", value=_truncate(decision.message_content, 900), inline=False)
    if decision.attachments_json:
        attachment_names = [item.get("filename") or item.get("url") or "attachment" for item in decision.attachments_json[:5]]
        embed.add_field(name="Attachments", value="\n".join(_truncate(item, 120) for item in attachment_names), inline=False)
    embed.set_footer(text=f"AI decision ID: {decision.id}")
    return embed


def build_ai_review_resolution_embed(
    decision: AIModerationDecision,
    *,
    locale: str | None = None,
    rule_labels: list[str] | None = None,
) -> discord.Embed:
    color = discord.Color.green() if decision.status == "action_applied" else discord.Color.greyple()
    embed = discord.Embed(
        title="AI moderation review resolved",
        description=f"Decision `{decision.id}` has been resolved. Review controls are disabled.",
        color=color,
        timestamp=decision.reviewed_at,
    )
    embed.add_field(name="Status", value=f"`{decision.status}`", inline=True)
    embed.add_field(name="Selected action", value=f"`{decision.selected_action or 'none'}`", inline=True)
    if decision.reviewed_by_user_id:
        embed.add_field(name="Reviewer", value=f"<@{decision.reviewed_by_user_id}> (`{decision.reviewed_by_user_id}`)", inline=True)
    if rule_labels:
        label_key = "modlog.rule_label" if len(rule_labels) == 1 else "modlog.rules_label"
        embed.add_field(name=tr(locale, label_key), value="\n".join(f"`{item}`" for item in rule_labels), inline=False)
    if decision.linked_action_id:
        embed.add_field(name="Action ID", value=f"`{decision.linked_action_id}`", inline=False)
    if decision.linked_case_id:
        embed.add_field(name="Case ID", value=f"`{decision.linked_case_id}`", inline=False)
    if decision.action_reason:
        embed.add_field(name="Reason", value=_truncate(decision.action_reason, 900), inline=False)
    return embed


def build_disabled_ai_review_view(decision: AIModerationDecision) -> discord.ui.View:
    view = AIModerationReviewView(
        decision_id=decision.id,
        suggested_action=decision.suggested_action,
        include_case_select=True,
    )
    for item in view.children:
        item.disabled = True
    return view


async def _edit_ai_review_message(
    *,
    guild: discord.Guild | None,
    message: discord.Message | None,
    decision: AIModerationDecision,
    locale: str | None = None,
    rule_labels: list[str] | None = None,
) -> None:
    target_message = message
    if target_message is None and guild is not None and decision.review_channel_id and decision.review_message_id:
        channel = guild.get_channel(decision.review_channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(decision.review_channel_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                channel = None
        fetch_message = getattr(channel, "fetch_message", None)
        if fetch_message is not None:
            try:
                target_message = await fetch_message(decision.review_message_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                target_message = None
    if target_message is None:
        return

    original_embeds = list(getattr(target_message, "embeds", []) or [])[:1]
    original_embeds.append(
        build_ai_review_resolution_embed(
            decision,
            locale=locale,
            rule_labels=rule_labels,
        )
    )
    await target_message.edit(embeds=original_embeds, view=build_disabled_ai_review_view(decision))


def _is_review_terminal(decision: AIModerationDecision) -> bool:
    return bool(decision.linked_action_id or decision.status in {"action_applied", "dismissed", "no_action_needed"})


async def _send_ephemeral(interaction: discord.Interaction, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


async def _refresh_review_message_for_decision(interaction: discord.Interaction, decision: AIModerationDecision) -> None:
    async with get_async_session() as session:
        locale = await _server_locale(session, decision.server_id)
        rule_labels = await _rule_labels_for_decision(session, decision, locale)
    try:
        await _edit_ai_review_message(
            guild=interaction.guild,
            message=interaction.message if isinstance(interaction.message, discord.Message) else None,
            decision=decision,
            locale=locale,
            rule_labels=rule_labels,
        )
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
        logger.warning("Failed to refresh AI review message for decision %s: %s", decision.id, error)


async def _ensure_review_open(interaction: discord.Interaction, decision_id: UUID) -> AIModerationDecision | None:
    async with get_async_session() as session:
        decision = await session.get(AIModerationDecision, decision_id)
        if decision is None:
            await _send_ephemeral(interaction, "AI decision was not found.")
            return None
        if interaction.guild is not None and decision.server_id != interaction.guild.id:
            await _send_ephemeral(interaction, "AI decision was not found for this server.")
            return None
        if _is_review_terminal(decision):
            await _refresh_review_message_for_decision(interaction, decision)
            await _send_ephemeral(interaction, "This AI review has already been resolved.")
            return None
        return decision


async def _moderator_allowed(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.moderate_members)


async def _set_decision_status(
    decision_id: UUID,
    *,
    status: str,
    reviewer_id: int,
    linked_case_id: UUID | None = None,
    selected_action: str | None = None,
    action_reason: str | None = None,
    action_override: bool | None = None,
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
        if selected_action is not None:
            decision.selected_action = selected_action
        if action_reason is not None:
            decision.action_reason = action_reason
        if action_override is not None:
            decision.action_override = action_override
        session.add(decision)
        await session.commit()
        await session.refresh(decision)
        return decision


def _case_options(cases) -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []
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
    if not options:
        options.append(discord.SelectOption(label="No open case loaded", value="__none__"))
    return options


class AICaseSelect(discord.ui.Select):
    def __init__(self, *, decision_id: UUID, cases):
        super().__init__(
            custom_id=_decision_component_id("case", decision_id),
            placeholder="Attach this AI review to an open case",
            min_values=1,
            max_values=1,
            options=_case_options(cases),
        )
        self.decision_id = decision_id

    async def callback(self, interaction: discord.Interaction):
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        decision = await _ensure_review_open(interaction, self.decision_id)
        if decision is None:
            return
        if self.values[0] == "__none__":
            await interaction.response.send_message("No open case was available on this review message.", ephemeral=True)
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


class AIActionSelect(discord.ui.Select):
    def __init__(self, *, decision_id: UUID, suggested_action: str | None = None):
        options = [
            discord.SelectOption(label="Watch", value="watch", description="Add the user to the monitoring watchlist."),
            discord.SelectOption(label="Warn", value="warn", description="Record a warning and DM the user."),
            discord.SelectOption(label="Mute", value="mute", description="Apply the configured mute role."),
            discord.SelectOption(label="Kick", value="kick", description="Kick the user from the server."),
            discord.SelectOption(label="Ban", value="ban", description="Ban the user from the server."),
            discord.SelectOption(label="No action", value="none", description="Dismiss this AI review without action."),
        ]
        for option in options:
            if option.value == suggested_action:
                option.default = True
        super().__init__(
            custom_id=_decision_component_id("action", decision_id),
            placeholder="Choose moderator action",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.decision_id = decision_id

    async def callback(self, interaction: discord.Interaction):
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        decision = await _ensure_review_open(interaction, self.decision_id)
        if decision is None:
            return
        selected_action = self.values[0]
        if selected_action == "none":
            updated_decision = await _set_decision_status(
                self.decision_id,
                status="dismissed",
                reviewer_id=interaction.user.id,
                selected_action="none",
                action_override=_is_action_override(decision, "none"),
            )
            if updated_decision is None:
                await interaction.response.send_message("AI decision was not found.", ephemeral=True)
                return
            await _refresh_review_message_for_decision(interaction, updated_decision)
            await interaction.response.send_message("AI review dismissed with no action.", ephemeral=True)
            return

        if selected_action == "watch":
            await interaction.response.send_modal(
                AIWatchConfirmModal(
                    decision_id=self.decision_id,
                    default_reason=decision.reason,
                )
            )
            return

        action_type = ACTIONABLE_AI_ACTIONS.get(selected_action)
        if action_type is None:
            await interaction.response.send_message("Unsupported moderation action.", ephemeral=True)
            return

        async with get_async_session() as session:
            settings = await session.get(ServerModerationSettings, interaction.guild.id) if interaction.guild else None
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild.id) if interaction.guild else []

        default_duration = settings.default_mute_minutes if settings else 60
        if not rules:
            await interaction.response.send_modal(
                AIActionConfirmModal(
                    decision_id=self.decision_id,
                    action_type=action_type,
                    selected_rule_ids=[],
                    default_reason=decision.reason,
                    default_duration_minutes=default_duration,
                )
            )
            return

        rule_view = AIActionRuleSelectionView(
                decision_id=self.decision_id,
                action_type=action_type,
                rules=rules,
                default_rule_ids=_ai_rule_defaults(decision, {str(rule.id) for rule in rules}),
                default_reason=decision.reason,
                default_duration_minutes=default_duration,
        )
        await interaction.response.send_message(
            rule_view.content(),
            view=rule_view,
            ephemeral=True,
        )


class AIRuleSelect(discord.ui.Select):
    def __init__(self, *, rules, default_rule_ids: set[str]):
        if rules:
            options = _rule_select_options(rules, default_rule_ids)
            max_values = min(len(rules), AI_RULE_SELECTION_LIMIT)
            disabled = False
        else:
            options = [discord.SelectOption(label="No matching rules", value="__none__")]
            max_values = 1
            disabled = True
        super().__init__(
            placeholder="Broken server rules",
            min_values=0,
            max_values=max_values,
            options=options,
            disabled=disabled,
        )
        self.visible_rule_ids = {str(rule.id) for rule in rules}

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, AIActionRuleSelectionView):
            view.update_visible_selection(
                selected_visible_rule_ids=[value for value in self.values if value != "__none__"],
                visible_rule_ids=self.visible_rule_ids,
            )
        await interaction.response.defer()


class AIActionRuleSearchModal(discord.ui.Modal):
    def __init__(self, *, view: "AIActionRuleSelectionView"):
        super().__init__(title="Search rules")
        self.rule_view = view
        self.query = discord.ui.TextInput(
            label="Search",
            placeholder="Rule number, title, or keyword",
            default=view.search_query,
            max_length=100,
            required=False,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        self.rule_view.search_query = str(self.query.value or "").strip()
        self.rule_view.page = 0
        self.rule_view.rebuild_items()
        await interaction.response.edit_message(content=self.rule_view.content(), view=self.rule_view)


class AIActionRuleSearchButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Search", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AIActionRuleSelectionView):
            await interaction.response.send_message("Rule selector expired. Choose the action again.", ephemeral=True)
            return
        await interaction.response.send_modal(AIActionRuleSearchModal(view=view))


class AIActionRulePageButton(discord.ui.Button):
    def __init__(self, *, direction: int):
        label = "Next" if direction > 0 else "Previous"
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=1)
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AIActionRuleSelectionView):
            await interaction.response.send_message("Rule selector expired. Choose the action again.", ephemeral=True)
            return
        view.page = max(0, min(view.page + self.direction, view.max_page))
        view.rebuild_items()
        await interaction.response.edit_message(content=view.content(), view=view)


class AIActionRuleClearSearchButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Clear search", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AIActionRuleSelectionView):
            await interaction.response.send_message("Rule selector expired. Choose the action again.", ephemeral=True)
            return
        view.search_query = ""
        view.page = 0
        view.rebuild_items()
        await interaction.response.edit_message(content=view.content(), view=view)


class AIActionRuleClearSelectionButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Clear rules", style=discord.ButtonStyle.danger, row=2)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AIActionRuleSelectionView):
            await interaction.response.send_message("Rule selector expired. Choose the action again.", ephemeral=True)
            return
        view.selected_rule_ids = []
        view.rebuild_items()
        await interaction.response.edit_message(content=view.content(), view=view)


class AIActionRuleConfirmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Continue", style=discord.ButtonStyle.primary, row=2)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AIActionRuleSelectionView):
            await interaction.response.send_message("Rule selector expired. Choose the action again.", ephemeral=True)
            return
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        decision = await _ensure_review_open(interaction, view.decision_id)
        if decision is None:
            return
        await interaction.response.send_modal(
            AIActionConfirmModal(
                decision_id=view.decision_id,
                action_type=view.action_type,
                selected_rule_ids=list(view.selected_rule_ids),
                default_reason=view.default_reason,
                default_duration_minutes=view.default_duration_minutes,
            )
        )


class AIActionRuleSelectionView(discord.ui.View):
    def __init__(
        self,
        *,
        decision_id: UUID,
        action_type: ActionType,
        rules,
        default_rule_ids: set[str],
        default_reason: str | None,
        default_duration_minutes: int,
    ):
        super().__init__(timeout=300)
        self.decision_id = decision_id
        self.action_type = action_type
        self.rules = list(rules)
        self.default_reason = default_reason
        self.default_duration_minutes = default_duration_minutes
        self.search_query = ""
        self.page = 0
        self.selected_rule_ids = [str(rule.id) for rule in self.rules if str(rule.id) in default_rule_ids]
        self.rule_select = AIRuleSelect(rules=[], default_rule_ids=set())
        self.rebuild_items()

    @property
    def filtered_rules(self):
        return [rule for rule in self.rules if _rule_matches_query(rule, self.search_query)]

    @property
    def max_page(self) -> int:
        filtered_count = len(self.filtered_rules)
        if filtered_count <= 0:
            return 0
        return (filtered_count - 1) // AI_RULE_SELECTION_LIMIT

    def page_rules(self):
        filtered = self.filtered_rules
        start = self.page * AI_RULE_SELECTION_LIMIT
        return filtered[start : start + AI_RULE_SELECTION_LIMIT]

    def selected_rule_id_set(self) -> set[str]:
        return set(self.selected_rule_ids)

    def update_visible_selection(self, *, selected_visible_rule_ids: list[str], visible_rule_ids: set[str]) -> None:
        kept_hidden = [rule_id for rule_id in self.selected_rule_ids if rule_id not in visible_rule_ids]
        visible_selected = [rule_id for rule_id in selected_visible_rule_ids if rule_id in visible_rule_ids]
        self.selected_rule_ids = list(dict.fromkeys([*kept_hidden, *visible_selected]))

    def content(self) -> str:
        filtered_count = len(self.filtered_rules)
        query_part = f" Search: `{self.search_query}`." if self.search_query else ""
        return (
            "Review the broken rules before applying this action."
            f"{query_part} Showing page {self.page + 1}/{self.max_page + 1}, "
            f"{filtered_count} matching rules, {len(self.selected_rule_ids)} selected."
        )

    def rebuild_items(self) -> None:
        self.page = max(0, min(self.page, self.max_page))
        self.clear_items()
        page_rules = self.page_rules()
        self.rule_select = AIRuleSelect(rules=page_rules, default_rule_ids=self.selected_rule_id_set())
        self.add_item(self.rule_select)
        search_button = AIActionRuleSearchButton()
        prev_button = AIActionRulePageButton(direction=-1)
        prev_button.disabled = self.page <= 0
        next_button = AIActionRulePageButton(direction=1)
        next_button.disabled = self.page >= self.max_page
        clear_search_button = AIActionRuleClearSearchButton()
        clear_search_button.disabled = not bool(self.search_query)
        clear_selection_button = AIActionRuleClearSelectionButton()
        clear_selection_button.disabled = not bool(self.selected_rule_ids)
        self.add_item(search_button)
        self.add_item(prev_button)
        self.add_item(next_button)
        self.add_item(clear_search_button)
        self.add_item(clear_selection_button)
        self.add_item(AIActionRuleConfirmButton())


class AIWatchConfirmModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        decision_id: UUID,
        default_reason: str | None,
    ):
        super().__init__(title="Confirm AI watch")
        self.decision_id = decision_id
        self.reason = discord.ui.TextInput(
            label="Watch reason",
            style=discord.TextStyle.paragraph,
            default=_truncate(default_reason, 900),
            max_length=1000,
            required=True,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        preflight_decision = await _ensure_review_open(interaction, self.decision_id)
        if preflight_decision is None:
            return

        reason = str(self.reason.value).strip()
        if not reason:
            await interaction.followup.send("A reason is required.", ephemeral=True)
            return

        resolved_decision = None
        try:
            async with get_async_session() as session:
                decision = await session.get(AIModerationDecision, self.decision_id)
                if decision is None or decision.server_id != interaction.guild.id:
                    await interaction.followup.send("AI decision was not found.", ephemeral=True)
                    return
                if _is_review_terminal(decision):
                    await _refresh_review_message_for_decision(interaction, decision)
                    await interaction.followup.send("This AI review has already been resolved.", ephemeral=True)
                    return

                await check_if_server_exists(interaction.guild, session)
                await check_if_user_exists(interaction.user, interaction.guild, session)
                member = interaction.guild.get_member(decision.author_user_id)
                if member is None:
                    member = await interaction.guild.fetch_member(decision.author_user_id)
                await check_if_user_exists(member, interaction.guild, session)

                await upsert_monitored_user(
                    session=session,
                    server_id=interaction.guild.id,
                    user_id=decision.author_user_id,
                    reason=reason,
                    added_by_user_id=interaction.user.id,
                    source="ai_moderation",
                )
                decision.status = "action_applied"
                decision.reviewed_by_user_id = interaction.user.id
                decision.reviewed_at = _naive_utcnow()
                decision.updated_at = _naive_utcnow()
                decision.selected_action = "watch"
                decision.action_reason = reason
                decision.action_override = _is_action_override(decision, "watch")
                session.add(decision)
                await session.commit()
                resolved_decision = decision
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            await interaction.followup.send(f"Could not add user to watchlist in Discord: {error}", ephemeral=True)
            return
        except Exception as error:
            logger.exception("Failed to apply AI watch for decision %s", self.decision_id)
            await interaction.followup.send(f"Could not add user to watchlist: {error}", ephemeral=True)
            return

        await _refresh_review_message_for_decision(interaction, resolved_decision)
        await interaction.followup.send(
            f"Added user to watchlist and linked it to AI decision `{str(self.decision_id)[:8]}`.",
            ephemeral=True,
        )


class AIActionConfirmModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        decision_id: UUID,
        action_type: ActionType,
        selected_rule_ids: list[str],
        default_reason: str | None,
        default_duration_minutes: int,
    ):
        super().__init__(title=f"Confirm AI {action_type.value}")
        self.decision_id = decision_id
        self.action_type = action_type
        self.selected_rule_ids = selected_rule_ids
        self.reason = discord.ui.TextInput(
            label="Reason",
            style=discord.TextStyle.paragraph,
            default=_truncate(default_reason, 900),
            max_length=1000,
            required=True,
        )
        self.add_item(self.reason)
        if action_type == ActionType.MUTE:
            self.duration_text = discord.ui.TextInput(
                label="Duration",
                placeholder="Examples: 30m, 2h, 3d, 1w",
                default=f"{default_duration_minutes}m",
                max_length=16,
                required=True,
            )
            self.add_item(self.duration_text)
        else:
            self.duration_text = None

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        preflight_decision = await _ensure_review_open(interaction, self.decision_id)
        if preflight_decision is None:
            return

        reason = str(self.reason.value).strip()
        if not reason:
            await interaction.followup.send("A reason is required.", ephemeral=True)
            return

        expires_at = None
        duration_label = None
        effective_duration = None
        if self.action_type == ActionType.MUTE:
            async with get_async_session() as session:
                settings = await session.get(ServerModerationSettings, interaction.guild.id)
            max_minutes = settings.max_mute_minutes if settings else 43_200
            try:
                duration_selection = parse_duration_text(str(self.duration_text.value), max_minutes=max_minutes)
            except ValueError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
            effective_duration = duration_selection.minutes
            duration_label = duration_selection.label
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=effective_duration)

        resolved_decision = None
        try:
            async with get_async_session() as session:
                decision = await session.get(AIModerationDecision, self.decision_id)
                if decision is None or decision.server_id != interaction.guild.id:
                    await interaction.followup.send("AI decision was not found.", ephemeral=True)
                    return
                if _is_review_terminal(decision):
                    await _refresh_review_message_for_decision(interaction, decision)
                    await interaction.followup.send("This AI review has already been resolved.", ephemeral=True)
                    return

                await check_if_server_exists(interaction.guild, session)
                await check_if_user_exists(interaction.user, interaction.guild, session)
                member = interaction.guild.get_member(decision.author_user_id)
                if member is None:
                    member = await interaction.guild.fetch_member(decision.author_user_id)
                await check_if_user_exists(member, interaction.guild, session)

                target_error = validate_target_for_moderation(interaction, member, None)
                if target_error:
                    await interaction.followup.send(target_error, ephemeral=True)
                    return

                action = await create_bot_moderation_action(
                    session=session,
                    interaction=interaction,
                    user=member,
                    action_type=self.action_type,
                    rule_id=_first_valid_uuid(self.selected_rule_ids),
                    rule_ids=self.selected_rule_ids,
                    commentary=(
                        f"Applied from AI decision {decision.id}. "
                        f"AI suggested `{decision.suggested_action}` with severity `{decision.severity}`."
                    ),
                    reason=reason,
                    expires_at=expires_at,
                    case_id=decision.linked_case_id,
                )
                decision.status = "action_applied"
                decision.reviewed_by_user_id = interaction.user.id
                decision.reviewed_at = _naive_utcnow()
                decision.updated_at = _naive_utcnow()
                decision.linked_action_id = action.id
                decision.selected_action = self.action_type.value
                decision.action_reason = reason
                decision.action_override = _is_action_override(decision, self.action_type.value)
                session.add(decision)
                await session.commit()
                resolved_decision = decision
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            await interaction.followup.send(f"Could not apply action in Discord: {error}", ephemeral=True)
            return
        except Exception as error:
            logger.exception("Failed to apply AI moderation action %s for decision %s", self.action_type.value, self.decision_id)
            await interaction.followup.send(f"Could not apply action: {error}", ephemeral=True)
            return

        await _refresh_review_message_for_decision(interaction, resolved_decision)
        duration_suffix = f" for {duration_label}" if duration_label else ""
        await interaction.followup.send(
            f"Applied `{self.action_type.value}`{duration_suffix} and linked it to AI decision `{str(self.decision_id)[:8]}`.",
            ephemeral=True,
        )


class AIDismissButton(discord.ui.Button):
    def __init__(self, *, decision_id: UUID):
        super().__init__(
            label="Dismiss",
            style=discord.ButtonStyle.secondary,
            custom_id=_decision_component_id("dismiss", decision_id),
        )
        self.decision_id = decision_id

    async def callback(self, interaction: discord.Interaction):
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        decision = await _ensure_review_open(interaction, self.decision_id)
        if decision is None:
            return
        decision = await _set_decision_status(
            self.decision_id,
            status="dismissed",
            reviewer_id=interaction.user.id,
            selected_action="none",
            action_override=_is_action_override(decision, "none"),
        )
        if decision is None:
            await interaction.response.send_message("AI decision was not found.", ephemeral=True)
            return
        await _refresh_review_message_for_decision(interaction, decision)
        await interaction.response.send_message("AI review dismissed.", ephemeral=True)


class AICreateCaseButton(discord.ui.Button):
    def __init__(self, *, decision_id: UUID):
        super().__init__(
            label="Create case",
            style=discord.ButtonStyle.success,
            custom_id=_decision_component_id("create_case", decision_id),
        )
        self.decision_id = decision_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        decision = await _ensure_review_open(interaction, self.decision_id)
        if decision is None:
            return
        await interaction.response.defer(ephemeral=True)
        async with get_async_session() as session:
            decision = await session.get(AIModerationDecision, self.decision_id)
            if decision is None:
                await interaction.followup.send("AI decision was not found.", ephemeral=True)
                return
            if _is_review_terminal(decision):
                await _refresh_review_message_for_decision(interaction, decision)
                await interaction.followup.send("This AI review has already been resolved.", ephemeral=True)
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
                        rule_ids=_valid_rule_id_strings(decision.rule_ids),
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


class AIModerationReviewView(discord.ui.View):
    def __init__(
        self,
        *,
        decision_id: UUID,
        open_cases=None,
        suggested_action: str | None = None,
        include_case_select: bool | None = None,
    ):
        super().__init__(timeout=None)
        cases = open_cases or []
        self.decision_id = decision_id
        self.add_item(AIDismissButton(decision_id=decision_id))
        self.add_item(AICreateCaseButton(decision_id=decision_id))
        self.add_item(AIActionSelect(decision_id=decision_id, suggested_action=suggested_action))
        should_include_case_select = bool(cases) if include_case_select is None else include_case_select
        if should_include_case_select:
            self.add_item(AICaseSelect(decision_id=decision_id, cases=cases))


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
        locale = await _server_locale(session, guild.id)
        rule_labels = await _rule_labels_for_decision(session, decision, locale)
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
    if not _bot_can_send_ai_mod_log(guild, channel):
        logger.warning("Bot cannot write AI moderation review to channel %s in guild %s", getattr(channel, "id", None), guild.id)
        return False
    try:
        sent_message = await send_method(
            embed=build_ai_moderation_embed(decision, message, rule_labels=rule_labels),
            view=AIModerationReviewView(
                decision_id=decision.id,
                open_cases=open_cases,
                suggested_action=decision.suggested_action,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        async with get_async_session() as session:
            stored_decision = await session.get(AIModerationDecision, decision.id)
            if stored_decision is not None:
                stored_decision.review_channel_id = getattr(getattr(sent_message, "channel", None), "id", None) or getattr(channel, "id", None)
                stored_decision.review_message_id = getattr(sent_message, "id", None)
                stored_decision.updated_at = _naive_utcnow()
                session.add(stored_decision)
                await session.commit()
        return True
    except (discord.Forbidden, discord.HTTPException) as error:
        logger.warning("Failed to send AI moderation review in guild %s: %s", guild.id, error)
        return False


async def register_ai_moderation_review_views(client: discord.Client, *, limit: int = 500) -> int:
    registered = 0
    async with get_async_session() as session:
        decisions = (
            await session.exec(
                select(AIModerationDecision)
                .where(AIModerationDecision.status.in_(AI_REVIEW_ACTIVE_STATUSES))
                .order_by(AIModerationDecision.created_at.desc())
                .limit(limit)
            )
        ).all()

    for decision in decisions:
        client.add_view(
            AIModerationReviewView(
                decision_id=decision.id,
                suggested_action=decision.suggested_action,
                include_case_select=True,
            )
        )
        registered += 1
    if registered:
        logger.info("Registered %s persistent AI moderation review views.", registered)
    return registered


async def screen_message_with_ai(message: discord.Message) -> None:
    try:
        if message.guild is None:
            return
        if not _bot_can_read_message_channel(message):
            logger.warning("Skipping AI moderation for unreadable channel %s in guild %s", message.channel.id, message.guild.id)
            return

        decision = None
        verdict = None
        async with get_async_session() as session:
            settings = await get_or_create_server_ai_settings(session, message.guild.id, server_name=message.guild.name)
            if settings.moderation_kill_switch_enabled:
                return
            if message.author.bot and not settings.moderation_monitor_bots:
                return
            if not should_moderate_message_channel(settings, channel_id=message.channel.id):
                return
            answer_flow_invocation = _is_allowed_answer_flow_invocation(settings, message)
            if await _usage_cap_reached(session, settings):
                logger.warning("Skipping AI moderation in guild %s because the daily token cap has been reached", message.guild.id)
                return
            existing = await _find_existing_decision(session, server_id=message.guild.id, message_id=message.id)
            if existing is not None:
                return
            attachments = _attachment_payload(message)
            if attachments and not settings.moderation_monitor_attachments and not (message.content or "").strip():
                return
            content = _content_for_moderation(message, include_attachments=settings.moderation_monitor_attachments)
            if not content.strip():
                return
            locale = await _server_locale(session, message.guild.id)
            bot_user_id = _current_bot_user_id(message)
            images = ai_images_from_discord_message(
                message,
                include_attachments=settings.moderation_monitor_attachments,
                include_custom_emojis=True,
            )
            reply_context = await _reply_context_payload(message)
            try:
                verdict = await asyncio.wait_for(
                    ai_main_class.check_message(
                        MessageModerationInput(
                            content=content,
                            server_id=message.guild.id,
                            author_user_id=message.author.id,
                            channel_id=message.channel.id,
                            message_id=message.id,
                            author_display_name=getattr(message.author, "display_name", None) or getattr(message.author, "name", None),
                            author_is_bot=bool(getattr(message.author, "bot", False)),
                            server_locale=locale,
                            bot_user_id=bot_user_id,
                            mentioned_users=_mentioned_user_payload(message),
                            current_bot_mentioned=_current_bot_mentioned(message),
                            answer_flow_invocation=answer_flow_invocation,
                            **reply_context,
                            images=images,
                        ),
                        session=session,
                        include_member_profile=True,
                        moderation_strictness=settings.moderation_strictness,
                    ),
                    timeout=settings.moderation_provider_timeout_seconds or AI_MODERATION_DEFAULT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning("AI moderation timed out in guild %s for message %s", message.guild.id, message.id)
                return
            except asyncio.CancelledError:
                logger.info("AI moderation task cancelled in guild %s for message %s", message.guild.id, message.id)
                raise
            except Exception:
                logger.exception("AI moderation provider failed in guild %s for message %s", message.guild.id, message.id)
                return

            if verdict.flagged or settings.log_ai_decisions or settings.moderation_daily_token_limit is not None:
                try:
                    decision = await create_ai_moderation_decision(
                        session=session,
                        message=message,
                        verdict=verdict,
                        settings=settings,
                        attachments=attachments if settings.moderation_monitor_attachments else [],
                    )
                    await session.commit()
                except Exception:
                    if hasattr(session, "rollback"):
                        await session.rollback()
                    logger.exception("Failed to persist AI moderation decision in guild %s for message %s", message.guild.id, message.id)
                    return

        if decision is not None and verdict is not None and verdict.flagged:
            try:
                await send_ai_moderation_review(guild=message.guild, message=message, decision=decision)
            except Exception:
                logger.exception("Failed to send AI moderation review in guild %s for message %s", message.guild.id, message.id)
    except asyncio.CancelledError:
        raise
    except Exception:
        guild_id = getattr(getattr(message, "guild", None), "id", None)
        message_id = getattr(message, "id", None)
        logger.exception("Unexpected AI moderation failure in guild %s for message %s", guild_id, message_id)

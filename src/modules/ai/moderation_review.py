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
    MessageLog,
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
TRUSTED_AUTHOR_PERMISSION_NAMES = (
    "administrator",
    "manage_guild",
    "manage_messages",
    "ban_members",
    "kick_members",
    "moderate_members",
    "manage_roles",
)
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


def _ai_review_color(severity: str | None) -> discord.Color:
    if severity == "high":
        return discord.Color.red()
    if severity == "medium":
        return discord.Color.orange()
    if severity == "low":
        return discord.Color.gold()
    return discord.Color.greyple()


def _ai_review_title(severity: str | None, locale: str | None = None) -> str:
    if severity == "high":
        return tr(locale, "ai_review.title_high")
    if severity == "medium":
        return tr(locale, "ai_review.title_medium")
    if severity == "low":
        return tr(locale, "ai_review.title_low")
    return tr(locale, "ai_review.title_note")


def _ai_review_display(locale: str | None, kind: str, value: str | None) -> str:
    normalized = (value or "none").strip() or "none"
    return tr(locale, f"ai_review.{kind}_{normalized}")


def _ai_review_reason(locale: str | None, reason: str | None) -> str:
    fallback = tr(locale, "ai_review.reason_fallback")
    cleaned = _truncate(reason, 420).strip()
    if not cleaned:
        return fallback
    locale_code = normalize_locale_code(locale)
    prefix = f"{locale_code}:"
    if cleaned.lower().startswith(prefix):
        cleaned = cleaned[len(prefix):].strip()
    return cleaned or fallback


def _quote_preview(value: str | None, limit: int = 900) -> str:
    preview = _truncate(value, limit).strip()
    if not preview:
        return ""
    return "> " + preview.replace("\n", "\n> ")


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


def _message_created_at_naive_utc(message: discord.Message) -> datetime | None:
    created_at = getattr(message, "created_at", None)
    if created_at is None:
        return None
    if getattr(created_at, "tzinfo", None) is not None:
        return created_at.astimezone(timezone.utc).replace(tzinfo=None)
    return created_at


def _message_log_context_item(log: MessageLog, *, target_author_id: int | None) -> dict[str, str | bool | None]:
    return {
        "message_id": str(log.message_id),
        "author_user_id": str(log.user_id),
        "is_target_author": target_author_id is not None and int(log.user_id) == int(target_author_id),
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "reply_to_message_id": str(log.reply_to_message_id) if log.reply_to_message_id is not None else None,
        "content": _truncate(log.content, 500),
    }


async def _recent_message_context_payload(session, message: discord.Message) -> dict[str, list[dict[str, str | bool | None]]]:
    if not hasattr(session, "exec"):
        return {}
    guild_id = getattr(getattr(message, "guild", None), "id", None)
    channel_id = getattr(getattr(message, "channel", None), "id", None)
    message_id = getattr(message, "id", None)
    author_id = getattr(getattr(message, "author", None), "id", None)
    if guild_id is None or channel_id is None or message_id is None:
        return {}

    created_at = _message_created_at_naive_utc(message)
    cutoff = (created_at or _naive_utcnow()) - timedelta(minutes=5)
    filters = [
        MessageLog.server_id == int(guild_id),
        MessageLog.channel_id == int(channel_id),
        MessageLog.message_id != int(message_id),
        MessageLog.created_at >= cutoff,
    ]
    if created_at is not None:
        filters.append(MessageLog.created_at <= created_at)
    else:
        filters.append(MessageLog.message_id < int(message_id))

    try:
        result = await session.exec(
            select(MessageLog)
            .where(*filters)
            .order_by(MessageLog.created_at.desc(), MessageLog.message_id.desc())
            .limit(12)
        )
        rows = list(result.all())
    except Exception:
        logger.exception("Failed to load AI moderation message context for message %s", message_id)
        return {}

    rows = list(reversed(rows))
    channel_context = [_message_log_context_item(row, target_author_id=author_id) for row in rows]
    author_context = [item for item in channel_context if item.get("is_target_author")]
    payload: dict[str, list[dict[str, str | bool | None]]] = {}
    if channel_context:
        payload["recent_channel_messages"] = channel_context[-10:]
    if author_context:
        payload["recent_author_messages"] = author_context[-6:]
    return payload

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


def _permission_names(permissions) -> list[str]:
    if permissions is None:
        return []
    return [name for name in TRUSTED_AUTHOR_PERMISSION_NAMES if bool(getattr(permissions, name, False))]


def _message_author_roles(message: discord.Message) -> list[dict]:
    roles = []
    for role in getattr(getattr(message, "author", None), "roles", []) or []:
        role_id = getattr(role, "id", None)
        permissions = _permission_names(getattr(role, "permissions", None))
        roles.append(
            {
                "id": str(role_id) if role_id is not None else None,
                "name": str(getattr(role, "name", None)) if getattr(role, "name", None) is not None else None,
                "permissions": permissions,
                "administrator": "administrator" in permissions,
            }
        )
    return roles


def _message_author_trust_flags(message: discord.Message, roles: list[dict]) -> tuple[bool, bool]:
    author = getattr(message, "author", None)
    guild_permissions = _permission_names(getattr(author, "guild_permissions", None))
    role_permissions = {permission for role in roles for permission in role.get("permissions", [])}
    is_admin = "administrator" in guild_permissions or "administrator" in role_permissions
    is_moderator = is_admin or bool(set(guild_permissions).intersection(TRUSTED_AUTHOR_PERMISSION_NAMES)) or bool(
        role_permissions.intersection(TRUSTED_AUTHOR_PERMISSION_NAMES)
    )
    return is_admin, is_moderator


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
    locale: str | None = None,
) -> discord.Embed:
    jump_url = getattr(message, "jump_url", None)
    reason = _ai_review_reason(locale, decision.reason)
    embed = discord.Embed(
        title=_ai_review_title(decision.severity, locale),
        description=reason,
        color=_ai_review_color(decision.severity),
        url=jump_url,
        timestamp=decision.created_at,
    )
    embed.add_field(
        name=tr(locale, "ai_review.field_context"),
        value=(
            f"{tr(locale, 'ai_review.label_author')}: <@{decision.author_user_id}> (`{decision.author_user_id}`)\n"
            f"{tr(locale, 'ai_review.label_channel')}: <#{decision.channel_id}> (`{decision.channel_id}`)"
            + (f"\n{tr(locale, 'ai_review.label_source')}: [{tr(locale, 'ai_review.open_in_discord')}]({jump_url})" if jump_url else "")
        ),
        inline=False,
    )
    if decision.archive_channel_id and decision.archive_message_id:
        archive_url = f"https://discord.com/channels/{decision.server_id}/{decision.archive_channel_id}/{decision.archive_message_id}"
        embed.add_field(
            name=tr(locale, "ai_review.field_original_channel_deleted"),
            value=tr(locale, "ai_review.original_channel_deleted", url=archive_url),
            inline=False,
        )
    embed.add_field(name=tr(locale, "ai_review.field_severity"), value=f"`{_ai_review_display(locale, 'severity', decision.severity)}`", inline=True)
    embed.add_field(name=tr(locale, "ai_review.field_suggested_action"), value=f"`{_ai_review_display(locale, 'action', decision.suggested_action)}`", inline=True)
    embed.add_field(name=tr(locale, "ai_review.field_strictness"), value=f"`{_ai_review_display(locale, 'strictness', decision.strictness)}`", inline=True)
    if decision.selected_action:
        override = tr(locale, "common.bool_true") if decision.action_override else tr(locale, "common.bool_false")
        embed.add_field(name=tr(locale, "ai_review.field_moderator_action"), value=f"`{_ai_review_display(locale, 'action', decision.selected_action)}` ({tr(locale, 'ai_review.override_label')}: `{override}`)", inline=True)
    if decision.categories:
        embed.add_field(name=tr(locale, "ai_review.field_categories"), value=", ".join(f"`{item}`" for item in decision.categories[:8]), inline=False)
    display_rules = rule_labels if rule_labels is not None else list(decision.rule_ids or [])[:8]
    if display_rules:
        embed.add_field(name=tr(locale, "ai_review.field_possible_rules"), value=", ".join(f"`{item}`" for item in display_rules), inline=False)
    if decision.message_content:
        embed.add_field(name=tr(locale, "ai_review.field_message"), value=_quote_preview(decision.message_content, 900), inline=False)
    if decision.attachments_json:
        attachment_names = [item.get("filename") or item.get("url") or tr(locale, "ai_review.attachment_fallback") for item in decision.attachments_json[:5]]
        embed.add_field(name=tr(locale, "ai_review.field_attachments"), value="\n".join(_truncate(item, 120) for item in attachment_names), inline=False)
    embed.set_footer(text=tr(locale, "ai_review.footer_decision_id", decision_id=decision.id))
    return embed


def build_ai_review_resolution_embed(
    decision: AIModerationDecision,
    *,
    locale: str | None = None,
    rule_labels: list[str] | None = None,
) -> discord.Embed:
    color = discord.Color.green() if decision.status == "action_applied" else discord.Color.greyple()
    embed = discord.Embed(
        title=tr(locale, "ai_review.resolved_title"),
        description=tr(locale, "ai_review.resolved_description"),
        color=color,
        timestamp=decision.reviewed_at,
    )
    embed.add_field(name=tr(locale, "ai_review.field_status"), value=f"`{_ai_review_display(locale, 'status', decision.status)}`", inline=True)
    embed.add_field(name=tr(locale, "ai_review.field_selected_action"), value=f"`{_ai_review_display(locale, 'action', decision.selected_action)}`", inline=True)
    if decision.reviewed_by_user_id:
        embed.add_field(name=tr(locale, "ai_review.field_reviewer"), value=f"<@{decision.reviewed_by_user_id}> (`{decision.reviewed_by_user_id}`)", inline=True)
    if rule_labels:
        label_key = "modlog.rule_label" if len(rule_labels) == 1 else "modlog.rules_label"
        embed.add_field(name=tr(locale, label_key), value="\n".join(f"`{item}`" for item in rule_labels), inline=False)
    if decision.linked_action_id:
        embed.add_field(name=tr(locale, "modlog.action_id_label"), value=f"`{decision.linked_action_id}`", inline=False)
    if decision.linked_case_id:
        embed.add_field(name=tr(locale, "ai_review.field_case_id"), value=f"`{decision.linked_case_id}`", inline=False)
    if decision.action_reason:
        embed.add_field(name=tr(locale, "modlog.reason_label"), value=_truncate(decision.action_reason, 900), inline=False)
    return embed


def build_disabled_ai_review_view(decision: AIModerationDecision, *, locale: str | None = None) -> discord.ui.View:
    view = AIModerationReviewView(
        decision_id=decision.id,
        suggested_action=decision.suggested_action,
        include_case_select=True,
        locale=locale,
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
    await target_message.edit(embeds=original_embeds, view=build_disabled_ai_review_view(decision, locale=locale))


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


def _case_options(cases, locale: str | None = None) -> list[discord.SelectOption]:
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
        options.append(discord.SelectOption(label=tr(locale, "ai_review.case_select_empty"), value="__none__"))
    return options


class AICaseSelect(discord.ui.Select):
    def __init__(self, *, decision_id: UUID, cases, locale: str | None = None):
        super().__init__(
            custom_id=_decision_component_id("case", decision_id),
            placeholder=tr(locale, "ai_review.case_select_placeholder"),
            min_values=1,
            max_values=1,
            options=_case_options(cases, locale),
        )
        self.decision_id = decision_id
        self.locale = locale

    async def callback(self, interaction: discord.Interaction):
        if not await _moderator_allowed(interaction):
            await interaction.response.send_message("You need moderation permissions to review AI decisions.", ephemeral=True)
            return
        decision = await _ensure_review_open(interaction, self.decision_id)
        if decision is None:
            return
        if self.values[0] == "__none__":
            await interaction.response.send_message(tr(self.locale, "ai_review.case_select_none_available"), ephemeral=True)
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
    def __init__(self, *, decision_id: UUID, suggested_action: str | None = None, locale: str | None = None):
        options = [
            discord.SelectOption(label=tr(locale, "ai_review.action_watch"), value="watch", description=tr(locale, "ai_review.action_watch_description")),
            discord.SelectOption(label=tr(locale, "ai_review.action_warn"), value="warn", description=tr(locale, "ai_review.action_warn_description")),
            discord.SelectOption(label=tr(locale, "ai_review.action_mute"), value="mute", description=tr(locale, "ai_review.action_mute_description")),
            discord.SelectOption(label=tr(locale, "ai_review.action_kick"), value="kick", description=tr(locale, "ai_review.action_kick_description")),
            discord.SelectOption(label=tr(locale, "ai_review.action_ban"), value="ban", description=tr(locale, "ai_review.action_ban_description")),
            discord.SelectOption(label=tr(locale, "ai_review.action_none"), value="none", description=tr(locale, "ai_review.action_none_description")),
        ]
        for option in options:
            if option.value == suggested_action:
                option.default = True
        super().__init__(
            custom_id=_decision_component_id("action", decision_id),
            placeholder=tr(locale, "ai_review.action_select_placeholder"),
            min_values=1,
            max_values=1,
            options=options,
        )
        self.decision_id = decision_id
        self.locale = locale

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
                    locale=self.locale,
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
                    locale=self.locale,
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
            locale=self.locale,
        )
        await interaction.response.send_message(
            rule_view.content(),
            view=rule_view,
            ephemeral=True,
        )


class AIRuleSelect(discord.ui.Select):
    def __init__(self, *, rules, default_rule_ids: set[str], locale: str | None = None):
        if rules:
            options = _rule_select_options(rules, default_rule_ids)
            max_values = min(len(rules), AI_RULE_SELECTION_LIMIT)
            disabled = False
        else:
            options = [discord.SelectOption(label=tr(locale, "ai_review.rule_select_empty"), value="__none__")]
            max_values = 1
            disabled = True
        super().__init__(
            placeholder=tr(locale, "ai_review.rule_select_placeholder"),
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
        super().__init__(title=tr(view.locale, "ai_review.rule_search_title"))
        self.rule_view = view
        self.query = discord.ui.TextInput(
            label=tr(view.locale, "ai_review.rule_search_label"),
            placeholder=tr(view.locale, "ai_review.rule_search_placeholder"),
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
    def __init__(self, *, locale: str | None = None):
        super().__init__(label=tr(locale, "ai_review.rule_search_button"), style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AIActionRuleSelectionView):
            await interaction.response.send_message("Rule selector expired. Choose the action again.", ephemeral=True)
            return
        await interaction.response.send_modal(AIActionRuleSearchModal(view=view))


class AIActionRulePageButton(discord.ui.Button):
    def __init__(self, *, direction: int, locale: str | None = None):
        label = tr(locale, "ai_review.rule_next") if direction > 0 else tr(locale, "ai_review.rule_previous")
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
    def __init__(self, *, locale: str | None = None):
        super().__init__(label=tr(locale, "ai_review.rule_clear_search"), style=discord.ButtonStyle.secondary, row=1)

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
    def __init__(self, *, locale: str | None = None):
        super().__init__(label=tr(locale, "ai_review.rule_clear_rules"), style=discord.ButtonStyle.danger, row=2)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AIActionRuleSelectionView):
            await interaction.response.send_message("Rule selector expired. Choose the action again.", ephemeral=True)
            return
        view.selected_rule_ids = []
        view.rebuild_items()
        await interaction.response.edit_message(content=view.content(), view=view)


class AIActionRuleConfirmButton(discord.ui.Button):
    def __init__(self, *, locale: str | None = None):
        super().__init__(label=tr(locale, "ai_review.rule_continue"), style=discord.ButtonStyle.primary, row=2)

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
                locale=view.locale,
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
        locale: str | None = None,
    ):
        super().__init__(timeout=300)
        self.decision_id = decision_id
        self.locale = locale
        self.action_type = action_type
        self.rules = list(rules)
        self.default_reason = default_reason
        self.default_duration_minutes = default_duration_minutes
        self.search_query = ""
        self.page = 0
        self.selected_rule_ids = [str(rule.id) for rule in self.rules if str(rule.id) in default_rule_ids]
        self.rule_select = AIRuleSelect(rules=[], default_rule_ids=set(), locale=self.locale)
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
        query_part = tr(self.locale, "ai_review.rule_selection_search", query=self.search_query) if self.search_query else ""
        return tr(
            self.locale,
            "ai_review.rule_selection_content",
            query=query_part,
            page=self.page + 1,
            pages=self.max_page + 1,
            count=filtered_count,
            selected=len(self.selected_rule_ids),
        )

    def rebuild_items(self) -> None:
        self.page = max(0, min(self.page, self.max_page))
        self.clear_items()
        page_rules = self.page_rules()
        self.rule_select = AIRuleSelect(rules=page_rules, default_rule_ids=self.selected_rule_id_set(), locale=self.locale)
        self.add_item(self.rule_select)
        search_button = AIActionRuleSearchButton(locale=self.locale)
        prev_button = AIActionRulePageButton(direction=-1, locale=self.locale)
        prev_button.disabled = self.page <= 0
        next_button = AIActionRulePageButton(direction=1, locale=self.locale)
        next_button.disabled = self.page >= self.max_page
        clear_search_button = AIActionRuleClearSearchButton(locale=self.locale)
        clear_search_button.disabled = not bool(self.search_query)
        clear_selection_button = AIActionRuleClearSelectionButton(locale=self.locale)
        clear_selection_button.disabled = not bool(self.selected_rule_ids)
        self.add_item(search_button)
        self.add_item(prev_button)
        self.add_item(next_button)
        self.add_item(clear_search_button)
        self.add_item(clear_selection_button)
        self.add_item(AIActionRuleConfirmButton(locale=self.locale))


class AIWatchConfirmModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        decision_id: UUID,
        default_reason: str | None,
        locale: str | None = None,
    ):
        super().__init__(title=tr(locale, "ai_review.watch_modal_title"))
        self.decision_id = decision_id
        self.locale = locale
        self.reason = discord.ui.TextInput(
            label=tr(locale, "ai_review.watch_reason_label"),
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
        locale: str | None = None,
    ):
        super().__init__(title=tr(locale, "ai_review.action_modal_title", action=tr(locale, f"ai_review.action_{action_type.value}").lower()))
        self.decision_id = decision_id
        self.locale = locale
        self.action_type = action_type
        self.selected_rule_ids = selected_rule_ids
        self.reason = discord.ui.TextInput(
            label=tr(locale, "ai_review.reason_label"),
            style=discord.TextStyle.paragraph,
            default=_truncate(default_reason, 900),
            max_length=1000,
            required=True,
        )
        self.add_item(self.reason)
        if action_type == ActionType.MUTE:
            self.duration_text = discord.ui.TextInput(
                label=tr(self.locale, "ai_review.duration_label"),
                placeholder=tr(self.locale, "ai_review.duration_placeholder"),
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
    def __init__(self, *, decision_id: UUID, locale: str | None = None):
        super().__init__(
            label=tr(locale, "ai_review.dismiss_button"),
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
    def __init__(self, *, decision_id: UUID, locale: str | None = None):
        super().__init__(
            label=tr(locale, "ai_review.create_case_button"),
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
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        cases = open_cases or []
        self.decision_id = decision_id
        self.locale = locale
        self.add_item(AIDismissButton(decision_id=decision_id, locale=locale))
        self.add_item(AICreateCaseButton(decision_id=decision_id, locale=locale))
        self.add_item(AIActionSelect(decision_id=decision_id, suggested_action=suggested_action, locale=locale))
        should_include_case_select = bool(cases) if include_case_select is None else include_case_select
        if should_include_case_select:
            self.add_item(AICaseSelect(decision_id=decision_id, cases=cases, locale=locale))


async def send_ai_moderation_review(
    *,
    guild: discord.Guild,
    message: discord.Message,
    decision: AIModerationDecision,
) -> bool:
    async with get_async_session() as session:
        ai_settings = await get_or_create_server_ai_settings(session, guild.id, server_name=guild.name)
        mod_settings = await session.get(ServerModerationSettings, guild.id)
        review_channel_id = ai_settings.moderation_review_channel_id or (
            mod_settings.mod_log_channel_id if mod_settings else None
        )
        if not review_channel_id:
            return False
        locale = await _server_locale(session, guild.id)
        rule_labels = await _rule_labels_for_decision(session, decision, locale)
        open_cases = await fetch_open_case_models(
            session=session,
            server_id=guild.id,
            user_id=decision.author_user_id,
            limit=25,
        )

    channel = guild.get_channel(review_channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(review_channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            logger.warning("Cannot resolve AI moderation review channel %s in guild %s: %s", review_channel_id, guild.id, error)
            return False
    send_method = getattr(channel, "send", None)
    if send_method is None:
        return False
    if not _bot_can_send_ai_mod_log(guild, channel):
        logger.warning("Bot cannot write AI moderation review to channel %s in guild %s", getattr(channel, "id", None), guild.id)
        return False
    try:
        sent_message = await send_method(
            embed=build_ai_moderation_embed(decision, message, rule_labels=rule_labels, locale=locale),
            view=AIModerationReviewView(
                decision_id=decision.id,
                open_cases=open_cases,
                suggested_action=decision.suggested_action,
                locale=locale,
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
        locales = (
            await session.exec(
                select(ServerLocalizationSettings).where(
                    ServerLocalizationSettings.server_id.in_({decision.server_id for decision in decisions})
                )
            )
        ).all() if decisions else []
        locale_by_server = {settings.server_id: normalize_locale_code(settings.locale_code) for settings in locales}

    for decision in decisions:
        client.add_view(
            AIModerationReviewView(
                decision_id=decision.id,
                suggested_action=decision.suggested_action,
                include_case_select=True,
                locale=locale_by_server.get(decision.server_id),
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
            author_roles = _message_author_roles(message)
            author_is_admin, author_is_moderator = _message_author_trust_flags(message, author_roles)
            images = ai_images_from_discord_message(
                message,
                include_attachments=settings.moderation_monitor_attachments,
                include_custom_emojis=True,
            )
            reply_context = await _reply_context_payload(message)
            recent_context = await _recent_message_context_payload(session, message)
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
                            author_roles=author_roles,
                            author_is_admin=author_is_admin,
                            author_is_moderator=author_is_moderator,
                            server_locale=locale,
                            bot_user_id=bot_user_id,
                            mentioned_users=_mentioned_user_payload(message),
                            current_bot_mentioned=_current_bot_mentioned(message),
                            answer_flow_invocation=answer_flow_invocation,
                            **reply_context,
                            **recent_context,
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

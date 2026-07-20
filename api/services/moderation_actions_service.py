from datetime import datetime, timedelta, timezone
import json
import logging
import os
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import aliased, selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import (
    ModerationActionLinkedMessageReadModel,
    ModerationActionMessageLinkResultModel,
    ModerationActionCreate,
    ModerationMessageLogReadModel,
    ModerationActionRead,
    ModerationActionSummaryModel,
)
from api.models.moderation_cases import (
    DeletedAttachmentReadModel,
    DeletedMessageAttachmentModel,
    DeletedMessageCreateModel,
    DeletedMessageReadModel,
)
from api.services.discord_guilds import (
    add_guild_member_role,
    ban_guild_member,
    create_channel_message,
    create_direct_message,
    delete_channel_message,
    fetch_guild_channels,
    fetch_guild_member,
    kick_guild_member,
    remove_guild_member_role,
    unban_guild_member,
)
from api.services.moderation_core import (
    build_actor,
    deleted_message_deletion_type,
    ensure_case_writable_for_actions,
    moderation_action_is_reverted,
    naive_utcnow,
    to_deleted_message_read,
    to_moderation_history,
)
from api.services.moderation_import_metadata import action_import_metadata
from api.services.moderation_action_numbers import allocate_moderation_action_number
from api.services.moderation_queries import (
    query_deleted_messages,
    query_deleted_messages_for_action,
    query_moderation_actions,
)
from src.db.models import (
    ActionType,
    AttachmentLog,
    DeletedMessage,
    GlobalUser,
    MessageLog,
    ModerationAction,
    ModerationActionDeletedMessageLink,
    ModerationActionMessageLink,
    ModerationActionRuleCitation,
    ModerationCase,
    ModerationCaseActionLink,
    ModerationCaseRuleCitation,
    ModerationImportSourceItem,
    ModerationRule,
    Server,
    ServerLocalizationSettings,
    ServerModerationSettings,
)
from src.modules.localization.service import normalize_locale_code, tr
from src.modules.moderation.moderation_helpers import (
    check_if_server_exists,
    check_if_user_exists,
    migrate_message_action_links_to_deleted,
)
from src.modules.moderation.mute_management import deactivate_user_mutes

logger = logging.getLogger("api.moderation")

DEFAULT_DASHBOARD_BASE_URL = "https://dashboard.modral.app"


def _truncate(value: str, limit: int = 600) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return f"{value.isoformat()}Z"


def _dashboard_base_url() -> str:
    return (os.getenv("DASHBOARD_BASE_URL") or DEFAULT_DASHBOARD_BASE_URL).rstrip("/")


def _dashboard_action_url(server_id: int, action_id: UUID | str) -> str:
    return f"{_dashboard_base_url()}/dashboard/{server_id}/moderation/actions/{action_id}"


def _dashboard_case_url(server_id: int, case_id: UUID | str) -> str:
    return f"{_dashboard_base_url()}/dashboard/{server_id}/moderation/cases/{case_id}"


def _inline_code(value: object, fallback: str = "unknown") -> str:
    text = str(value if value is not None else fallback).replace("`", "'").strip()
    return f"`{text or fallback}`"


def _markdown_link(label: object, url: str) -> str:
    text = str(label).replace("\n", " ").replace("[", "(").replace("]", ")").strip()
    return f"[{text or url}]({url})"


def _rule_label_from_parts(code: str | None, title: str | None, locale: str | None = None) -> str:
    code = (code or "").strip()
    title = (title or "").strip()
    if code:
        if code.isdigit():
            keycap_code = "".join(f"{digit}\ufe0f\u20e3" for digit in code)
            return f"{tr(locale, 'modlog.rule_label')} {keycap_code}: {title}".strip(": ")
        return f"{code} {title}".strip()
    return title or "Rule"


def _rule_labels_for_action(action: ModerationAction, locale: str | None = None) -> list[str]:
    if action.rule_citations:
        sorted_citations = sorted(
            action.rule_citations,
            key=lambda item: (item.cited_at or datetime.min.replace(tzinfo=None), str(item.id)),
        )
        return [
            _rule_label_from_parts(
                item.rule.code if item.rule is not None else item.rule_code_snapshot,
                item.rule.title if item.rule is not None else item.rule_title_snapshot,
                locale,
            )
            for item in sorted_citations
        ]
    if action.rule is not None:
        return [_rule_label_from_parts(action.rule.code, action.rule.title, locale)]
    return []


def _format_user_for_log(user_id: int, username: str | None, locale: str | None = None) -> str:
    return f"<@{user_id}> ({_inline_code(username or tr(locale, 'modlog.unknown'))}, {_inline_code(user_id)})"


def _reason_without_commentary_suffix(reason: str | None, commentary: str | None) -> str:
    display_reason = (reason or "").strip()
    display_commentary = (commentary or "").strip()
    if not display_reason or not display_commentary:
        return display_reason

    legacy_suffix = f"\nCommentary: {display_commentary}"
    if display_reason.endswith(legacy_suffix):
        return display_reason[: -len(legacy_suffix)].rstrip()
    return display_reason


def _rule_label_compare_values(label: str) -> set[str]:
    normalized = label.strip().casefold().replace("\ufe0f", "").replace("\u20e3", "").replace(":", " ")
    normalized = " ".join(normalized.split())
    values = {normalized} if normalized else set()
    for prefix in ("rule ", "правило "):
        if normalized.startswith(prefix):
            values.add(normalized[len(prefix) :].strip())
    return values


def _display_reason_for_log(reason: str | None, commentary: str | None, rule_labels: list[str]) -> str:
    display_reason = _reason_without_commentary_suffix(reason, commentary)
    normalized_reason = display_reason.strip().casefold()
    rule_reason_values: set[str] = set()
    for label in rule_labels:
        rule_reason_values.update(_rule_label_compare_values(label))
    if normalized_reason and normalized_reason in rule_reason_values:
        return ""
    return display_reason


def _build_action_log_message(
    *,
    action: ModerationAction,
    moderator_username: str | None,
    target_username: str | None,
    locale: str | None = None,
) -> str:
    action_url = _dashboard_action_url(action.server_id, action.id)
    action_type_label = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
    action_label = f"{action_type_label} #{action.action_number}"
    lines = [
        f"**{tr(locale, 'modlog.action_label')}:** {_markdown_link(action_label, action_url)}",
        f"**{tr(locale, 'modlog.target_label')}:** {_format_user_for_log(action.target_user_id, target_username, locale)}",
        f"**{tr(locale, 'modlog.moderator_label')}:** {_format_user_for_log(action.moderator_user_id, moderator_username, locale)}",
    ]

    rule_labels = _rule_labels_for_action(action, locale)
    display_reason = _display_reason_for_log(action.reason, action.commentary, rule_labels)
    if display_reason:
        lines.append(f"**{tr(locale, 'modlog.reason_label')}:** {_truncate(display_reason, limit=1000)}")
    if action.commentary:
        lines.append(f"**{tr(locale, 'modlog.commentary_label')}:** {_truncate(action.commentary, limit=1000)}")

    if rule_labels:
        label_key = "modlog.rule_label" if len(rule_labels) == 1 else "modlog.rules_label"
        lines.append(f"**{tr(locale, label_key)}:** {', '.join(_inline_code(item) for item in rule_labels)}")

    if action.case_id:
        case_label = action.case.title if action.case is not None and action.case.title else str(action.case_id)
        lines.append(
            f"**{tr(locale, 'modlog.case_label')}:** "
            f"{_markdown_link(case_label, _dashboard_case_url(action.server_id, action.case_id))}"
        )
    if action.expires_at:
        lines.append(f"**{tr(locale, 'modlog.expires_at_label')}:** {_inline_code(_format_dt(action.expires_at))}")
    import_metadata = action_import_metadata(action, locale=locale)
    if import_metadata["created_at_label"]:
        lines.append(f"**{tr(locale, 'modlog.created_at_label')}:** {import_metadata['created_at_label']}")
    lines.append(
        f"**{tr(locale, 'modlog.action_number_label')}:** "
        f"{_markdown_link(f'#{action.action_number}', action_url)}"
    )

    message = f"{tr(locale, 'modlog.header')}\n" + "\n".join(lines)
    return _truncate(message, limit=1900)



def _action_log_color(action_type: ActionType) -> int:
    if action_type == ActionType.WARN:
        return 0xF2C94C
    if action_type == ActionType.MUTE:
        return 0xEB5757
    if action_type == ActionType.BAN:
        return 0x2F3136
    if action_type == ActionType.KICK:
        return 0xF2994A
    return 0x5865F2


def _embed_field(name: str, value: str, inline: bool = False) -> dict:
    return {
        "name": _truncate(name, limit=256),
        "value": _truncate(value or "-", limit=1024),
        "inline": inline,
    }


def _build_action_log_embed(
    *,
    action: ModerationAction,
    moderator_username: str | None,
    target_username: str | None,
    locale: str | None = None,
) -> dict:
    action_url = _dashboard_action_url(action.server_id, action.id)
    action_type_label = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
    action_label = f"{action_type_label} #{action.action_number}"
    rule_labels = _rule_labels_for_action(action, locale)
    display_reason = _display_reason_for_log(action.reason, action.commentary, rule_labels)
    fields = [
        _embed_field(
            tr(locale, "modlog.target_label"),
            _format_user_for_log(action.target_user_id, target_username, locale),
            inline=True,
        ),
        _embed_field(
            tr(locale, "modlog.moderator_label"),
            _format_user_for_log(action.moderator_user_id, moderator_username, locale),
            inline=True,
        ),
    ]

    if rule_labels:
        label_key = "modlog.rule_label" if len(rule_labels) == 1 else "modlog.rules_label"
        fields.append(_embed_field(tr(locale, label_key), "\n".join(_inline_code(item) for item in rule_labels)))
    if display_reason:
        fields.append(_embed_field(tr(locale, "modlog.reason_label"), display_reason))
    if action.commentary:
        fields.append(_embed_field(tr(locale, "modlog.commentary_label"), action.commentary))
    if action.case_id:
        case_label = action.case.title if action.case is not None and action.case.title else str(action.case_id)
        fields.append(
            _embed_field(
                tr(locale, "modlog.case_label"),
                _markdown_link(case_label, _dashboard_case_url(action.server_id, action.case_id)),
            )
        )
    if action.expires_at:
        fields.append(_embed_field(tr(locale, "modlog.expires_at_label"), _format_dt(action.expires_at), inline=True))
    import_metadata = action_import_metadata(action, locale=locale)
    if import_metadata["created_at_label"]:
        fields.append(
            _embed_field(
                tr(locale, "modlog.created_at_label"),
                import_metadata["created_at_label"],
                inline=False,
            )
        )

    created_at = getattr(action, "created_at", None)
    embed = {
        "title": f"{tr(locale, 'modlog.title')}: {action_label}",
        "url": action_url,
        "color": _action_log_color(action.action_type),
        "fields": fields,
        "footer": {"text": f"{tr(locale, 'modlog.action_number_label')}: #{action.action_number}"},
    }
    if created_at is not None and import_metadata["source_created_at_known"]:
        embed["timestamp"] = _format_dt(created_at)
    return embed


def _build_action_revert_log_embed(
    *,
    action: ModerationAction,
    moderator_user_id: int,
    moderator_username: str | None,
    target_username: str | None,
    reason: str,
    discord_changed: bool,
    locale: str | None = None,
) -> dict:
    action_url = _dashboard_action_url(action.server_id, action.id)
    action_type = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
    fields = [
        _embed_field(
            tr(locale, "modlog.target_label"),
            _format_user_for_log(action.target_user_id, target_username, locale),
            inline=True,
        ),
        _embed_field(
            tr(locale, "modlog.moderator_label"),
            _format_user_for_log(moderator_user_id, moderator_username, locale),
            inline=True,
        ),
        _embed_field(
            tr(locale, "modlog.original_action_label"),
            _markdown_link(f"{action_type} #{action.action_number}", action_url),
            inline=False,
        ),
        _embed_field(tr(locale, "modlog.reason_label"), reason, inline=False),
        _embed_field(tr(locale, "modlog.reverted_label"), f"`{discord_changed}`", inline=True),
    ]
    return {
        "title": f"{tr(locale, 'modlog.title')}: {tr(locale, 'modlog.action_revert')}",
        "url": action_url,
        "color": 0x5865F2,
        "fields": fields,
        "footer": {"text": f"{tr(locale, 'modlog.action_number_label')}: #{action.action_number}"},
        "timestamp": _format_dt(naive_utcnow()),
    }


async def _resolve_username(session: AsyncSession, user_id: int) -> str | None:
    user = await session.get(GlobalUser, user_id)
    if not user:
        return None
    return user.username


def _parse_rule_id_list(raw_rule_ids: list[str]) -> list[UUID]:
    parsed: list[UUID] = []
    seen: set[UUID] = set()
    for raw_id in raw_rule_ids:
        if not raw_id:
            continue
        try:
            parsed_id = UUID(str(raw_id))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid rule id: {raw_id}",
            )
        if parsed_id in seen:
            continue
        seen.add(parsed_id)
        parsed.append(parsed_id)
    return parsed


async def _resolve_rules_for_server(
    session: AsyncSession,
    server_id: int,
    rule_ids: list[UUID],
) -> list[ModerationRule]:
    if not rule_ids:
        return []
    rules = (
        await session.exec(
            select(ModerationRule).where(
                ModerationRule.server_id == server_id,
                ModerationRule.id.in_(rule_ids),
                ModerationRule.is_active.is_(True),
            )
        )
    ).all()
    by_id = {rule.id: rule for rule in rules}
    missing = [rule_id for rule_id in rule_ids if rule_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Moderation rule not found",
        )
    return [by_id[rule_id] for rule_id in rule_ids]


async def _upsert_action_rule_citations(
    session: AsyncSession,
    action: ModerationAction,
    rules: list[ModerationRule],
) -> None:
    if not rules:
        return

    existing = (
        await session.exec(
            select(ModerationActionRuleCitation).where(
                ModerationActionRuleCitation.action_id == action.id,
                ModerationActionRuleCitation.rule_id.in_([rule.id for rule in rules]),
            )
        )
    ).all()
    existing_rule_ids = {item.rule_id for item in existing if item.rule_id is not None}

    for rule in rules:
        if rule.id in existing_rule_ids:
            continue
        session.add(
            ModerationActionRuleCitation(
                action_id=action.id,
                rule_id=rule.id,
                server_id=action.server_id,
                rule_code_snapshot=rule.code,
                rule_title_snapshot=rule.title,
                cited_at=action.created_at,
            )
        )
    await session.flush()


async def _upsert_case_rule_citations(
    session: AsyncSession,
    case_id: UUID,
    server_id: int,
    rules: list[ModerationRule],
    cited_at: datetime,
) -> None:
    if not rules:
        return
    existing = (
        await session.exec(
            select(ModerationCaseRuleCitation).where(
                ModerationCaseRuleCitation.case_id == case_id,
                ModerationCaseRuleCitation.rule_id.in_([rule.id for rule in rules]),
            )
        )
    ).all()
    existing_rule_ids = {item.rule_id for item in existing if item.rule_id is not None}
    for rule in rules:
        if rule.id in existing_rule_ids:
            continue
        session.add(
            ModerationCaseRuleCitation(
                case_id=case_id,
                rule_id=rule.id,
                server_id=server_id,
                rule_code_snapshot=rule.code,
                rule_title_snapshot=rule.title,
                cited_at=cited_at,
            )
        )
    await session.flush()


async def _load_action_for_read(session: AsyncSession, action_id: UUID) -> ModerationAction:
    action = (
        await session.exec(
            select(ModerationAction)
            .where(ModerationAction.id == action_id)
            .options(
                selectinload(ModerationAction.global_user_moderator),
                selectinload(ModerationAction.global_user_target),
                selectinload(ModerationAction.rule),
                selectinload(ModerationAction.case),
                selectinload(ModerationAction.rule_citations).selectinload(ModerationActionRuleCitation.rule),
                selectinload(ModerationAction.import_source_items),
            )
        )
    ).one_or_none()
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")
    return action


def _to_action_summary(
    action_id: UUID,
    action_number: int,
    action_type,
    server_id: int,
    target_user_id: int,
    moderator_user_id: int,
    reason: str,
    case_id: UUID | None,
    case_title: str | None,
    created_at: datetime,
    expires_at: datetime | None,
    is_active: bool,
    target_username: str | None,
    moderator_username: str | None,
    rules_count: int,
    linked_messages_count: int,
    deleted_messages_count: int,
    import_metadata: dict | None = None,
) -> ModerationActionSummaryModel:
    import_metadata = import_metadata or {}
    return ModerationActionSummaryModel(
        id=str(action_id),
        action_number=action_number,
        action_type=action_type,
        server_id=str(server_id),
        target_user_id=str(target_user_id),
        target_user_username=target_username or str(target_user_id),
        moderator_user_id=str(moderator_user_id),
        moderator_username=moderator_username or str(moderator_user_id),
        reason=reason,
        case_id=str(case_id) if case_id else None,
        case_title=case_title,
        created_at=created_at,
        created_at_label=import_metadata.get("created_at_label"),
        import_source=import_metadata.get("import_source"),
        import_source_label=import_metadata.get("import_source_label"),
        source_created_at_known=import_metadata.get("source_created_at_known", True),
        source_created_at_note=import_metadata.get("source_created_at_note"),
        expires_at=expires_at,
        is_active=is_active,
        is_reverted=moderation_action_is_reverted(action_type, is_active),
        rules_count=rules_count,
        linked_messages_count=linked_messages_count,
        deleted_messages_count=deleted_messages_count,
    )


async def _import_metadata_for_action_ids(
    session: AsyncSession,
    action_ids: list[UUID],
) -> dict[UUID, dict]:
    if not action_ids:
        return {}
    items = (
        await session.exec(
            select(ModerationImportSourceItem).where(
                ModerationImportSourceItem.moderation_action_id.in_(action_ids),
            )
        )
    ).all()
    by_action_id: dict[UUID, list[ModerationImportSourceItem]] = {}
    for item in items:
        if item.moderation_action_id is None:
            continue
        by_action_id.setdefault(item.moderation_action_id, []).append(item)

    result: dict[UUID, dict] = {}
    for action_id, source_items in by_action_id.items():
        lightweight_action = type("ImportedActionProxy", (), {"import_source_items": source_items})()
        result[action_id] = action_import_metadata(lightweight_action)
    return result


def build_action_log_components(
    action: ModerationAction,
    locale: str | None = None,
) -> list[dict]:
    action_url = _dashboard_action_url(action.server_id, action.id)
    buttons = [
        {
            "type": 2,
            "style": 5,
            "label": tr(locale, "action.open_dashboard"),
            "url": action_url,
        },
        {
            "type": 2,
            "style": 5,
            "label": tr(locale, "action.add_info_dashboard"),
            "url": action_url,
        },
    ]
    if action.is_active and action.action_type in {
        ActionType.WARN,
        ActionType.MUTE,
        ActionType.BAN,
    }:
        buttons.append(
            {
                "type": 2,
                "style": 4,
                "label": tr(locale, "action.revert_button"),
                "custom_id": f"mod-action:revert:{action.id}",
            }
        )
    return [{"type": 1, "components": buttons}]


async def _send_action_to_mod_log(
    session: AsyncSession,
    action: ModerationAction,
) -> None:
    settings = await session.get(ServerModerationSettings, action.server_id)
    if not settings or not settings.mod_log_channel_id:
        return

    moderator_username = await _resolve_username(session, action.moderator_user_id)
    target_username = await _resolve_username(session, action.target_user_id)
    locale = await _get_server_locale(session=session, server_id=action.server_id)
    embed = _build_action_log_embed(
        action=action,
        moderator_username=moderator_username,
        target_username=target_username,
        locale=locale,
    )

    try:
        await create_channel_message(
            channel_id=settings.mod_log_channel_id,
            embeds=[embed],
            components=build_action_log_components(action, locale),
        )
    except Exception as error:
        logger.warning(
            "Failed to send moderation action log to channel %s for server %s: %s",
            settings.mod_log_channel_id,
            action.server_id,
            error,
        )



def _rules_label(rules: list[ModerationRule], fallback_reason: str, locale: str | None = None) -> str:
    if not rules:
        return fallback_reason
    primary_rule = rules[0]
    return _rule_label_from_parts(primary_rule.code, primary_rule.title, locale) or fallback_reason


async def _get_server_locale(session: AsyncSession, server_id: int) -> str:
    settings = await session.get(ServerLocalizationSettings, server_id)
    return normalize_locale_code(settings.locale_code if settings else None)


def _format_dm_expiry(expires_at: datetime) -> str:
    normalized = expires_at
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return f"<t:{int(normalized.timestamp())}:F> (<t:{int(normalized.timestamp())}:R>)"


async def _send_action_dm_for_action(
    session: AsyncSession,
    action: ModerationActionCreate,
    action_number: int,
    resolved_reason: str,
    resolved_rules: list[ModerationRule],
    resolved_commentary: str | None,
) -> None:
    try:
        locale = await _get_server_locale(session=session, server_id=action.server_id)
        message = tr(
            locale,
            f"action.dm_{action.action_type.value}_body",
            action_number=action_number,
            server_name=action.server_name,
            rule_label=_rules_label(resolved_rules, fallback_reason=resolved_reason, locale=locale),
        )
        if resolved_commentary:
            message += tr(locale, "action.dm_commentary", commentary=resolved_commentary)
        if action.expires_at is not None:
            message += tr(
                locale,
                "action.dm_expires",
                expires_at=_format_dm_expiry(action.expires_at),
            )
        await create_direct_message(
            user_id=action.target_user_id,
            content=_truncate(message, limit=1900),
        )
    except Exception as error:
        logger.warning(
            "Failed to DM %s action #%s to user %s in server %s: %s",
            action.action_type.value,
            action_number,
            action.target_user_id,
            action.server_id,
            error,
        )


async def send_action_revert_dm(
    *,
    session: AsyncSession,
    action: ModerationAction,
    reason: str,
) -> None:
    try:
        locale = await _get_server_locale(session=session, server_id=action.server_id)
        server = await session.get(Server, action.server_id)
        server_name = server.server_name if server is not None else str(action.server_id)
        message = tr(
            locale,
            "action.dm_reverted_body",
            action_name=tr(locale, f"action.dm_type_{action.action_type.value}"),
            action_number=action.action_number,
            server_name=server_name,
            reason=reason,
        )
        await create_direct_message(
            user_id=action.target_user_id,
            content=_truncate(message, limit=1900),
        )
    except Exception as error:
        logger.warning(
            "Failed to DM revert of %s action #%s to user %s in server %s: %s",
            action.action_type.value,
            action.action_number,
            action.target_user_id,
            action.server_id,
            error,
        )


async def _prepare_discord_action_effects(
    session: AsyncSession,
    action: ModerationActionCreate,
) -> int | None:
    if action.action_type != ActionType.MUTE:
        return None

    settings = await session.get(ServerModerationSettings, action.server_id)
    if not settings or not settings.mute_role_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mute role is not configured for this server",
        )

    await deactivate_user_mutes(session=session, server_id=action.server_id, user_id=action.target_user_id)
    return settings.mute_role_id


async def _apply_mute_effect_for_action(
    action: ModerationActionCreate,
    mute_role_id: int,
) -> None:
    await add_guild_member_role(
        server_id=action.server_id,
        user_id=action.target_user_id,
        role_id=mute_role_id,
    )


async def _apply_discord_action_effects(
    session: AsyncSession,
    action: ModerationActionCreate,
    resolved_reason: str,
    resolved_rules: list[ModerationRule],
    resolved_commentary: str | None,
    action_number: int,
    mute_role_id: int | None = None,
) -> None:
    if action.action_type in {ActionType.WARN, ActionType.KICK, ActionType.BAN}:
        await _send_action_dm_for_action(
            session=session,
            action=action,
            action_number=action_number,
            resolved_reason=resolved_reason,
            resolved_rules=resolved_rules,
            resolved_commentary=resolved_commentary,
        )

    if action.action_type == ActionType.WARN:
        return
    elif action.action_type == ActionType.MUTE:
        if mute_role_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Mute role is not configured for this server",
            )
        await _apply_mute_effect_for_action(action=action, mute_role_id=mute_role_id)
        await _send_action_dm_for_action(
            session=session,
            action=action,
            action_number=action_number,
            resolved_reason=resolved_reason,
            resolved_rules=resolved_rules,
            resolved_commentary=resolved_commentary,
        )
    elif action.action_type == ActionType.BAN:
        await ban_guild_member(
            server_id=action.server_id,
            user_id=action.target_user_id,
            delete_message_seconds=0,
        )
    elif action.action_type == ActionType.KICK:
        await kick_guild_member(server_id=action.server_id, user_id=action.target_user_id)


async def create_action(
    session: AsyncSession,
    action: ModerationActionCreate,
    moderator_user_id: int,
    case_id: UUID | None = None,
    apply_discord_effects: bool = False,
) -> ModerationAction:
    mock_user = type(
        "MockUser",
        (),
        {
            "id": action.target_user_id,
            "name": action.target_user_name,
            "joined_at": action.target_user_joined_at,
            "nick": action.target_user_server_nickname,
        },
    )()
    mock_server = type("MockServer", (), {"id": action.server_id, "name": action.server_name})()

    await check_if_server_exists(mock_server, session)
    await check_if_user_exists(mock_user, mock_server, session)

    resolved_commentary = action.commentary.strip() if action.commentary else None
    resolved_reason = action.reason.strip() if action.reason else None
    parsed_rule_ids = _parse_rule_id_list(action.rule_ids or [])
    if action.rule_id is not None:
        parsed_rule_ids = [action.rule_id, *[item for item in parsed_rule_ids if item != action.rule_id]]

    resolved_rules = await _resolve_rules_for_server(
        session=session,
        server_id=action.server_id,
        rule_ids=parsed_rule_ids,
    )
    resolved_rule_id = resolved_rules[0].id if resolved_rules else None

    if resolved_rules:
        primary_rule = resolved_rules[0]
        base_reason = f"{primary_rule.code} {primary_rule.title}".strip() if primary_rule.code else primary_rule.title
        resolved_reason = base_reason

    if not resolved_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either reason or rule_id must be provided",
        )

    resolved_case_id: UUID | None = case_id
    if resolved_case_id is None and action.case_id:
        try:
            resolved_case_id = UUID(str(action.case_id))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid case_id",
            )

    if resolved_case_id is not None:
        linked_case = await session.get(ModerationCase, resolved_case_id)
        if not linked_case or linked_case.server_id != action.server_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Moderation case not found",
            )
        ensure_case_writable_for_actions(linked_case)

    mute_role_id: int | None = None
    if apply_discord_effects:
        mute_role_id = await _prepare_discord_action_effects(session=session, action=action)

    action_number = await allocate_moderation_action_number(session, action.server_id)
    db_action = ModerationAction(
        action_number=action_number,
        action_type=action.action_type,
        moderator_user_id=moderator_user_id,
        reason=resolved_reason,
        rule_id=resolved_rule_id,
        case_id=resolved_case_id,
        commentary=resolved_commentary,
        expires_at=action.expires_at,
        target_user_id=action.target_user_id,
        server_id=action.server_id,
    )
    session.add(db_action)
    await session.flush()

    await _upsert_action_rule_citations(
        session=session,
        action=db_action,
        rules=resolved_rules,
    )

    if resolved_case_id is not None:
        existing_link = (
            await session.exec(
                select(ModerationCaseActionLink).where(
                    ModerationCaseActionLink.case_id == resolved_case_id,
                    ModerationCaseActionLink.moderation_action_id == db_action.id,
                )
            )
        ).first()
        if not existing_link:
            session.add(
                ModerationCaseActionLink(
                    case_id=resolved_case_id,
                    moderation_action_id=db_action.id,
                    linked_by_user_id=moderator_user_id,
                    linked_at=db_action.created_at,
                )
            )
            await session.flush()
        await _upsert_case_rule_citations(
            session=session,
            case_id=resolved_case_id,
            server_id=action.server_id,
            rules=resolved_rules,
            cited_at=db_action.created_at,
        )

    await _delete_and_link_cleanup_messages_for_action(
        session=session,
        action=action,
        action_id=db_action.id,
        moderator_user_id=moderator_user_id,
    )

    db_action = await _load_action_for_read(session=session, action_id=db_action.id)

    if apply_discord_effects:
        await _apply_discord_action_effects(
            session=session,
            action=action,
            resolved_reason=resolved_reason,
            resolved_rules=resolved_rules,
            resolved_commentary=resolved_commentary,
            action_number=db_action.action_number,
            mute_role_id=mute_role_id,
        )

    await _send_action_to_mod_log(session=session, action=db_action)
    return db_action


async def list_action_summaries(
    session: AsyncSession,
    server_id: int,
    target_user_id: int | None = None,
    limit: int = 500,
    action_types: set[ActionType] | None = None,
    is_active: bool | None = None,
) -> list[ModerationActionSummaryModel]:
    target_user = aliased(GlobalUser)
    moderator_user = aliased(GlobalUser)

    statement = (
        select(
            ModerationAction.id,
            ModerationAction.action_number,
            ModerationAction.action_type,
            ModerationAction.server_id,
            ModerationAction.target_user_id,
            ModerationAction.moderator_user_id,
            ModerationAction.reason,
            ModerationAction.case_id,
            ModerationCase.title.label("case_title"),
            ModerationAction.created_at,
            ModerationAction.expires_at,
            ModerationAction.is_active,
            target_user.username.label("target_username"),
            moderator_user.username.label("moderator_username"),
            func.count(func.distinct(ModerationActionRuleCitation.id)).label("rules_count"),
            func.count(func.distinct(ModerationActionMessageLink.id)).label("linked_messages_count"),
            func.count(func.distinct(ModerationActionDeletedMessageLink.id)).label("deleted_messages_count"),
        )
        .join(target_user, target_user.discord_id == ModerationAction.target_user_id, isouter=True)
        .join(moderator_user, moderator_user.discord_id == ModerationAction.moderator_user_id, isouter=True)
        .outerjoin(ModerationCase, ModerationCase.id == ModerationAction.case_id)
        .outerjoin(ModerationActionRuleCitation, ModerationActionRuleCitation.action_id == ModerationAction.id)
        .outerjoin(
            ModerationActionMessageLink,
            ModerationActionMessageLink.moderation_action_id == ModerationAction.id,
        )
        .outerjoin(
            ModerationActionDeletedMessageLink,
            ModerationActionDeletedMessageLink.moderation_action_id == ModerationAction.id,
        )
        .where(ModerationAction.server_id == server_id)
    )
    if target_user_id is not None:
        statement = statement.where(ModerationAction.target_user_id == target_user_id)
    if action_types:
        statement = statement.where(ModerationAction.action_type.in_(list(action_types)))
    if is_active is not None:
        statement = statement.where(ModerationAction.is_active == is_active)

    statement = (
        statement.group_by(
            ModerationAction.id,
            ModerationAction.action_number,
            ModerationAction.action_type,
            ModerationAction.server_id,
            ModerationAction.target_user_id,
            ModerationAction.moderator_user_id,
            ModerationAction.reason,
            ModerationAction.case_id,
            ModerationCase.title,
            ModerationAction.created_at,
            ModerationAction.expires_at,
            ModerationAction.is_active,
            target_user.username,
            moderator_user.username,
        )
        .order_by(ModerationAction.created_at.desc())
        .limit(limit)
    )
    rows = (await session.exec(statement)).all()
    metadata_by_action_id = await _import_metadata_for_action_ids(session, [row[0] for row in rows])
    return [
        _to_action_summary(
            action_id=row[0],
            action_number=row[1],
            action_type=row[2],
            server_id=row[3],
            target_user_id=row[4],
            moderator_user_id=row[5],
            reason=row[6],
            case_id=row[7],
            case_title=row[8],
            created_at=row[9],
            expires_at=row[10],
            is_active=row[11],
            target_username=row[12],
            moderator_username=row[13],
            rules_count=int(row[14] or 0),
            linked_messages_count=int(row[15] or 0),
            deleted_messages_count=int(row[16] or 0),
            import_metadata=metadata_by_action_id.get(row[0]),
        )
        for row in rows
    ]


async def get_action_details(
    session: AsyncSession,
    server_id: int,
    action_id: UUID,
) -> ModerationActionRead:
    action = await _load_action_for_read(session=session, action_id=action_id)
    if action.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")
    return to_moderation_history([action])[0]


async def _apply_discord_revert_for_action(
    *,
    session: AsyncSession,
    action: ModerationAction,
) -> bool:
    if action.action_type == ActionType.WARN:
        return False

    if action.action_type == ActionType.MUTE:
        settings = await session.get(ServerModerationSettings, action.server_id)
        if not settings or not settings.mute_role_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Mute role is not configured for this server",
            )
        member = await fetch_guild_member(action.server_id, action.target_user_id)
        member_role_ids = {int(role_id) for role_id in (member or {}).get("roles", [])}
        if int(settings.mute_role_id) not in member_role_ids:
            return False
        try:
            await remove_guild_member_role(
                server_id=action.server_id,
                user_id=action.target_user_id,
                role_id=settings.mute_role_id,
            )
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                return False
            raise
        return True

    if action.action_type == ActionType.BAN:
        try:
            await unban_guild_member(action.server_id, action.target_user_id)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                return False
            raise
        return True

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="This action type cannot be reverted from Discord",
    )


async def _send_action_revert_to_mod_log(
    *,
    session: AsyncSession,
    action: ModerationAction,
    moderator_user_id: int,
    reason: str,
    discord_changed: bool,
) -> None:
    settings = await session.get(ServerModerationSettings, action.server_id)
    if not settings or not settings.mod_log_channel_id:
        return

    locale = await _get_server_locale(session=session, server_id=action.server_id)
    moderator_username = await _resolve_username(session, moderator_user_id)
    target_username = await _resolve_username(session, action.target_user_id)
    embed = _build_action_revert_log_embed(
        action=action,
        moderator_user_id=moderator_user_id,
        moderator_username=moderator_username,
        target_username=target_username,
        reason=reason,
        discord_changed=discord_changed,
        locale=locale,
    )
    try:
        await create_channel_message(channel_id=settings.mod_log_channel_id, embeds=[embed])
    except Exception as error:
        logger.warning(
            "Failed to send moderation action revert log to channel %s for server %s: %s",
            settings.mod_log_channel_id,
            action.server_id,
            error,
        )


async def revert_action(
    *,
    session: AsyncSession,
    server_id: int,
    action_id: UUID,
    moderator_user_id: int,
    reason: str | None = None,
) -> tuple[ModerationActionRead, bool]:
    action = await _load_action_for_read(session=session, action_id=action_id)
    if action.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")
    if not action.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This action is already inactive")

    locale = await _get_server_locale(session=session, server_id=action.server_id)
    moderator_username = await _resolve_username(session, moderator_user_id)
    resolved_reason = (reason or "").strip() or tr(
        locale,
        "modlog.reason_reverted_by_dashboard",
        moderator=_format_user_for_log(moderator_user_id, moderator_username, locale),
    )
    discord_changed = await _apply_discord_revert_for_action(session=session, action=action)

    action.is_active = False
    action.expires_at = action.expires_at or naive_utcnow()
    session.add(action)
    await session.flush()

    await send_action_revert_dm(
        session=session,
        action=action,
        reason=resolved_reason,
    )
    await _send_action_revert_to_mod_log(
        session=session,
        action=action,
        moderator_user_id=moderator_user_id,
        reason=resolved_reason,
        discord_changed=discord_changed,
    )

    action = await _load_action_for_read(session=session, action_id=action_id)
    return to_moderation_history([action])[0], discord_changed


async def get_user_history_summary_by_search(
    session: AsyncSession,
    server_id: int,
    search: str,
    limit: int = 500,
) -> list[ModerationActionSummaryModel]:
    if search.isdigit():
        target_user_id = int(search)
    else:
        user = (await session.exec(select(GlobalUser).where(GlobalUser.username == search))).one_or_none()
        if not user:
            return []
        target_user_id = user.discord_id
    return await list_action_summaries(
        session=session,
        server_id=server_id,
        target_user_id=target_user_id,
        limit=limit,
    )


async def get_user_history_by_search(
    session: AsyncSession,
    server_id: int,
    search: str,
) -> list[ModerationActionRead]:
    if search.isdigit():
        target_user_id = int(search)
    else:
        user = (await session.exec(select(GlobalUser).where(GlobalUser.username == search))).one_or_none()
        if not user:
            return []
        target_user_id = user.discord_id

    actions = await query_moderation_actions(
        session=session,
        server_id=server_id,
        target_user_id=target_user_id,
    )
    return to_moderation_history(actions)


async def get_server_history(
    session: AsyncSession,
    server_id: int,
    target_user_id: str | None = None,
    limit: int = 500,
) -> list[ModerationActionRead]:
    actions = await query_moderation_actions(
        session=session,
        server_id=server_id,
        target_user_id=int(target_user_id) if target_user_id else None,
        limit=limit,
    )
    return to_moderation_history(actions)


async def get_server_history_summary(
    session: AsyncSession,
    server_id: int,
    target_user_id: str | None = None,
    limit: int = 500,
) -> list[ModerationActionSummaryModel]:
    return await list_action_summaries(
        session=session,
        server_id=server_id,
        target_user_id=int(target_user_id) if target_user_id else None,
        limit=limit,
    )


async def _get_channel_names(server_id: int) -> dict[int, str]:
    try:
        channels = await fetch_guild_channels(server_id)
        return {int(ch["id"]): ch.get("name", "") for ch in channels}
    except Exception:
        return {}


async def list_message_logs_for_server(
    session: AsyncSession,
    server_id: int,
    user_id: str | None = None,
    channel_id: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[ModerationMessageLogReadModel]:
    statement = select(MessageLog).where(MessageLog.server_id == server_id)
    if user_id:
        statement = statement.where(MessageLog.user_id == int(user_id))
    if channel_id:
        statement = statement.where(MessageLog.channel_id == int(channel_id))
    if since:
        statement = statement.where(MessageLog.created_at >= since)
    statement = statement.order_by(MessageLog.created_at.desc(), MessageLog.message_id.desc()).limit(limit)
    messages = (await session.exec(statement)).all()
    channel_names = await _get_channel_names(server_id)
    return [
        ModerationMessageLogReadModel(
            message_id=str(message.message_id),
            server_id=str(message.server_id),
            channel_id=str(message.channel_id),
            channel_name=channel_names.get(message.channel_id),
            author_user_id=str(message.user_id),
            content=message.content,
            created_at=message.created_at,
        )
        for message in messages
    ]


def _to_linked_message_read(
    link: ModerationActionMessageLink,
    message: MessageLog,
    *,
    channel_name: str | None = None,
) -> ModerationActionLinkedMessageReadModel:
    return ModerationActionLinkedMessageReadModel(
        message_id=str(message.message_id),
        server_id=str(message.server_id),
        channel_id=str(message.channel_id),
        channel_name=channel_name,
        author_user_id=str(message.user_id),
        content=message.content,
        created_at=message.created_at,
        linked_by_user_id=str(link.linked_by_user_id),
        linked_at=link.linked_at,
    )


async def link_message_to_action(
    session: AsyncSession,
    *,
    action_id: UUID,
    message_id: int,
    linked_by_user_id: int,
) -> ModerationActionMessageLinkResultModel:
    action = await session.get(ModerationAction, action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    await build_actor(session, action.server_id, linked_by_user_id, require_membership=True)
    message = (
        await session.exec(
            select(MessageLog).where(
                MessageLog.message_id == message_id,
                MessageLog.server_id == action.server_id,
            )
        )
    ).first()
    if message is not None:
        existing = (
            await session.exec(
                select(ModerationActionMessageLink).where(
                    ModerationActionMessageLink.moderation_action_id == action_id,
                    ModerationActionMessageLink.message_id == message_id,
                )
            )
        ).first()
        if existing is None:
            session.add(
                ModerationActionMessageLink(
                    moderation_action_id=action_id,
                    message_id=message.message_id,
                    server_id=message.server_id,
                    channel_id=message.channel_id,
                    author_user_id=message.user_id,
                    linked_by_user_id=linked_by_user_id,
                )
            )
            await session.flush()
        return ModerationActionMessageLinkResultModel(state="live", message_id=str(message_id))

    deleted_message = (
        await session.exec(
            select(DeletedMessage)
            .where(
                DeletedMessage.message_id == message_id,
                DeletedMessage.server_id == action.server_id,
            )
            .order_by(DeletedMessage.deleted_at.desc())
        )
    ).first()
    if deleted_message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message is not available in the live or deleted message archive",
        )
    await link_existing_deleted_message_to_action(
        session=session,
        action_id=action_id,
        deleted_message_id=deleted_message.id,
        linked_by_user_id=linked_by_user_id,
    )
    return ModerationActionMessageLinkResultModel(state="deleted", message_id=str(message_id))


async def get_linked_messages_for_action(
    session: AsyncSession,
    action_id: UUID,
) -> list[ModerationActionLinkedMessageReadModel]:
    action = await session.get(ModerationAction, action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    rows = (
        await session.exec(
            select(ModerationActionMessageLink, MessageLog)
            .join(MessageLog, MessageLog.message_id == ModerationActionMessageLink.message_id)
            .where(ModerationActionMessageLink.moderation_action_id == action_id)
            .order_by(MessageLog.created_at.desc(), MessageLog.message_id.desc())
        )
    ).all()
    channel_names = await _get_channel_names(action.server_id)
    return [
        _to_linked_message_read(link, message, channel_name=channel_names.get(message.channel_id))
        for link, message in rows
    ]


async def _message_logs_for_action_cleanup(
    session: AsyncSession,
    action: ModerationActionCreate,
) -> list[MessageLog]:
    cleanup = action.message_cleanup
    if cleanup is None:
        return []

    collected: dict[int, MessageLog] = {}
    if cleanup.message_ids:
        explicit_ids = [int(item) for item in cleanup.message_ids]
        explicit_rows = (
            await session.exec(
                select(MessageLog).where(
                    MessageLog.server_id == action.server_id,
                    MessageLog.user_id == action.target_user_id,
                    MessageLog.message_id.in_(explicit_ids),
                )
            )
        ).all()
        for row in explicit_rows:
            collected[row.message_id] = row

    if cleanup.recent_period_minutes is not None:
        since = naive_utcnow() - timedelta(minutes=cleanup.recent_period_minutes)
        recent_statement = select(MessageLog).where(
            MessageLog.server_id == action.server_id,
            MessageLog.user_id == action.target_user_id,
            MessageLog.created_at >= since,
        )
        if cleanup.channel_ids:
            recent_statement = recent_statement.where(
                MessageLog.channel_id.in_([int(item) for item in cleanup.channel_ids])
            )
        recent_statement = recent_statement.order_by(
            MessageLog.created_at.desc(),
            MessageLog.message_id.desc(),
        ).limit(cleanup.recent_limit)
        recent_rows = (await session.exec(recent_statement)).all()
        for row in recent_rows:
            collected[row.message_id] = row

    return sorted(collected.values(), key=lambda item: (item.created_at, item.message_id), reverse=True)


async def _move_deleted_message_logs_to_action(
    session: AsyncSession,
    *,
    messages: list[MessageLog],
    action_id: UUID,
    deleted_by_user_id: int,
) -> int:
    if not messages:
        return 0

    message_ids = [message.message_id for message in messages]
    attachment_rows = (
        await session.exec(select(AttachmentLog).where(AttachmentLog.message_id.in_(message_ids)))
    ).all()
    attachments_by_message_id: dict[int, list[AttachmentLog]] = {}
    for attachment in attachment_rows:
        attachments_by_message_id.setdefault(attachment.message_id, []).append(attachment)

    deleted_at = naive_utcnow()
    moved_count = 0
    for message in messages:
        attachments = attachments_by_message_id.get(message.message_id, [])
        attachments_json = (
            json.dumps(
                [
                    {
                        "storage_key": attachment.storage_key,
                        "file_name": attachment.file_name,
                        "content_type": attachment.content_type,
                    }
                    for attachment in attachments
                ]
            )
            if attachments
            else None
        )
        deleted_message = DeletedMessage(
            server_id=message.server_id,
            message_id=message.message_id,
            channel_id=message.channel_id,
            author_user_id=message.user_id,
            content=message.content,
            attachments_json=attachments_json,
            deleted_at=deleted_at,
            deleted_by_user_id=deleted_by_user_id,
        )
        session.add(deleted_message)
        await session.flush()
        await migrate_message_action_links_to_deleted(
            session,
            deleted_message=deleted_message,
            ensure_action_id=action_id,
            linked_by_user_id=deleted_by_user_id,
        )
        for attachment in attachments:
            await session.delete(attachment)
        await session.delete(message)
        moved_count += 1
    await session.flush()
    return moved_count


async def _delete_and_link_cleanup_messages_for_action(
    session: AsyncSession,
    *,
    action: ModerationActionCreate,
    action_id: UUID,
    moderator_user_id: int,
) -> int:
    messages = await _message_logs_for_action_cleanup(session=session, action=action)
    if not messages:
        return 0

    for message in messages:
        try:
            await delete_channel_message(channel_id=message.channel_id, message_id=message.message_id)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise

    return await _move_deleted_message_logs_to_action(
        session=session,
        messages=messages,
        action_id=action_id,
        deleted_by_user_id=moderator_user_id,
    )


async def add_deleted_message_for_action(
    session: AsyncSession,
    action_id: UUID,
    body: DeletedMessageCreateModel,
    linked_by_user_id: int,
) -> DeletedMessageReadModel:
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    server_id = action.server_id
    await build_actor(session, server_id, linked_by_user_id, require_membership=True)

    author_user_id = int(body.author_user_id) if body.author_user_id else None
    deleted_by_user_id = int(body.deleted_by_user_id) if body.deleted_by_user_id else None
    if author_user_id:
        await build_actor(session, server_id, author_user_id)
    if deleted_by_user_id:
        await build_actor(session, server_id, deleted_by_user_id)

    deleted_message = DeletedMessage(
        server_id=server_id,
        message_id=int(body.message_id),
        channel_id=int(body.channel_id),
        author_user_id=author_user_id,
        content=body.content,
        attachments_json=body.attachments_json,
        deleted_at=body.deleted_at or naive_utcnow(),
        deleted_by_user_id=deleted_by_user_id,
    )
    session.add(deleted_message)
    await session.flush()
    await session.refresh(deleted_message)

    session.add(
        ModerationActionDeletedMessageLink(
            moderation_action_id=action_id,
            deleted_message_id=deleted_message.id,
            linked_by_user_id=linked_by_user_id,
        )
    )
    await session.flush()
    return await to_deleted_message_read(deleted_message, session)


async def link_existing_deleted_message_to_action(
    session: AsyncSession,
    action_id: UUID,
    deleted_message_id: UUID,
    linked_by_user_id: int,
) -> DeletedMessageReadModel:
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    deleted_message = await session.get(DeletedMessage, deleted_message_id)
    if not deleted_message or deleted_message.server_id != action.server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deleted message not found")

    await build_actor(session, action.server_id, linked_by_user_id, require_membership=True)

    existing_link = (
        await session.exec(
            select(ModerationActionDeletedMessageLink).where(
                ModerationActionDeletedMessageLink.moderation_action_id == action_id,
                ModerationActionDeletedMessageLink.deleted_message_id == deleted_message_id,
            )
        )
    ).first()
    if not existing_link:
        session.add(
            ModerationActionDeletedMessageLink(
                moderation_action_id=action_id,
                deleted_message_id=deleted_message_id,
                linked_by_user_id=linked_by_user_id,
            )
        )
        await session.flush()

    channel_names = await _get_channel_names(action.server_id)
    return await to_deleted_message_read(
        deleted_message,
        session,
        channel_name=channel_names.get(deleted_message.channel_id),
    )


async def get_deleted_messages_for_action(
    session: AsyncSession,
    action_id: UUID,
) -> list[DeletedMessageReadModel]:
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    deleted_messages = await query_deleted_messages_for_action(session=session, action_id=action_id)
    channel_names = await _get_channel_names(action.server_id)
    return [
        await to_deleted_message_read(item, session, channel_name=channel_names.get(item.channel_id))
        for item in deleted_messages
    ]


async def browse_deleted_messages_for_server(
    session: AsyncSession,
    server_id: int,
    author_user_id: str | None = None,
    channel_id: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[DeletedMessageReadModel]:
    messages = await query_deleted_messages(
        session=session,
        server_id=server_id,
        author_user_id=int(author_user_id) if author_user_id else None,
        channel_id=int(channel_id) if channel_id else None,
        since=since,
        limit=limit,
    )
    channel_names = await _get_channel_names(server_id)
    return [
        await to_deleted_message_read(item, session, channel_name=channel_names.get(item.channel_id))
        for item in messages
    ]


def _deleted_message_attachments(raw: str | None) -> list[DeletedMessageAttachmentModel]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [
        DeletedMessageAttachmentModel.model_validate(item)
        for item in parsed
        if isinstance(item, dict)
    ]


async def browse_deleted_attachments_for_server(
    session: AsyncSession,
    server_id: int,
    author_user_id: str | None = None,
    channel_id: str | None = None,
    since: datetime | None = None,
    kind: str = "image",
    deletion_type: str | None = None,
    sort_by: str = "deleted_at",
    limit: int = 200,
) -> list[DeletedAttachmentReadModel]:
    messages = await query_deleted_messages(
        session=session,
        server_id=server_id,
        author_user_id=int(author_user_id) if author_user_id else None,
        channel_id=int(channel_id) if channel_id else None,
        since=since,
        limit=1000,
    )
    channel_names = await _get_channel_names(server_id)
    rows: list[DeletedAttachmentReadModel] = []
    for message in messages:
        message_deletion_type = deleted_message_deletion_type(message)
        if deletion_type and message_deletion_type != deletion_type:
            continue
        attachments = _deleted_message_attachments(message.attachments_json)
        if kind == "image":
            attachments = [
                attachment
                for attachment in attachments
                if (attachment.content_type or "").lower().startswith("image/")
            ]
        if not attachments:
            continue
        read_model = await to_deleted_message_read(
            message,
            session,
            channel_name=channel_names.get(message.channel_id),
        )
        for attachment in attachments:
            rows.append(
                DeletedAttachmentReadModel(
                    deleted_message_id=str(message.id),
                    server_id=str(message.server_id),
                    message_id=str(message.message_id),
                    channel_id=str(message.channel_id),
                    channel_name=channel_names.get(message.channel_id),
                    deleted_at=message.deleted_at,
                    deletion_type=message_deletion_type,
                    author=read_model.author,
                    deleted_by=read_model.deleted_by,
                    attachment=attachment,
                )
            )

    if sort_by == "deletion_type":
        type_order = {"self": 0, "moderator": 1, "unknown": 2}
        rows.sort(key=lambda row: (type_order.get(row.deletion_type, 99), -row.deleted_at.timestamp()))
    else:
        rows.sort(key=lambda row: row.deleted_at, reverse=True)
    return rows[:limit]

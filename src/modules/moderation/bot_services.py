from datetime import datetime, timezone
from uuid import UUID

import discord
from discord import app_commands
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionCreate, ModerationActionMessageCleanupCreate
from api.models.moderation_cases import ModerationCaseCreateModel, ModerationCaseSummaryModel
from api.models.moderation_rules import ModerationRuleReadModel
from api.services.moderation_actions_service import _dashboard_action_url, _dashboard_case_url, create_action
from api.services.moderation_cases_service import create_case, list_cases
from api.services.moderation_rules_service import list_rules, to_rule_read_model
from src.db.models import ActionType, CaseStatus, ModerationAction, ModerationCase
from src.modules.localization.service import tr
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists


CASE_NEW_VALUE = "__new_case__"
MESSAGE_CLEANUP_PERIOD_LABELS = {
    15: "15 minutes",
    60: "1 hour",
    360: "6 hours",
    1440: "24 hours",
    10080: "7 days",
}


def action_message_cleanup_choices() -> list[app_commands.Choice[int]]:
    return [
        app_commands.Choice(name=label, value=minutes)
        for minutes, label in MESSAGE_CLEANUP_PERIOD_LABELS.items()
    ]


def build_message_cleanup_request(
    *,
    delete_messages: app_commands.Choice[int] | int | None,
    delete_message_limit: int | None = None,
    delete_message_channel: discord.abc.GuildChannel | None = None,
) -> ModerationActionMessageCleanupCreate | None:
    if delete_messages is None:
        return None

    period_minutes = (
        delete_messages.value
        if isinstance(delete_messages, app_commands.Choice)
        else int(delete_messages)
    )
    channel_ids = [str(delete_message_channel.id)] if delete_message_channel is not None else []
    return ModerationActionMessageCleanupCreate(
        recent_period_minutes=period_minutes,
        recent_limit=delete_message_limit or 25,
        channel_ids=channel_ids,
    )


def message_cleanup_receipt_line(
    *,
    locale: str,
    cleanup: ModerationActionMessageCleanupCreate | None,
    channel: discord.abc.GuildChannel | None = None,
) -> tuple[str, str] | None:
    if cleanup is None or cleanup.recent_period_minutes is None:
        return None

    period = MESSAGE_CLEANUP_PERIOD_LABELS.get(
        cleanup.recent_period_minutes,
        f"{cleanup.recent_period_minutes} minutes",
    )
    channel_suffix = (
        tr(
            locale,
            "action.message_cleanup_channel_suffix",
            channel=channel.mention if hasattr(channel, "mention") else f"#{channel.name}",
        )
        if channel is not None
        else ""
    )
    return (
        tr(locale, "action.message_cleanup_label"),
        tr(
            locale,
            "action.message_cleanup_value",
            period=period,
            limit=cleanup.recent_limit,
            channel=channel_suffix,
        ),
    )


def message_cleanup_receipt_lines(
    *,
    locale: str,
    cleanup: ModerationActionMessageCleanupCreate | None,
    channel: discord.abc.GuildChannel | None = None,
) -> list[tuple[str, str]]:
    line = message_cleanup_receipt_line(locale=locale, cleanup=cleanup, channel=channel)
    return [line] if line is not None else []


async def fetch_active_rule_models(session: AsyncSession, server_id: int) -> list[ModerationRuleReadModel]:
    rules = await list_rules(session=session, server_id=server_id, include_inactive=False)
    return [to_rule_read_model(rule) for rule in rules]


def find_rule(rules: list[ModerationRuleReadModel], rule_id: str) -> ModerationRuleReadModel | None:
    for rule in rules:
        if str(rule.id) == str(rule_id):
            return rule
    return None


def rule_label(rule: ModerationRuleReadModel) -> str:
    code = (rule.code or "").strip()
    title = (rule.title or "").strip()
    if code:
        return f"{code} {title}".strip()
    return title or tr(None, "common.rule_fallback")


def rule_choices(
    rules: list[ModerationRuleReadModel],
    current: str,
    limit: int = 25,
) -> list[app_commands.Choice[str]]:
    current_lower = current.lower().strip()
    choices: list[app_commands.Choice[str]] = []
    for rule in rules:
        label = rule_label(rule)
        if current_lower and current_lower not in label.lower():
            continue
        display_name = label if len(label) <= 100 else f"{label[:97]}..."
        choices.append(app_commands.Choice(name=display_name, value=str(rule.id)))
        if len(choices) >= limit:
            break
    return choices


def _receipt_value(value: object, limit: int = 600) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def build_moderator_action_receipt(
    *,
    locale: str,
    server_id: int,
    public_message: str,
    action: ModerationAction | None = None,
    action_type: ActionType | str | None = None,
    action_id: str | UUID | None = None,
    rule: str | None = None,
    commentary: str | None = None,
    case_id: str | UUID | None = None,
    expires_at: datetime | None = None,
    extra_lines: list[tuple[str, object | None]] | None = None,
) -> str:
    """Build the private moderator receipt sent after the public notice."""
    resolved_action_id = action_id or getattr(action, "id", None)
    resolved_action_type = action_type or getattr(action, "action_type", None)
    resolved_case_id = case_id or getattr(action, "case_id", None)
    resolved_commentary = commentary if commentary is not None else getattr(action, "commentary", None)
    resolved_expires_at = expires_at or getattr(action, "expires_at", None)

    lines = [f"**{tr(locale, 'action.private_receipt_title')}**", f"{tr(locale, 'action.public_notice_label')}: {public_message}"]

    if resolved_action_id:
        action_id_text = str(resolved_action_id)
        lines.append(
            f"{tr(locale, 'modlog.action_id_label')}: "
            f"[`{action_id_text[:8]}`]({_dashboard_action_url(server_id, action_id_text)})"
        )
    if resolved_action_type:
        action_type_text = resolved_action_type.value if hasattr(resolved_action_type, "value") else str(resolved_action_type)
        lines.append(f"{tr(locale, 'modlog.action_label')}: `{_receipt_value(action_type_text, 80)}`")
    if rule:
        lines.append(f"{tr(locale, 'modlog.rule_label')}: `{_receipt_value(rule)}`")
    if resolved_case_id:
        case_id_text = str(resolved_case_id)
        lines.append(
            f"{tr(locale, 'modlog.case_label')}: "
            f"[`{case_id_text[:8]}`]({_dashboard_case_url(server_id, case_id_text)})"
        )
    if resolved_expires_at:
        lines.append(f"{tr(locale, 'modlog.expires_at_label')}: `{resolved_expires_at.isoformat()}`")
    if resolved_commentary:
        lines.append(f"{tr(locale, 'modlog.commentary_label')}: {_receipt_value(resolved_commentary)}")

    for label, value in extra_lines or []:
        if value is None:
            continue
        lines.append(f"{label}: {_receipt_value(value)}")

    return "\n".join(lines)


async def fetch_open_case_models(
    session: AsyncSession,
    server_id: int,
    user_id: int | None = None,
    limit: int = 20,
) -> list[ModerationCaseSummaryModel]:
    return await list_cases(
        session=session,
        server_id=server_id,
        status_filter=CaseStatus.OPEN,
        user_id=str(user_id) if user_id is not None else None,
        limit=limit,
    )


async def fetch_case_autocomplete_models(
    session: AsyncSession,
    server_id: int,
    user_id: int | None = None,
    limit: int = 20,
) -> list[ModerationCaseSummaryModel]:
    cases = await fetch_open_case_models(
        session=session,
        server_id=server_id,
        user_id=user_id,
        limit=limit,
    )
    if user_id is None or len(cases) >= limit:
        return cases[:limit]

    fallback = await fetch_open_case_models(
        session=session,
        server_id=server_id,
        user_id=None,
        limit=limit,
    )
    seen = {case.id for case in cases}
    cases.extend(case for case in fallback if case.id not in seen)
    return cases[:limit]

def case_label(case: ModerationCaseSummaryModel) -> str:
    target = case.target_user.display_name or case.target_user.user_id
    return f"#{case.id[:8]} {case.title} ({target})"


def case_choices(
    cases: list[ModerationCaseSummaryModel],
    current: str,
    include_new: bool = True,
    limit: int = 25,
) -> list[app_commands.Choice[str]]:
    current_lower = current.lower().strip()
    choices: list[app_commands.Choice[str]] = []
    if include_new and (not current_lower or "new" in current_lower):
        choices.append(app_commands.Choice(name="New case", value=CASE_NEW_VALUE))

    for moderation_case in cases:
        label = case_label(moderation_case)
        if current_lower and current_lower not in label.lower():
            continue
        display_name = label if len(label) <= 100 else f"{label[:97]}..."
        choices.append(app_commands.Choice(name=display_name, value=moderation_case.id))
        if len(choices) >= limit:
            break
    return choices


async def resolve_case_id_for_action(
    *,
    session: AsyncSession,
    interaction: discord.Interaction,
    user: discord.Member,
    action_type: ActionType,
    selected_case: str | None,
    selected_rule: ModerationRuleReadModel,
    selected_rule_label: str,
    commentary: str | None,
) -> UUID | None:
    if not selected_case:
        return None

    if interaction.guild is None:
        raise ValueError("Cases can only be used in a server")

    if selected_case == CASE_NEW_VALUE:
        await check_if_server_exists(interaction.guild, session)
        await check_if_user_exists(user, interaction.guild, session)
        await check_if_user_exists(interaction.user, interaction.guild, session)

        title = f"{action_type.value.title()} - {user.display_name}: {selected_rule_label}"
        case_data = await create_case(
            session=session,
            server_id=interaction.guild.id,
            body=ModerationCaseCreateModel(
                target_user_id=str(user.id),
                opened_by_user_id=str(interaction.user.id),
                title=title[:300],
                summary=commentary,
                rule_ids=[str(selected_rule.id)],
            ),
            opened_by_user_id=interaction.user.id,
        )
        return UUID(case_data.id)

    try:
        case_id = UUID(str(selected_case))
    except ValueError:
        raise ValueError("Invalid case selection")

    existing_case = await session.get(ModerationCase, case_id)
    if (
        existing_case is None
        or existing_case.server_id != interaction.guild.id
        or existing_case.status != CaseStatus.OPEN
    ):
        raise ValueError("Selected case is not open or does not exist")
    return case_id


def validate_target_for_moderation(
    interaction: discord.Interaction,
    target: discord.Member,
    locale: str,
) -> str | None:
    guild = interaction.guild
    if guild is None:
        return tr(locale, "common.server_only")
    if target.id == interaction.user.id:
        return tr(locale, "common.target_self")
    if target.id == guild.owner_id:
        return tr(locale, "common.target_owner")

    actor = interaction.user if isinstance(interaction.user, discord.Member) else None
    if actor and guild.owner_id != actor.id and target.top_role >= actor.top_role:
        return tr(locale, "common.target_hierarchy")

    me = guild.me
    if me and target.top_role >= me.top_role:
        return tr(locale, "common.target_bot_hierarchy")
    return None


def target_joined_at_for_action(user: discord.Member) -> datetime:
    joined_at = user.joined_at or datetime.now(timezone.utc)
    if joined_at.tzinfo is not None:
        return joined_at.astimezone(timezone.utc).replace(tzinfo=None)
    return joined_at


def build_action_payload(
    *,
    interaction: discord.Interaction,
    user: discord.Member,
    action_type: ActionType,
    rule_id: str | UUID | None,
    commentary: str | None,
    reason: str | None,
    expires_at: datetime | None = None,
    case_id: UUID | None = None,
    rule_ids: list[str] | None = None,
    message_cleanup: ModerationActionMessageCleanupCreate | None = None,
) -> ModerationActionCreate:
    parsed_rule_id = UUID(str(rule_id)) if rule_id else None
    return ModerationActionCreate(
        action_type=action_type,
        moderator_user_id=interaction.user.id,
        rule_id=parsed_rule_id,
        rule_ids=rule_ids or [],
        commentary=commentary,
        reason=reason,
        expires_at=expires_at,
        case_id=str(case_id) if case_id else None,
        target_user_id=user.id,
        target_user_name=user.name,
        target_user_joined_at=target_joined_at_for_action(user),
        target_user_server_nickname=user.nick,
        server_id=interaction.guild.id,
        server_name=interaction.guild.name,
        message_cleanup=message_cleanup,
    )


async def create_bot_moderation_action(
    *,
    session: AsyncSession,
    interaction: discord.Interaction,
    user: discord.Member,
    action_type: ActionType,
    rule_id: str | UUID | None,
    commentary: str | None,
    reason: str | None,
    expires_at: datetime | None = None,
    case_id: UUID | None = None,
    rule_ids: list[str] | None = None,
    message_cleanup: ModerationActionMessageCleanupCreate | None = None,
) -> ModerationAction:
    payload = build_action_payload(
        interaction=interaction,
        user=user,
        action_type=action_type,
        rule_id=rule_id,
        rule_ids=rule_ids,
        commentary=commentary,
        reason=reason,
        expires_at=expires_at,
        case_id=case_id,
        message_cleanup=message_cleanup,
    )
    return await create_action(
        session=session,
        action=payload,
        moderator_user_id=interaction.user.id,
        apply_discord_effects=True,
    )

from datetime import datetime, timezone
from uuid import UUID

import discord
from discord import app_commands
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionCreate
from api.models.moderation_cases import ModerationCaseCreateModel, ModerationCaseSummaryModel
from api.models.moderation_rules import ModerationRuleReadModel
from api.services.moderation_actions_service import create_action
from api.services.moderation_cases_service import create_case, list_cases
from api.services.moderation_rules_service import list_rules, to_rule_read_model
from src.db.models import ActionType, CaseStatus, ModerationAction, ModerationCase
from src.modules.localization.service import tr
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists


CASE_NEW_VALUE = "__new_case__"


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
) -> ModerationActionCreate:
    parsed_rule_id = UUID(str(rule_id)) if rule_id else None
    return ModerationActionCreate(
        action_type=action_type,
        moderator_user_id=interaction.user.id,
        rule_id=parsed_rule_id,
        rule_ids=[],
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
) -> ModerationAction:
    payload = build_action_payload(
        interaction=interaction,
        user=user,
        action_type=action_type,
        rule_id=rule_id,
        commentary=commentary,
        reason=reason,
        expires_at=expires_at,
        case_id=case_id,
    )
    return await create_action(
        session=session,
        action=payload,
        moderator_user_id=interaction.user.id,
        apply_discord_effects=True,
    )

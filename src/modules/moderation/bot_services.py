from datetime import datetime, timezone
from uuid import UUID

import discord
from discord import app_commands
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionCreate
from api.models.moderation_rules import ModerationRuleReadModel
from api.services.moderation_actions_service import create_action
from api.services.moderation_rules_service import list_rules, to_rule_read_model
from src.db.models import ActionType, ModerationAction
from src.modules.localization.service import tr


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
) -> ModerationAction:
    payload = build_action_payload(
        interaction=interaction,
        user=user,
        action_type=action_type,
        rule_id=rule_id,
        commentary=commentary,
        reason=reason,
        expires_at=expires_at,
    )
    return await create_action(
        session=session,
        action=payload,
        moderator_user_id=interaction.user.id,
        apply_discord_effects=True,
    )

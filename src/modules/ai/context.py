import json
from typing import Any, Awaitable, Callable, Literal

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.discord_guilds import fetch_channel
from api.services.moderation_rules_service import list_rules, to_rule_read_model
from api.services.moderation_users_service import build_user_profile_card
from src.modules.ai.models import AIContext

ChannelFetcher = Callable[[int, int], Awaitable[dict[str, Any] | None]]
MemberProfileVisibility = Literal["moderation", "public_answer"]


def _model_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return {"value": value}


def _sanitize_channel_payload(channel: dict[str, Any] | None, channel_id: int) -> dict[str, Any]:
    if channel is None:
        return {
            "id": str(channel_id),
            "lookup_status": "not_found",
        }

    return {
        "id": str(channel.get("id", channel_id)),
        "name": channel.get("name"),
        "type": channel.get("type"),
        "position": channel.get("position"),
        "parent_id": str(channel["parent_id"]) if channel.get("parent_id") is not None else None,
        "topic": channel.get("topic"),
        "nsfw": channel.get("nsfw"),
        "rate_limit_per_user": channel.get("rate_limit_per_user"),
        "lookup_status": "found",
    }


def public_member_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """
    Keep only member fields that are safe to expose to user-facing assistant replies.

    Public answer context can mention profile basics, nickname history, public activity
    summaries, moderation actions taken against the member, and rule violation summaries.
    It must not include monitoring status, cases, notes, or other internal moderation workspace data.
    """
    public_actions = []
    for action in profile.get("recent_actions") or []:
        public_actions.append(
            {
                "id": action.get("id"),
                "action_type": action.get("action_type"),
                "reason": action.get("reason"),
                "created_at": action.get("created_at"),
            }
        )

    return {
        "visibility": "public_answer",
        "user_id": profile.get("user_id"),
        "username": profile.get("username"),
        "server_nickname": profile.get("server_nickname"),
        "display_name": profile.get("display_name"),
        "avatar_hash": profile.get("avatar_hash"),
        "joined_discord": profile.get("joined_discord"),
        "is_member": profile.get("is_member"),
        "birthday": profile.get("birthday"),
        "activity": profile.get("activity"),
        "nickname_history": profile.get("nickname_history") or [],
        "moderation_actions_count": profile.get("moderation_actions_count", 0),
        "recent_actions": public_actions,
        "top_rules_violated": profile.get("top_rules_violated") or [],
        "omitted_private_fields": [
            "open_cases_count",
            "recent_cases",
            "monitored",
            "monitored_summary",
            "flagged_absent_at",
        ],
    }


def moderation_member_profile(profile: dict[str, Any]) -> dict[str, Any]:
    profile = dict(profile)
    profile["visibility"] = "moderation"
    return profile


async def get_active_rules_context(session: AsyncSession, server_id: int) -> list[dict[str, Any]]:
    rules = await list_rules(session=session, server_id=server_id, include_inactive=False)
    return [_model_to_dict(to_rule_read_model(rule)) for rule in rules]


async def get_member_profile_context(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    visibility: MemberProfileVisibility = "moderation",
) -> dict[str, Any]:
    profile = await build_user_profile_card(
        session=session,
        server_id=server_id,
        user_id=user_id,
        history_limit=10,
        actions_limit=10,
        cases_limit=10,
    )
    payload = _model_to_dict(profile)
    if visibility == "public_answer":
        return public_member_profile(payload)
    return moderation_member_profile(payload)


async def get_channel_context(
    *,
    server_id: int,
    channel_id: int,
    channel_fetcher: ChannelFetcher = fetch_channel,
) -> dict[str, Any]:
    try:
        channel = await channel_fetcher(server_id, channel_id)
    except HTTPException as exc:
        return {
            "id": str(channel_id),
            "lookup_status": "failed",
            "lookup_error": str(exc.detail),
        }
    return _sanitize_channel_payload(channel=channel, channel_id=channel_id)


async def build_ai_context(
    *,
    session: AsyncSession | None = None,
    server_id: int | None = None,
    user_id: int | None = None,
    channel_id: int | None = None,
    include_rules: bool = True,
    include_member_profile: bool = False,
    member_profile_visibility: MemberProfileVisibility = "moderation",
    include_channel: bool = True,
    channel_fetcher: ChannelFetcher = fetch_channel,
) -> AIContext:
    context = AIContext(server_id=server_id, user_id=user_id, channel_id=channel_id)
    if server_id is None:
        return context

    if include_channel and channel_id is not None:
        context.channel = await get_channel_context(
            server_id=server_id,
            channel_id=channel_id,
            channel_fetcher=channel_fetcher,
        )

    if session is None:
        return context

    if include_rules:
        context.active_rules = await get_active_rules_context(session=session, server_id=server_id)

    if include_member_profile and user_id is not None:
        context.member_profile = await get_member_profile_context(
            session=session,
            server_id=server_id,
            user_id=user_id,
            visibility=member_profile_visibility,
        )

    return context


def context_to_prompt_block(context: AIContext) -> str:
    if context.is_empty():
        return "No database context was provided for this request."

    payload = {
        "server_id": str(context.server_id) if context.server_id is not None else None,
        "user_id": str(context.user_id) if context.user_id is not None else None,
        "channel_id": str(context.channel_id) if context.channel_id is not None else None,
        "server_name": context.server_name,
        "channel": context.channel,
        "active_rules": context.active_rules,
        "member_profile": context.member_profile,
        "server_notes": context.server_notes,
        "admin_notes": context.admin_notes,
    }
    return json.dumps(payload, ensure_ascii=False, default=str, indent=2)

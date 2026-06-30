from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.discord_guilds import fetch_guild_member, search_guild_members
from src.db.models import (
    GlobalUser,
    ModerationAction,
    ModerationImportSource,
    ModerationImportSourceItem,
    User,
)


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def _member_user(member: dict) -> dict:
    user = member.get("user")
    return user if isinstance(user, dict) else {}


def _member_names(member: dict) -> set[str]:
    user = _member_user(member)
    return {
        _norm(member.get("nick")),
        _norm(member.get("display_name")),
        _norm(user.get("username")),
        _norm(user.get("global_name")),
    } - {""}


def _member_display_name(member: dict, fallback: str | None = None) -> str | None:
    user = _member_user(member)
    return (
        user.get("global_name")
        or member.get("nick")
        or user.get("username")
        or fallback
    )


def _member_user_id(member: dict) -> int | None:
    user_id = _member_user(member).get("id")
    if user_id is None:
        return None
    return int(user_id)


async def _upsert_member_user(
    session: AsyncSession,
    *,
    server_id: int,
    user_id: int,
    username: str | None,
    member: dict | None = None,
) -> None:
    user_payload = _member_user(member or {})
    global_user = await session.get(GlobalUser, user_id)
    if global_user is None:
        global_user = GlobalUser(
            discord_id=user_id,
            username=username,
            avatar_hash=user_payload.get("avatar"),
        )
        session.add(global_user)
        await session.flush()
    else:
        if username:
            global_user.username = username
        if user_payload.get("avatar"):
            global_user.avatar_hash = user_payload.get("avatar")
        session.add(global_user)

    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    if membership is None:
        membership = User(
            user_id=user_id,
            server_id=server_id,
            server_nickname=(member or {}).get("nick"),
            is_member=True,
        )
        session.add(membership)
    else:
        if member is not None:
            membership.server_nickname = member.get("nick")
            membership.is_member = True
            session.add(membership)
    await session.flush()


async def _member_for_manual_id(server_id: int, user_id: int) -> dict | None:
    try:
        return await fetch_guild_member(server_id, user_id)
    except Exception:
        return None


async def _resolve_handle(
    *,
    server_id: int,
    handle: str,
    moderator_map: dict[str, int] | None,
    use_discord_search: bool,
) -> tuple[str, int | None, dict | None, str | None]:
    normalized = _norm(handle)
    if moderator_map and normalized in moderator_map:
        user_id = moderator_map[normalized]
        member = await _member_for_manual_id(server_id, user_id)
        return "manual_map", user_id, member, None

    if not use_discord_search:
        return "unresolved", None, None, "discord search disabled"

    members = await search_guild_members(server_id, handle, limit=10)
    exact_matches = [
        member
        for member in members
        if normalized in _member_names(member)
    ]
    if len(exact_matches) != 1:
        if not exact_matches:
            return "unresolved", None, None, "no exact Discord member match"
        return "ambiguous", None, None, f"{len(exact_matches)} exact Discord member matches"

    member = exact_matches[0]
    user_id = _member_user_id(member)
    if user_id is None:
        return "unresolved", None, member, "Discord member match had no user id"
    return "discord_search", user_id, member, None


async def fix_juniper_moderator_attribution(
    session: AsyncSession,
    *,
    server_id: int,
    run_id: UUID | None = None,
    dry_run: bool = False,
    moderator_map: dict[str, int] | None = None,
    use_discord_search: bool = True,
) -> dict:
    statement = (
        select(ModerationImportSourceItem)
        .where(
            ModerationImportSourceItem.server_id == server_id,
            ModerationImportSourceItem.source == ModerationImportSource.JUNIPER.value,
            ModerationImportSourceItem.source_item_type == "juniper_warns_xlsx",
            ModerationImportSourceItem.moderation_action_id.is_not(None),
        )
        .options(selectinload(ModerationImportSourceItem.moderation_action))
    )
    if run_id is not None:
        statement = statement.where(ModerationImportSourceItem.import_run_id == run_id)

    items = (await session.exec(statement)).all()
    by_handle: dict[str, list[ModerationImportSourceItem]] = {}
    missing_issuer = 0
    for item in items:
        raw_payload = item.raw_payload_json or {}
        issuer_handle = raw_payload.get("issuer_handle") if isinstance(raw_payload, dict) else None
        if not issuer_handle:
            missing_issuer += 1
            continue
        by_handle.setdefault(str(issuer_handle).strip(), []).append(item)

    summary = {
        "items": len(items),
        "issuer_handles": len(by_handle),
        "missing_issuer": missing_issuer,
        "resolved_handles": 0,
        "unresolved_handles": 0,
        "ambiguous_handles": 0,
        "actions_updated": 0,
        "already_correct": 0,
        "dry_run": dry_run,
        "details": {},
    }

    for handle, handle_items in sorted(by_handle.items(), key=lambda item: item[0].casefold()):
        method, moderator_user_id, member, error = await _resolve_handle(
            server_id=server_id,
            handle=handle,
            moderator_map=moderator_map,
            use_discord_search=use_discord_search,
        )
        if moderator_user_id is None:
            if method == "ambiguous":
                summary["ambiguous_handles"] += 1
            else:
                summary["unresolved_handles"] += 1
            summary["details"][handle] = {
                "status": method,
                "error": error,
                "actions": len(handle_items),
            }
            continue

        summary["resolved_handles"] += 1
        display_name = _member_display_name(member or {}, fallback=handle)
        updated_for_handle = 0
        already_correct_for_handle = 0
        if not dry_run:
            await _upsert_member_user(
                session,
                server_id=server_id,
                user_id=moderator_user_id,
                username=display_name,
                member=member,
            )

        for item in handle_items:
            action = item.moderation_action
            if action is None:
                continue
            if action.moderator_user_id == moderator_user_id:
                summary["already_correct"] += 1
                already_correct_for_handle += 1
                continue
            if not dry_run:
                action.moderator_user_id = moderator_user_id
                session.add(action)
                normalized_payload = dict(item.normalized_payload_json or {})
                normalized_payload.update(
                    {
                        "moderator_user_id": str(moderator_user_id),
                        "moderator_username": display_name,
                        "moderator_attribution_fixed": True,
                        "moderator_attribution_source": method,
                    }
                )
                item.normalized_payload_json = normalized_payload
                session.add(item)
            summary["actions_updated"] += 1
            updated_for_handle += 1

        summary["details"][handle] = {
            "status": "resolved",
            "method": method,
            "moderator_user_id": str(moderator_user_id),
            "moderator_username": display_name,
            "actions": len(handle_items),
            "updated": updated_for_handle,
            "already_correct": already_correct_for_handle,
        }

    if not dry_run:
        await session.flush()
    return summary

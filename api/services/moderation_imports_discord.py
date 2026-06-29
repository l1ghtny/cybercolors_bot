from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.discord_guilds import fetch_guild_audit_logs, fetch_guild_bans
from api.services.moderation_core import naive_utcnow
from api.services.moderation_imports_service import (
    ImportedModerationActionPayload,
    create_import_run,
    finish_import_run,
    has_active_moderation_action,
    import_moderation_action,
    record_skipped_source_item,
)
from src.db.models import (
    ActionType,
    ModerationImportConfidence,
    ModerationImportSource,
)

DISCORD_EPOCH_MS = 1420070400000
DISCORD_AUDIT_ACTION_MEMBER_KICK = 20
DISCORD_AUDIT_ACTION_MEMBER_BAN_ADD = 22
DISCORD_AUDIT_ACTION_MEMBER_BAN_REMOVE = 23
DISCORD_AUDIT_ACTION_MEMBER_UPDATE = 24
SUPPORTED_AUDIT_ACTION_TYPES = {
    DISCORD_AUDIT_ACTION_MEMBER_KICK,
    DISCORD_AUDIT_ACTION_MEMBER_BAN_ADD,
    DISCORD_AUDIT_ACTION_MEMBER_BAN_REMOVE,
    DISCORD_AUDIT_ACTION_MEMBER_UPDATE,
}


def snowflake_datetime(snowflake_id: int | str) -> datetime:
    timestamp_ms = (int(snowflake_id) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def parse_discord_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _user_display_name(user: dict | None) -> str | None:
    if not user:
        return None
    global_name = user.get("global_name")
    username = user.get("username")
    discriminator = user.get("discriminator")
    if global_name:
        return str(global_name)
    if username and discriminator and discriminator != "0":
        return f"{username}#{discriminator}"
    return str(username) if username else None


async def fetch_all_guild_bans(server_id: int) -> list[dict]:
    bans: list[dict] = []
    after: int | None = None
    while True:
        page = await fetch_guild_bans(server_id, limit=1000, after=after)
        if not page:
            break
        bans.extend(page)
        if len(page) < 1000:
            break
        last_user = page[-1].get("user") or {}
        last_user_id = last_user.get("id")
        if last_user_id is None:
            break
        after = int(last_user_id)
    return bans


async def fetch_recent_moderation_audit_entries(server_id: int, *, days: int = 45) -> tuple[list[dict], dict[str, dict]]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    entries: list[dict] = []
    users_by_id: dict[str, dict] = {}
    before: int | None = None

    while True:
        payload = await fetch_guild_audit_logs(server_id, limit=100, before=before)
        for user in payload.get("users", []) or []:
            user_id = user.get("id")
            if user_id is not None:
                users_by_id[str(user_id)] = user

        page_entries = payload.get("audit_log_entries", []) or []
        if not page_entries:
            break

        oldest_seen: datetime | None = None
        for entry in page_entries:
            entry_id = entry.get("id")
            if entry_id is None:
                continue
            created_at = snowflake_datetime(entry_id)
            oldest_seen = created_at if oldest_seen is None else min(oldest_seen, created_at)
            if created_at < cutoff:
                continue
            if entry.get("action_type") in SUPPORTED_AUDIT_ACTION_TYPES:
                entries.append(entry)

        last_entry_id = page_entries[-1].get("id")
        if last_entry_id is None:
            break
        before = int(last_entry_id)
        if len(page_entries) < 100 or (oldest_seen is not None and oldest_seen < cutoff):
            break

    return entries, users_by_id


def _timeout_expires_at(entry: dict) -> datetime | None:
    for change in entry.get("changes", []) or []:
        if change.get("key") == "communication_disabled_until":
            return parse_discord_datetime(change.get("new_value"))
    return None


def _payload_from_audit_entry(
    *,
    server_id: int,
    entry: dict,
    users_by_id: dict[str, dict],
    current_banned_user_ids: set[int],
    now: datetime,
) -> ImportedModerationActionPayload | None:
    action_type = entry.get("action_type")
    entry_id = str(entry.get("id"))
    target_id_raw = entry.get("target_id")
    if target_id_raw is None:
        return None
    target_user_id = int(target_id_raw)
    moderator_user_id = int(entry["user_id"]) if entry.get("user_id") is not None else None
    created_at = snowflake_datetime(entry_id)
    target_user = users_by_id.get(str(target_user_id))
    moderator_user = users_by_id.get(str(moderator_user_id)) if moderator_user_id is not None else None
    reason = entry.get("reason") or None

    if action_type == DISCORD_AUDIT_ACTION_MEMBER_KICK:
        return ImportedModerationActionPayload(
            source=ModerationImportSource.DISCORD,
            source_item_type="discord_audit_log",
            source_item_id=entry_id,
            server_id=server_id,
            action_type=ActionType.KICK,
            target_user_id=target_user_id,
            target_username=_user_display_name(target_user),
            moderator_user_id=moderator_user_id,
            moderator_username=_user_display_name(moderator_user),
            reason=reason or "Imported Discord audit log kick",
            created_at=created_at,
            is_active=False,
            raw_payload=entry,
        )

    if action_type == DISCORD_AUDIT_ACTION_MEMBER_BAN_ADD:
        return ImportedModerationActionPayload(
            source=ModerationImportSource.DISCORD,
            source_item_type="discord_audit_log",
            source_item_id=entry_id,
            server_id=server_id,
            action_type=ActionType.BAN,
            target_user_id=target_user_id,
            target_username=_user_display_name(target_user),
            moderator_user_id=moderator_user_id,
            moderator_username=_user_display_name(moderator_user),
            reason=reason or "Imported Discord audit log ban",
            created_at=created_at,
            is_active=target_user_id in current_banned_user_ids,
            raw_payload=entry,
        )

    if action_type == DISCORD_AUDIT_ACTION_MEMBER_UPDATE:
        expires_at = _timeout_expires_at(entry)
        if expires_at is None:
            return None
        return ImportedModerationActionPayload(
            source=ModerationImportSource.DISCORD,
            source_item_type="discord_audit_log",
            source_item_id=entry_id,
            server_id=server_id,
            action_type=ActionType.MUTE,
            target_user_id=target_user_id,
            target_username=_user_display_name(target_user),
            moderator_user_id=moderator_user_id,
            moderator_username=_user_display_name(moderator_user),
            reason=reason or "Imported Discord audit log timeout",
            commentary="Imported from Discord communication_disabled_until audit change.",
            created_at=created_at,
            expires_at=expires_at,
            is_active=expires_at > now,
            confidence=ModerationImportConfidence.INFERRED,
            raw_payload=entry,
        )

    return None


async def import_discord_baseline(
    session: AsyncSession,
    *,
    server_id: int,
    started_by_user_id: int | None = None,
    dry_run: bool = False,
) -> dict:
    run = await create_import_run(
        session,
        server_id=server_id,
        source=ModerationImportSource.DISCORD,
        started_by_user_id=started_by_user_id,
        dry_run=dry_run,
    )
    summary = {
        "audit_imported": 0,
        "active_bans_imported": 0,
        "skipped": 0,
        "duplicates": 0,
        "unsupported": 0,
    }

    try:
        now = naive_utcnow()
        current_bans = await fetch_all_guild_bans(server_id)
        current_banned_user_ids = {
            int((ban.get("user") or {}).get("id"))
            for ban in current_bans
            if (ban.get("user") or {}).get("id") is not None
        }
        audit_entries, users_by_id = await fetch_recent_moderation_audit_entries(server_id, days=45)

        for entry in audit_entries:
            if entry.get("action_type") == DISCORD_AUDIT_ACTION_MEMBER_BAN_REMOVE:
                result = await record_skipped_source_item(
                    session,
                    run,
                    source_item_type="discord_audit_log",
                    source_item_id=str(entry.get("id")) if entry.get("id") is not None else None,
                    raw_payload=entry,
                    reason="Discord unban audit entries do not map to the current moderation action model.",
                )
                summary["unsupported"] += 1
                if result.reason == "duplicate":
                    summary["duplicates"] += 1
                else:
                    summary["skipped"] += 1
                continue

            payload = _payload_from_audit_entry(
                server_id=server_id,
                entry=entry,
                users_by_id=users_by_id,
                current_banned_user_ids=current_banned_user_ids,
                now=now,
            )
            if payload is None:
                result = await record_skipped_source_item(
                    session,
                    run,
                    source_item_type="discord_audit_log",
                    source_item_id=str(entry.get("id")) if entry.get("id") is not None else None,
                    raw_payload=entry,
                    reason="Discord audit entry is not a supported moderation action.",
                )
                summary["unsupported"] += 1
                if result.reason == "duplicate":
                    summary["duplicates"] += 1
                else:
                    summary["skipped"] += 1
                continue

            result = await import_moderation_action(session, run, payload)
            if result.imported:
                summary["audit_imported"] += 1
            elif result.reason == "duplicate":
                summary["duplicates"] += 1
            else:
                summary["skipped"] += 1

        for ban in current_bans:
            user = ban.get("user") or {}
            user_id = user.get("id")
            if user_id is None:
                continue
            target_user_id = int(user_id)
            if await has_active_moderation_action(
                session,
                server_id=server_id,
                target_user_id=target_user_id,
                action_type=ActionType.BAN,
            ):
                result = await record_skipped_source_item(
                    session,
                    run,
                    source_item_type="discord_current_ban",
                    source_item_id=str(target_user_id),
                    raw_payload=ban,
                    reason="Active ban is already represented by an imported or existing active ban action.",
                    confidence=ModerationImportConfidence.EXACT,
                )
                if result.reason == "duplicate":
                    summary["duplicates"] += 1
                else:
                    summary["skipped"] += 1
                continue

            payload = ImportedModerationActionPayload(
                source=ModerationImportSource.DISCORD,
                source_item_type="discord_current_ban",
                source_item_id=str(target_user_id),
                server_id=server_id,
                action_type=ActionType.BAN,
                target_user_id=target_user_id,
                target_username=_user_display_name(user),
                reason=ban.get("reason") or "Imported active Discord ban",
                created_at=now,
                is_active=True,
                confidence=ModerationImportConfidence.INFERRED,
                raw_payload=ban,
            )
            result = await import_moderation_action(session, run, payload)
            if result.imported:
                summary["active_bans_imported"] += 1
            elif result.reason == "duplicate":
                summary["duplicates"] += 1
            else:
                summary["skipped"] += 1

        await finish_import_run(session, run, summary=summary)
        return {"run_id": str(run.id), **summary}
    except Exception as exc:
        await finish_import_run(session, run, summary=summary, error_message=str(exc))
        raise
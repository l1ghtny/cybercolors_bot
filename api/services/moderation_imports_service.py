from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.moderation_core import get_or_create_server_record, naive_utcnow
from src.db.models import (
    ActionType,
    GlobalUser,
    ModerationAction,
    ModerationImportConfidence,
    ModerationImportItemStatus,
    ModerationImportRun,
    ModerationImportRunStatus,
    ModerationImportSource,
    ModerationImportSourceItem,
)

IMPORT_SYSTEM_USER_ID = 0
IMPORT_SYSTEM_USERNAME = "Imported moderation"


@dataclass(frozen=True)
class ImportedModerationActionPayload:
    source: ModerationImportSource
    source_item_type: str
    source_item_id: str | None
    server_id: int
    action_type: ActionType
    target_user_id: int
    target_username: str | None = None
    moderator_user_id: int | None = None
    moderator_username: str | None = None
    reason: str | None = None
    commentary: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    is_active: bool = False
    confidence: ModerationImportConfidence = ModerationImportConfidence.EXACT
    raw_payload: dict | None = None


@dataclass(frozen=True)
class ImportItemResult:
    source_item: ModerationImportSourceItem | None
    action: ModerationAction | None
    imported: bool
    skipped: bool
    reason: str | None = None


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _source_hash(source: ModerationImportSource, source_item_type: str, source_item_id: str | None, raw_payload: dict | None) -> str:
    identity = {
        "source": source.value,
        "source_item_type": source_item_type,
        "source_item_id": source_item_id,
        "raw_payload": raw_payload or {},
    }
    encoded = json.dumps(identity, sort_keys=True, default=_json_default, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _ensure_global_user(session: AsyncSession, user_id: int, username: str | None = None) -> GlobalUser:
    user = await session.get(GlobalUser, user_id)
    if not user:
        user = GlobalUser(discord_id=user_id, username=username)
        session.add(user)
        await session.flush()
    elif username and user.username != username:
        user.username = username
        session.add(user)
    return user


async def _ensure_import_system_user(session: AsyncSession) -> GlobalUser:
    return await _ensure_global_user(session, IMPORT_SYSTEM_USER_ID, IMPORT_SYSTEM_USERNAME)


async def create_import_run(
    session: AsyncSession,
    *,
    server_id: int,
    source: ModerationImportSource,
    started_by_user_id: int | None = None,
    dry_run: bool = False,
) -> ModerationImportRun:
    await get_or_create_server_record(server_id, session)
    if started_by_user_id is not None:
        await _ensure_global_user(session, started_by_user_id)

    run = ModerationImportRun(
        server_id=server_id,
        source=source.value,
        status=ModerationImportRunStatus.RUNNING.value,
        dry_run=dry_run,
        started_by_user_id=started_by_user_id,
        started_at=naive_utcnow(),
    )
    session.add(run)
    await session.flush()
    return run


async def finish_import_run(
    session: AsyncSession,
    run: ModerationImportRun,
    *,
    summary: dict | None = None,
    error_message: str | None = None,
) -> ModerationImportRun:
    run.completed_at = naive_utcnow()
    run.summary_json = summary or {}
    if error_message:
        run.status = ModerationImportRunStatus.FAILED.value
        run.error_message = error_message
    else:
        run.status = ModerationImportRunStatus.COMPLETED.value
        run.error_message = None
    session.add(run)
    await session.flush()
    return run


async def _existing_source_item(
    session: AsyncSession,
    *,
    server_id: int,
    source: ModerationImportSource,
    source_hash: str,
) -> ModerationImportSourceItem | None:
    return (
        await session.exec(
            select(ModerationImportSourceItem).where(
                ModerationImportSourceItem.server_id == server_id,
                ModerationImportSourceItem.source == source.value,
                ModerationImportSourceItem.source_hash == source_hash,
            )
        )
    ).first()


async def record_skipped_source_item(
    session: AsyncSession,
    run: ModerationImportRun,
    *,
    source_item_type: str,
    source_item_id: str | None,
    raw_payload: dict | None,
    reason: str,
    confidence: ModerationImportConfidence = ModerationImportConfidence.INFERRED,
) -> ImportItemResult:
    source = ModerationImportSource(run.source)
    item_hash = _source_hash(source, source_item_type, source_item_id, raw_payload)
    existing = await _existing_source_item(
        session,
        server_id=run.server_id,
        source=source,
        source_hash=item_hash,
    )
    if existing:
        return ImportItemResult(source_item=existing, action=None, imported=False, skipped=True, reason="duplicate")

    if run.dry_run:
        return ImportItemResult(source_item=None, action=None, imported=False, skipped=True, reason=reason)

    item = ModerationImportSourceItem(
        import_run_id=run.id,
        server_id=run.server_id,
        source=source.value,
        source_item_type=source_item_type,
        source_item_id=source_item_id,
        source_hash=item_hash,
        raw_payload_json=raw_payload,
        normalized_payload_json=None,
        confidence=confidence.value,
        status=ModerationImportItemStatus.SKIPPED.value,
        error_message=reason,
    )
    session.add(item)
    await session.flush()
    return ImportItemResult(source_item=item, action=None, imported=False, skipped=True, reason=reason)


async def import_moderation_action(
    session: AsyncSession,
    run: ModerationImportRun,
    payload: ImportedModerationActionPayload,
) -> ImportItemResult:
    if payload.server_id != run.server_id:
        raise ValueError("Imported action server_id must match import run server_id")
    if payload.source.value != run.source:
        raise ValueError("Imported action source must match import run source")

    item_hash = _source_hash(payload.source, payload.source_item_type, payload.source_item_id, payload.raw_payload)
    existing = await _existing_source_item(
        session,
        server_id=payload.server_id,
        source=payload.source,
        source_hash=item_hash,
    )
    if existing:
        existing_action = None
        if existing.moderation_action_id is not None:
            existing_action = await session.get(ModerationAction, existing.moderation_action_id)
        return ImportItemResult(
            source_item=existing,
            action=existing_action,
            imported=False,
            skipped=True,
            reason="duplicate",
        )

    normalized_payload = {
        "action_type": payload.action_type.value,
        "target_user_id": str(payload.target_user_id),
        "moderator_user_id": str(payload.moderator_user_id or IMPORT_SYSTEM_USER_ID),
        "reason": payload.reason,
        "commentary": payload.commentary,
        "created_at": payload.created_at,
        "expires_at": payload.expires_at,
        "is_active": payload.is_active,
    }

    if run.dry_run:
        return ImportItemResult(source_item=None, action=None, imported=False, skipped=True, reason="dry_run")

    await get_or_create_server_record(payload.server_id, session)
    await _ensure_global_user(session, payload.target_user_id, payload.target_username)
    moderator_user_id = payload.moderator_user_id or IMPORT_SYSTEM_USER_ID
    if payload.moderator_user_id is None:
        await _ensure_import_system_user(session)
    else:
        await _ensure_global_user(session, moderator_user_id, payload.moderator_username)

    item = ModerationImportSourceItem(
        import_run_id=run.id,
        server_id=payload.server_id,
        source=payload.source.value,
        source_item_type=payload.source_item_type,
        source_item_id=payload.source_item_id,
        source_hash=item_hash,
        raw_payload_json=payload.raw_payload,
        normalized_payload_json=json.loads(json.dumps(normalized_payload, default=_json_default)),
        confidence=payload.confidence.value,
        status=ModerationImportItemStatus.PENDING.value,
    )
    session.add(item)
    await session.flush()

    action = ModerationAction(
        action_type=payload.action_type,
        server_id=payload.server_id,
        target_user_id=payload.target_user_id,
        moderator_user_id=moderator_user_id,
        reason=(payload.reason or f"Imported {payload.action_type.value} from {payload.source.value}").strip(),
        commentary=payload.commentary,
        created_at=payload.created_at or naive_utcnow(),
        expires_at=payload.expires_at,
        is_active=payload.is_active,
    )
    session.add(action)
    await session.flush()

    item.status = ModerationImportItemStatus.IMPORTED.value
    item.moderation_action_id = action.id
    session.add(item)
    await session.flush()

    return ImportItemResult(source_item=item, action=action, imported=True, skipped=False)


async def has_active_moderation_action(
    session: AsyncSession,
    *,
    server_id: int,
    target_user_id: int,
    action_type: ActionType,
) -> bool:
    existing = (
        await session.exec(
            select(ModerationAction.id).where(
                ModerationAction.server_id == server_id,
                ModerationAction.target_user_id == target_user_id,
                ModerationAction.action_type == action_type,
                ModerationAction.is_active == True,
            )
        )
    ).first()
    return existing is not None
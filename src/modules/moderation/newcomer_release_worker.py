from datetime import datetime

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.discord_guilds import fetch_guild_member
from api.services.moderation_core import naive_utcnow
from api.services.newcomer_probation import promote_newcomer_member
from src.db.models import MonitoredUser, MonitoredUserStatusEvent, ServerSecuritySettings
from src.modules.logs_setup import logger

log = logger.logging.getLogger("bot")


async def list_due_newcomer_releases(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[tuple[MonitoredUser, ServerSecuritySettings]]:
    release_time = now or naive_utcnow()
    rows = (
        await session.exec(
            select(MonitoredUser, ServerSecuritySettings)
            .join(
                ServerSecuritySettings,
                ServerSecuritySettings.server_id == MonitoredUser.server_id,
            )
            .where(
                MonitoredUser.source == "newcomer",
                MonitoredUser.is_active.is_(True),
                MonitoredUser.release_due_at.is_not(None),
                MonitoredUser.release_due_at <= release_time,
                MonitoredUser.released_at.is_(None),
                ServerSecuritySettings.newcomer_role_id.is_not(None),
                ServerSecuritySettings.newcomer_member_role_id.is_not(None),
                ServerSecuritySettings.lockdown_enabled.is_(False),
            )
            .order_by(MonitoredUser.release_due_at.asc(), MonitoredUser.created_at.asc())
            .limit(limit)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


def _mark_released(session: AsyncSession, item: MonitoredUser, *, now: datetime) -> None:
    previous_active = item.is_active
    item.is_active = False
    item.released_at = now
    item.release_error = None
    item.updated_at = now
    session.add(item)
    if previous_active:
        session.add(
            MonitoredUserStatusEvent(
                monitored_user_id=item.id,
                changed_by_user_id=item.added_by_user_id,
                from_is_active=True,
                to_is_active=False,
                changed_at=now,
            )
        )


def _record_release_error(session: AsyncSession, item: MonitoredUser, error: str, *, now: datetime) -> None:
    item.release_error = error[:2000]
    item.updated_at = now
    session.add(item)


async def process_due_newcomer_releases(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> tuple[int, int]:
    release_time = now or naive_utcnow()
    processed = 0
    failed = 0
    rows = await list_due_newcomer_releases(session, now=release_time, limit=limit)
    for item, settings in rows:
        try:
            member_payload = await fetch_guild_member(item.server_id, item.user_id)
            if member_payload is None:
                _mark_released(session, item, now=release_time)
                processed += 1
                continue

            current_role_ids = {
                int(role_id_raw) for role_id_raw in member_payload.get("roles", [])
            }

            await promote_newcomer_member(
                server_id=item.server_id,
                user_id=item.user_id,
                settings=settings,
                current_role_ids=current_role_ids,
            )
            _mark_released(session, item, now=release_time)
            processed += 1
        except HTTPException as error:
            if error.status_code == status.HTTP_404_NOT_FOUND:
                _mark_released(session, item, now=release_time)
                processed += 1
                continue
            failed += 1
            _record_release_error(
                session,
                item,
                f"Discord API error {error.status_code}: {error.detail}",
                now=release_time,
            )
            log.warning(
                "Failed to auto-release newcomer role for user %s in guild %s: %s",
                item.user_id,
                item.server_id,
                error.detail,
            )
        except Exception as error:
            failed += 1
            _record_release_error(session, item, str(error), now=release_time)
            log.exception(
                "Unexpected newcomer auto-release failure for user %s in guild %s",
                item.user_id,
                item.server_id,
            )

    return processed, failed

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.bot_messages import BotMessageCreateModel
from api.models.scheduled_posts import (
    ScheduledPostReadModel,
    ScheduledPostRunReadModel,
    ScheduledPostWriteModel,
)
from api.services.bot_messages import send_bot_message
from api.services.discord_guilds import TEXT_CHANNEL_TYPES, fetch_channel
from src.db.models import (
    GlobalUser,
    ScheduledBotPost,
    ScheduledBotPostRun,
    utcnow_utc_tz,
)

LEASE_DURATION = timedelta(minutes=5)


def to_read_model(post: ScheduledBotPost) -> ScheduledPostReadModel:
    return ScheduledPostReadModel(
        id=post.id,
        server_id=str(post.server_id),
        channel_id=str(post.channel_id),
        content=post.content,
        mention_everyone=post.mention_everyone,
        mention_user_ids=post.mention_user_ids,
        mention_role_ids=post.mention_role_ids,
        schedule_type=post.schedule_type,
        timezone=post.timezone,
        interval_seconds=post.interval_seconds,
        status=post.status,
        next_run_at=post.next_run_at,
        last_run_at=post.last_run_at,
        created_by_user_id=str(post.created_by_user_id),
        updated_by_user_id=str(post.updated_by_user_id),
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def to_run_read_model(run: ScheduledBotPostRun) -> ScheduledPostRunReadModel:
    return ScheduledPostRunReadModel.model_validate(run, from_attributes=True)


async def _ensure_actor(session: AsyncSession, actor_user_id: int) -> None:
    if await session.get(GlobalUser, actor_user_id) is None:
        session.add(GlobalUser(discord_id=actor_user_id, username=None))
        await session.flush()


async def _validate_destination(server_id: int, channel_id: int) -> None:
    channel = await fetch_channel(server_id, channel_id)
    if channel is None or int(channel.get("type", -1)) not in TEXT_CHANNEL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select a text channel, thread, or forum post from this server",
        )


def _validate_future_run(value: datetime) -> None:
    if value <= utcnow_utc_tz():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The first delivery time must be in the future",
        )


async def list_scheduled_posts(session: AsyncSession, server_id: int) -> list[ScheduledPostReadModel]:
    rows = (
        await session.exec(
            select(ScheduledBotPost)
            .where(ScheduledBotPost.server_id == server_id)
            .order_by(ScheduledBotPost.next_run_at, ScheduledBotPost.created_at)
        )
    ).all()
    return [to_read_model(row) for row in rows]


async def get_scheduled_post(
    session: AsyncSession, server_id: int, post_id: UUID
) -> ScheduledBotPost:
    post = await session.get(ScheduledBotPost, post_id)
    if post is None or post.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled post not found")
    return post


async def create_scheduled_post(
    session: AsyncSession,
    *,
    server_id: int,
    actor_user_id: int,
    body: ScheduledPostWriteModel,
) -> ScheduledPostReadModel:
    _validate_future_run(body.next_run_at)
    await _validate_destination(server_id, int(body.channel_id))
    await _ensure_actor(session, actor_user_id)
    now = utcnow_utc_tz()
    post = ScheduledBotPost(
        server_id=server_id,
        channel_id=int(body.channel_id),
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
        content=body.content,
        mention_everyone=body.mention_everyone,
        mention_user_ids=body.mention_user_ids,
        mention_role_ids=body.mention_role_ids,
        schedule_type=body.schedule_type,
        timezone=body.timezone,
        interval_seconds=body.interval_seconds,
        status="active",
        next_run_at=body.next_run_at,
        created_at=now,
        updated_at=now,
    )
    session.add(post)
    await session.flush()
    await session.refresh(post)
    return to_read_model(post)


async def update_scheduled_post(
    session: AsyncSession,
    *,
    server_id: int,
    post_id: UUID,
    actor_user_id: int,
    body: ScheduledPostWriteModel,
) -> ScheduledPostReadModel:
    post = await get_scheduled_post(session, server_id, post_id)
    _validate_future_run(body.next_run_at)
    await _validate_destination(server_id, int(body.channel_id))
    await _ensure_actor(session, actor_user_id)
    post.channel_id = int(body.channel_id)
    post.updated_by_user_id = actor_user_id
    post.content = body.content
    post.mention_everyone = body.mention_everyone
    post.mention_user_ids = body.mention_user_ids
    post.mention_role_ids = body.mention_role_ids
    post.schedule_type = body.schedule_type
    post.timezone = body.timezone
    post.interval_seconds = body.interval_seconds
    post.next_run_at = body.next_run_at
    post.status = "active"
    post.lease_until = None
    post.updated_at = utcnow_utc_tz()
    session.add(post)
    await session.flush()
    await session.refresh(post)
    return to_read_model(post)


async def set_scheduled_post_status(
    session: AsyncSession,
    *,
    server_id: int,
    post_id: UUID,
    actor_user_id: int,
    new_status: str,
) -> ScheduledPostReadModel:
    post = await get_scheduled_post(session, server_id, post_id)
    if post.status == "completed" and new_status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Edit the completed one-time post to schedule it again",
        )
    await _ensure_actor(session, actor_user_id)
    post.status = new_status
    post.updated_by_user_id = actor_user_id
    post.updated_at = utcnow_utc_tz()
    post.lease_until = None
    session.add(post)
    await session.flush()
    await session.refresh(post)
    return to_read_model(post)


async def delete_scheduled_post(session: AsyncSession, server_id: int, post_id: UUID) -> None:
    post = await get_scheduled_post(session, server_id, post_id)
    await session.delete(post)


async def list_scheduled_post_runs(
    session: AsyncSession, server_id: int, *, limit: int = 100
) -> list[ScheduledPostRunReadModel]:
    rows = (
        await session.exec(
            select(ScheduledBotPostRun)
            .join(ScheduledBotPost, ScheduledBotPost.id == ScheduledBotPostRun.scheduled_post_id)
            .where(ScheduledBotPost.server_id == server_id)
            .order_by(ScheduledBotPostRun.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    return [to_run_read_model(row) for row in rows]


def _next_occurrence(post: ScheduledBotPost, *, now: datetime) -> datetime | None:
    if post.schedule_type == "once" or post.interval_seconds is None:
        return None
    step = timedelta(seconds=post.interval_seconds)
    candidate = post.next_run_at + step
    if candidate <= now:
        missed = int((now - candidate).total_seconds() // post.interval_seconds) + 1
        candidate += step * missed
    return candidate


async def claim_due_scheduled_post(
    session: AsyncSession, *, now: datetime | None = None
) -> tuple[ScheduledBotPost, ScheduledBotPostRun] | None:
    claim_time = now or utcnow_utc_tz()
    post = (
        await session.exec(
            select(ScheduledBotPost)
            .where(
                ScheduledBotPost.status == "active",
                ScheduledBotPost.next_run_at <= claim_time,
                (
                    ScheduledBotPost.lease_until.is_(None)
                    | (ScheduledBotPost.lease_until < claim_time)
                ),
            )
            .order_by(ScheduledBotPost.next_run_at, ScheduledBotPost.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).first()
    if post is None:
        return None

    scheduled_for = post.next_run_at
    existing = (
        await session.exec(
            select(ScheduledBotPostRun).where(
                ScheduledBotPostRun.scheduled_post_id == post.id,
                ScheduledBotPostRun.scheduled_for == scheduled_for,
            )
        )
    ).first()
    if existing is not None:
        if existing.status == "claimed":
            existing.status = "skipped"
            existing.error_text = "Worker stopped while delivery state was unknown; skipped to prevent a duplicate"
            existing.finished_at = claim_time
            session.add(existing)
        next_run = _next_occurrence(post, now=claim_time)
        post.status = "active" if next_run is not None else "completed"
        if next_run is not None:
            post.next_run_at = next_run
        post.lease_until = None
        post.updated_at = claim_time
        session.add(post)
        await session.flush()
        return None

    run = ScheduledBotPostRun(
        scheduled_post_id=post.id,
        scheduled_for=scheduled_for,
        status="claimed",
    )
    session.add(run)
    post.lease_until = claim_time + LEASE_DURATION
    session.add(post)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return None
    await session.refresh(run)
    return post, run


async def deliver_claimed_scheduled_post(
    session: AsyncSession,
    *,
    post: ScheduledBotPost,
    run: ScheduledBotPostRun,
) -> None:
    await session.refresh(post)
    await session.refresh(run)
    if post.status != "active" or post.next_run_at != run.scheduled_for:
        now = utcnow_utc_tz()
        run.status = "skipped"
        run.error_text = "Schedule was paused or edited before delivery"
        run.finished_at = now
        post.lease_until = None
        post.updated_at = now
        session.add(run)
        session.add(post)
        await session.commit()
        return
    try:
        audit = await send_bot_message(
            session,
            server_id=post.server_id,
            actor_user_id=post.created_by_user_id,
            body=BotMessageCreateModel(
                channel_id=str(post.channel_id),
                content=post.content,
                mention_everyone=post.mention_everyone,
                mention_user_ids=post.mention_user_ids,
                mention_role_ids=post.mention_role_ids,
            ),
            source="scheduled",
        )
        run.status = "sent"
        run.bot_message_audit_id = audit.id
        run.error_text = None
    except Exception as error:
        run.status = "failed"
        run.error_text = str(getattr(error, "detail", error))[:2000]
    now = utcnow_utc_tz()
    run.finished_at = now
    post.last_run_at = now
    next_run = _next_occurrence(post, now=now)
    post.status = "active" if next_run is not None else "completed"
    if next_run is not None:
        post.next_run_at = next_run
    post.lease_until = None
    post.updated_at = now
    session.add(run)
    session.add(post)
    await session.commit()


async def send_scheduled_post_now(
    session: AsyncSession,
    *,
    server_id: int,
    post_id: UUID,
    actor_user_id: int,
) -> ScheduledPostRunReadModel:
    post = await get_scheduled_post(session, server_id, post_id)
    now = utcnow_utc_tz()
    run = ScheduledBotPostRun(scheduled_post_id=post.id, scheduled_for=now, status="claimed")
    session.add(run)
    await session.flush()
    try:
        audit = await send_bot_message(
            session,
            server_id=server_id,
            actor_user_id=actor_user_id,
            body=BotMessageCreateModel(
                channel_id=str(post.channel_id),
                content=post.content,
                mention_everyone=post.mention_everyone,
                mention_user_ids=post.mention_user_ids,
                mention_role_ids=post.mention_role_ids,
            ),
            source="scheduled",
        )
        run.status = "sent"
        run.bot_message_audit_id = audit.id
        run.error_text = None
    except Exception as error:
        run.status = "failed"
        run.error_text = str(getattr(error, "detail", error))[:2000]
        run.finished_at = utcnow_utc_tz()
        session.add(run)
        await session.commit()
        raise
    run.finished_at = utcnow_utc_tz()
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return to_run_read_model(run)

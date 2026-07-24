import asyncio
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.youtube_channels import (
    YouTubeChannelSubscriptionCreateModel,
    YouTubeChannelSubscriptionListModel,
    YouTubeChannelSubscriptionReadModel,
    YouTubeChannelSubscriptionUpdateModel,
    YouTubeChannelVideoListModel,
    YouTubeChannelVideoReadModel,
)
from src.db.models import (
    AIKnowledgeSource,
    GlobalUser,
    Server,
    YouTubeChannelSubscription,
    YouTubeChannelVideo,
    utcnow_utc_tz,
)
from src.modules.ai.youtube_channel_errors import public_youtube_channel_error
from src.modules.ai.youtube_channel_sync import sync_youtube_channel_subscription
from src.modules.ai.youtube_data import YouTubeDataClient, YouTubeDataError


async def list_youtube_channel_subscriptions(
    session: AsyncSession,
    *,
    server_id: int,
) -> YouTubeChannelSubscriptionListModel:
    subscriptions = (
        await session.exec(
            select(YouTubeChannelSubscription)
            .where(YouTubeChannelSubscription.server_id == server_id)
            .order_by(YouTubeChannelSubscription.created_at.desc())
        )
    ).all()
    counts = await _video_counts(session, [item.id for item in subscriptions if item.id is not None])
    return YouTubeChannelSubscriptionListModel(
        items=[
            _subscription_to_model(
                item,
                video_count=counts.get(item.id, (0, 0))[0],
                linked_video_count=counts.get(item.id, (0, 0))[1],
            )
            for item in subscriptions
        ]
    )


async def create_youtube_channel_subscription(
    session: AsyncSession,
    *,
    server_id: int,
    created_by_user_id: int,
    body: YouTubeChannelSubscriptionCreateModel,
    client: YouTubeDataClient | None = None,
) -> YouTubeChannelSubscriptionReadModel:
    try:
        active_client = client or YouTubeDataClient()
        channel = await asyncio.to_thread(active_client.resolve_channel, body.channel_url)
    except YouTubeDataError as exc:
        raise _youtube_data_http_exception(exc) from exc

    existing = (
        await session.exec(
            select(YouTubeChannelSubscription).where(
                YouTubeChannelSubscription.server_id == server_id,
                YouTubeChannelSubscription.channel_id == channel.channel_id,
            )
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "youtube_channel_already_subscribed",
                "message": "This YouTube channel is already subscribed.",
            },
        )

    await _ensure_server(session, server_id)
    await _ensure_global_user(session, created_by_user_id)
    now = utcnow_utc_tz()
    subscription = YouTubeChannelSubscription(
        server_id=server_id,
        channel_id=channel.channel_id,
        handle=channel.handle,
        canonical_url=channel.canonical_url,
        title=channel.title[:255],
        description=channel.description or None,
        thumbnail_url=channel.thumbnail_url,
        uploads_playlist_id=channel.uploads_playlist_id,
        status="enabled",
        auto_index_new_videos=body.auto_index_new_videos,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(subscription)
    await session.flush()
    await sync_youtube_channel_subscription(
        session,
        subscription,
        client=active_client,
        resolved_channel=channel,
        auto_index_new=False,
    )
    count, linked = (await _video_counts(session, [subscription.id])).get(subscription.id, (0, 0))
    return _subscription_to_model(subscription, video_count=count, linked_video_count=linked)


async def update_youtube_channel_subscription(
    session: AsyncSession,
    *,
    server_id: int,
    subscription_id: UUID,
    body: YouTubeChannelSubscriptionUpdateModel,
) -> YouTubeChannelSubscriptionReadModel:
    subscription = await _get_subscription(session, server_id=server_id, subscription_id=subscription_id)
    if body.status is not None:
        subscription.status = body.status
        if body.status == "enabled":
            subscription.next_sync_at = utcnow_utc_tz()
    if body.auto_index_new_videos is not None:
        subscription.auto_index_new_videos = body.auto_index_new_videos
    subscription.updated_at = utcnow_utc_tz()
    session.add(subscription)
    await session.flush()
    count, linked = (await _video_counts(session, [subscription.id])).get(subscription.id, (0, 0))
    return _subscription_to_model(subscription, video_count=count, linked_video_count=linked)


async def delete_youtube_channel_subscription(
    session: AsyncSession,
    *,
    server_id: int,
    subscription_id: UUID,
) -> None:
    subscription = await _get_subscription(session, server_id=server_id, subscription_id=subscription_id)
    await session.exec(
        delete(YouTubeChannelVideo).where(YouTubeChannelVideo.subscription_id == subscription.id)
    )
    await session.delete(subscription)
    await session.flush()


async def sync_youtube_channel_now(
    session: AsyncSession,
    *,
    server_id: int,
    subscription_id: UUID,
    client: YouTubeDataClient | None = None,
) -> YouTubeChannelSubscriptionReadModel:
    subscription = await _get_subscription(session, server_id=server_id, subscription_id=subscription_id)
    await sync_youtube_channel_subscription(session, subscription, client=client)
    count, linked = (await _video_counts(session, [subscription.id])).get(subscription.id, (0, 0))
    return _subscription_to_model(subscription, video_count=count, linked_video_count=linked)


async def list_youtube_channel_videos(
    session: AsyncSession,
    *,
    server_id: int,
    subscription_id: UUID,
    limit: int = 200,
) -> YouTubeChannelVideoListModel:
    await _get_subscription(session, server_id=server_id, subscription_id=subscription_id)
    rows = (
        await session.exec(
            select(YouTubeChannelVideo, AIKnowledgeSource.status)
            .outerjoin(
                AIKnowledgeSource,
                AIKnowledgeSource.id == YouTubeChannelVideo.knowledge_source_id,
            )
            .where(
                YouTubeChannelVideo.server_id == server_id,
                YouTubeChannelVideo.subscription_id == subscription_id,
            )
            .order_by(
                YouTubeChannelVideo.published_at.desc(),
                YouTubeChannelVideo.discovered_at.desc(),
            )
            .limit(min(max(int(limit), 1), 500))
        )
    ).all()
    return YouTubeChannelVideoListModel(
        items=[_video_to_model(video, knowledge_source_status=source_status) for video, source_status in rows]
    )


async def link_youtube_channel_video_source(
    session: AsyncSession,
    *,
    server_id: int,
    subscription_id: UUID,
    video_id: str,
    knowledge_source_id: UUID | None,
) -> YouTubeChannelVideoReadModel:
    video = (
        await session.exec(
            select(YouTubeChannelVideo).where(
                YouTubeChannelVideo.server_id == server_id,
                YouTubeChannelVideo.subscription_id == subscription_id,
                YouTubeChannelVideo.video_id == video_id,
            )
        )
    ).first()
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="YouTube channel video not found")

    source_status = None
    if knowledge_source_id is not None:
        source = await session.get(AIKnowledgeSource, knowledge_source_id)
        if source is None or source.server_id != server_id or source.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI knowledge source not found")
        existing_link = (
            await session.exec(
                select(YouTubeChannelVideo).where(
                    YouTubeChannelVideo.knowledge_source_id == knowledge_source_id,
                    YouTubeChannelVideo.id != video.id,
                )
            )
        ).first()
        if existing_link is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This knowledge source is already linked to another YouTube video",
            )
        source_status = source.status

    video.knowledge_source_id = knowledge_source_id
    video.updated_at = utcnow_utc_tz()
    session.add(video)
    await session.flush()
    return _video_to_model(video, knowledge_source_status=source_status)


async def _get_subscription(
    session: AsyncSession,
    *,
    server_id: int,
    subscription_id: UUID,
) -> YouTubeChannelSubscription:
    subscription = await session.get(YouTubeChannelSubscription, subscription_id)
    if subscription is None or subscription.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="YouTube channel subscription not found")
    return subscription


async def _video_counts(
    session: AsyncSession,
    subscription_ids: list[UUID],
) -> dict[UUID, tuple[int, int]]:
    if not subscription_ids:
        return {}
    rows = (
        await session.exec(
            select(
                YouTubeChannelVideo.subscription_id,
                func.count(YouTubeChannelVideo.id),
                func.count(YouTubeChannelVideo.knowledge_source_id),
            )
            .where(YouTubeChannelVideo.subscription_id.in_(subscription_ids))
            .group_by(YouTubeChannelVideo.subscription_id)
        )
    ).all()
    return {subscription_id: (int(count), int(linked)) for subscription_id, count, linked in rows}


def _subscription_to_model(
    subscription: YouTubeChannelSubscription,
    *,
    video_count: int,
    linked_video_count: int,
) -> YouTubeChannelSubscriptionReadModel:
    return YouTubeChannelSubscriptionReadModel(
        id=str(subscription.id),
        server_id=str(subscription.server_id),
        channel_id=subscription.channel_id,
        handle=subscription.handle,
        canonical_url=subscription.canonical_url,
        title=subscription.title,
        description=subscription.description,
        thumbnail_url=subscription.thumbnail_url,
        status=subscription.status,
        auto_index_new_videos=subscription.auto_index_new_videos,
        video_count=video_count,
        linked_video_count=linked_video_count,
        last_synced_at=subscription.last_synced_at,
        next_sync_at=subscription.next_sync_at,
        error_code=subscription.error_code,
        error_message=public_youtube_channel_error(subscription.error_code, subscription.error_message),
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


def _video_to_model(
    video: YouTubeChannelVideo,
    *,
    knowledge_source_status: str | None,
) -> YouTubeChannelVideoReadModel:
    return YouTubeChannelVideoReadModel(
        id=str(video.id),
        video_id=video.video_id,
        title=video.title,
        description=video.description,
        published_at=video.published_at,
        duration_seconds=video.duration_seconds,
        thumbnail_url=video.thumbnail_url,
        availability=video.availability,
        captions_available=video.captions_available,
        knowledge_source_id=str(video.knowledge_source_id) if video.knowledge_source_id else None,
        knowledge_source_status=knowledge_source_status,
        discovered_at=video.discovered_at,
        updated_at=video.updated_at,
    )


def _youtube_data_http_exception(exc: YouTubeDataError) -> HTTPException:
    if exc.code == "youtube_channel_url_invalid":
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif exc.code == "youtube_channel_not_found":
        status_code = status.HTTP_404_NOT_FOUND
    elif exc.code in {"youtube_data_not_configured", "youtube_data_auth_failed"}:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif exc.status_code == 429:
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        status_code = status.HTTP_502_BAD_GATEWAY
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.safe_message},
    )


async def _ensure_server(session: AsyncSession, server_id: int) -> None:
    if await session.get(Server, server_id) is None:
        session.add(Server(server_id=server_id, server_name=str(server_id)))
        await session.flush()


async def _ensure_global_user(session: AsyncSession, user_id: int) -> None:
    if await session.get(GlobalUser, user_id) is None:
        session.add(GlobalUser(discord_id=user_id, username=None))
        await session.flush()

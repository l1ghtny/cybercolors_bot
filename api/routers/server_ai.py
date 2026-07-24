from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_dashboard_access
from api.dependencies.server_access import require_server_permission
from api.models.ai_knowledge import (
    AIKnowledgeJobListModel,
    AIKnowledgeJobReadModel,
    AIKnowledgeProcessOneResponseModel,
    AIKnowledgeSearchRequestModel,
    AIKnowledgeSearchResponseModel,
    AIKnowledgeSourceCreateModel,
    AIKnowledgeSourceListModel,
    AIKnowledgeSourceReadModel,
    AIKnowledgeSourceUpdateModel,
)
from api.models.ai_moderation import (
    AIApproveSuggestionModel,
    AIBulkDismissSuggestionsModel,
    AIBulkDismissSuggestionsResponseModel,
    AIDismissSuggestionModel,
    AIModerationDecisionListModel,
    AIResolveSuggestionResponseModel,
    AISuggestionStatusFilter,
    AITweakSuggestionModel,
)
from api.models.youtube_channels import (
    YouTubeChannelSubscriptionCreateModel,
    YouTubeChannelSubscriptionListModel,
    YouTubeChannelSubscriptionReadModel,
    YouTubeChannelSubscriptionUpdateModel,
    YouTubeChannelVideoLinkModel,
    YouTubeChannelVideoListModel,
    YouTubeChannelVideoReadModel,
)
from api.services.ai_knowledge import (
    create_file_knowledge_source,
    create_knowledge_source,
    delete_knowledge_source,
    get_knowledge_source,
    list_knowledge_jobs,
    list_knowledge_sources,
    process_one_knowledge_job,
    queue_knowledge_source_reindex,
    search_knowledge_sources,
    update_knowledge_source,
)
from api.services.ai_moderation import (
    approve_ai_suggestion,
    bulk_dismiss_ai_suggestions,
    dismiss_ai_suggestion,
    list_ai_decisions,
    list_ai_suggestions,
    tweak_ai_suggestion,
)
from api.services.youtube_channels import (
    create_youtube_channel_subscription,
    delete_youtube_channel_subscription,
    link_youtube_channel_video_source,
    list_youtube_channel_subscriptions,
    list_youtube_channel_videos,
    sync_youtube_channel_now,
    update_youtube_channel_subscription,
)
from src.db.database import get_session

server_ai_router = APIRouter(
    prefix="/servers/{server_id}/ai",
    dependencies=[Depends(require_server_dashboard_access)],
)


@server_ai_router.get(
    "/suggestions",
    response_model=AIModerationDecisionListModel,
    dependencies=[Depends(require_server_permission("ai.suggestions.view"))],
)
async def get_ai_suggestions(
    server_id: int,
    status: AISuggestionStatusFilter = Query(default="pending"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await list_ai_suggestions(
        session=session,
        server_id=server_id,
        status_filter=status,
        cursor=cursor,
        limit=limit,
    )


@server_ai_router.post("/suggestions/{suggestion_id}/approve", response_model=AIResolveSuggestionResponseModel)
async def approve_suggestion(
    server_id: int,
    suggestion_id: UUID,
    body: AIApproveSuggestionModel | None = None,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("ai.suggestions.review")),
):
    return await approve_ai_suggestion(
        session=session,
        server_id=server_id,
        suggestion_id=suggestion_id,
        moderator_user_id=current_user_id,
        body=body or AIApproveSuggestionModel(),
    )


@server_ai_router.post("/suggestions/{suggestion_id}/tweak", response_model=AIResolveSuggestionResponseModel)
async def tweak_suggestion(
    server_id: int,
    suggestion_id: UUID,
    body: AITweakSuggestionModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("ai.suggestions.review")),
):
    return await tweak_ai_suggestion(
        session=session,
        server_id=server_id,
        suggestion_id=suggestion_id,
        moderator_user_id=current_user_id,
        body=body,
    )


@server_ai_router.post(
    "/suggestions/bulk-dismiss",
    response_model=AIBulkDismissSuggestionsResponseModel,
)
async def bulk_dismiss_suggestions(
    server_id: int,
    body: AIBulkDismissSuggestionsModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("ai.suggestions.review")),
):
    return await bulk_dismiss_ai_suggestions(
        session=session,
        server_id=server_id,
        moderator_user_id=current_user_id,
        body=body,
    )


@server_ai_router.post("/suggestions/{suggestion_id}/dismiss", response_model=AIResolveSuggestionResponseModel)
async def dismiss_suggestion(
    server_id: int,
    suggestion_id: UUID,
    body: AIDismissSuggestionModel | None = None,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("ai.suggestions.review")),
):
    return await dismiss_ai_suggestion(
        session=session,
        server_id=server_id,
        suggestion_id=suggestion_id,
        moderator_user_id=current_user_id,
        body=body or AIDismissSuggestionModel(),
    )


@server_ai_router.get(
    "/decisions",
    response_model=AIModerationDecisionListModel,
    dependencies=[Depends(require_server_permission("ai.decisions.view"))],
)
async def get_ai_decisions(
    server_id: int,
    status: AISuggestionStatusFilter = Query(default="all"),
    flagged: bool | None = Query(default=None),
    author_user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    channel_id: str | None = Query(default=None, pattern=r"^\d+$"),
    suggested_action: str | None = Query(default=None),
    selected_action: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await list_ai_decisions(
        session=session,
        server_id=server_id,
        status_filter=status,
        flagged=flagged,
        author_user_id=int(author_user_id) if author_user_id else None,
        channel_id=int(channel_id) if channel_id else None,
        suggested_action=suggested_action,
        selected_action=selected_action,
        since=since,
        until=until,
        cursor=cursor,
        limit=limit,
    )


@server_ai_router.get(
    "/knowledge",
    response_model=AIKnowledgeSourceListModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.view"))],
)
async def get_ai_knowledge_sources(
    server_id: int,
    status: str | None = Query(default=None),
    visibility: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    subject_type: str | None = Query(default=None),
    subject_user_id: int | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await list_knowledge_sources(
        session=session,
        server_id=server_id,
        status_filter=status,
        visibility=visibility,
        source_type=source_type,
        subject_type=subject_type,
        subject_user_id=subject_user_id,
        include_deleted=include_deleted,
        limit=limit,
    )


@server_ai_router.post(
    "/knowledge",
    response_model=AIKnowledgeSourceReadModel,
)
async def create_ai_knowledge_source(
    server_id: int,
    body: AIKnowledgeSourceCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("ai.knowledge.manage")),
):
    return await create_knowledge_source(
        session=session,
        server_id=server_id,
        body=body,
        created_by_user_id=current_user_id,
    )


@server_ai_router.post(
    "/knowledge/file",
    response_model=AIKnowledgeSourceReadModel,
)
async def upload_ai_knowledge_file(
    server_id: int,
    title: str = Form(..., min_length=1, max_length=255),
    subject_type: str = Form(default="server"),
    subject_user_id: int | None = Form(default=None),
    visibility: str = Form(default="public_answer"),
    queue_index: bool = Form(default=True),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("ai.knowledge.manage")),
):
    payload = await file.read()
    return await create_file_knowledge_source(
        session=session,
        server_id=server_id,
        created_by_user_id=current_user_id,
        title=title,
        payload=payload,
        filename=file.filename or "upload",
        content_type=file.content_type,
        subject_type=subject_type,
        subject_user_id=subject_user_id,
        visibility=visibility,
        queue_index=queue_index,
    )


@server_ai_router.post(
    "/knowledge/search",
    response_model=AIKnowledgeSearchResponseModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.view"))],
)
async def search_ai_knowledge_sources(
    server_id: int,
    body: AIKnowledgeSearchRequestModel,
    session: AsyncSession = Depends(get_session),
):
    return await search_knowledge_sources(session=session, server_id=server_id, body=body)


@server_ai_router.get(
    "/knowledge/jobs",
    response_model=AIKnowledgeJobListModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.manage"))],
)
async def get_ai_knowledge_jobs(
    server_id: int,
    status: str | None = Query(default=None),
    source_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await list_knowledge_jobs(
        session=session,
        server_id=server_id,
        status_filter=status,
        source_id=source_id,
        limit=limit,
    )


@server_ai_router.post(
    "/knowledge/jobs/process-one",
    response_model=AIKnowledgeProcessOneResponseModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.manage"))],
)
async def process_one_ai_knowledge_job(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    return await process_one_knowledge_job(session=session, server_id=server_id)


@server_ai_router.get(
    "/knowledge/{source_id}",
    response_model=AIKnowledgeSourceReadModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.view"))],
)
async def get_ai_knowledge_source(
    server_id: int,
    source_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    return await get_knowledge_source(session=session, server_id=server_id, source_id=source_id)


@server_ai_router.put(
    "/knowledge/{source_id}",
    response_model=AIKnowledgeSourceReadModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.manage"))],
)
async def update_ai_knowledge_source(
    server_id: int,
    source_id: UUID,
    body: AIKnowledgeSourceUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    return await update_knowledge_source(session=session, server_id=server_id, source_id=source_id, body=body)


@server_ai_router.delete(
    "/knowledge/{source_id}",
    status_code=204,
    dependencies=[Depends(require_server_permission("ai.knowledge.manage"))],
)
async def delete_ai_knowledge_source(
    server_id: int,
    source_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    await delete_knowledge_source(session=session, server_id=server_id, source_id=source_id)


@server_ai_router.post(
    "/knowledge/{source_id}/reindex",
    response_model=AIKnowledgeJobReadModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.manage"))],
)
async def reindex_ai_knowledge_source(
    server_id: int,
    source_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    return await queue_knowledge_source_reindex(session=session, server_id=server_id, source_id=source_id)


@server_ai_router.get(
    "/youtube-channels",
    response_model=YouTubeChannelSubscriptionListModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.view"))],
)
async def get_youtube_channel_subscriptions(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    return await list_youtube_channel_subscriptions(session, server_id=server_id)


@server_ai_router.post(
    "/youtube-channels",
    response_model=YouTubeChannelSubscriptionReadModel,
)
async def create_youtube_channel_subscription_route(
    server_id: int,
    body: YouTubeChannelSubscriptionCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("ai.knowledge.manage")),
):
    return await create_youtube_channel_subscription(
        session,
        server_id=server_id,
        created_by_user_id=current_user_id,
        body=body,
    )


@server_ai_router.put(
    "/youtube-channels/{subscription_id}",
    response_model=YouTubeChannelSubscriptionReadModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.manage"))],
)
async def update_youtube_channel_subscription_route(
    server_id: int,
    subscription_id: UUID,
    body: YouTubeChannelSubscriptionUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    return await update_youtube_channel_subscription(
        session,
        server_id=server_id,
        subscription_id=subscription_id,
        body=body,
    )


@server_ai_router.delete(
    "/youtube-channels/{subscription_id}",
    status_code=204,
    dependencies=[Depends(require_server_permission("ai.knowledge.manage"))],
)
async def delete_youtube_channel_subscription_route(
    server_id: int,
    subscription_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    await delete_youtube_channel_subscription(
        session,
        server_id=server_id,
        subscription_id=subscription_id,
    )


@server_ai_router.post(
    "/youtube-channels/{subscription_id}/sync",
    response_model=YouTubeChannelSubscriptionReadModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.manage"))],
)
async def sync_youtube_channel_subscription_route(
    server_id: int,
    subscription_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    return await sync_youtube_channel_now(
        session,
        server_id=server_id,
        subscription_id=subscription_id,
    )


@server_ai_router.get(
    "/youtube-channels/{subscription_id}/videos",
    response_model=YouTubeChannelVideoListModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.view"))],
)
async def get_youtube_channel_videos(
    server_id: int,
    subscription_id: UUID,
    limit: int = Query(default=200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    return await list_youtube_channel_videos(
        session,
        server_id=server_id,
        subscription_id=subscription_id,
        limit=limit,
    )


@server_ai_router.put(
    "/youtube-channels/{subscription_id}/videos/{video_id}/link",
    response_model=YouTubeChannelVideoReadModel,
    dependencies=[Depends(require_server_permission("ai.knowledge.manage"))],
)
async def link_youtube_channel_video_source_route(
    server_id: int,
    subscription_id: UUID,
    video_id: str,
    body: YouTubeChannelVideoLinkModel,
    session: AsyncSession = Depends(get_session),
):
    return await link_youtube_channel_video_source(
        session,
        server_id=server_id,
        subscription_id=subscription_id,
        video_id=video_id,
        knowledge_source_id=body.knowledge_source_id,
    )

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.models.scheduled_posts import (
    ScheduledPostReadModel,
    ScheduledPostRunReadModel,
    ScheduledPostStatusModel,
    ScheduledPostWriteModel,
)
from api.services.scheduled_posts import (
    create_scheduled_post,
    delete_scheduled_post,
    list_scheduled_post_runs,
    list_scheduled_posts,
    send_scheduled_post_now,
    set_scheduled_post_status,
    update_scheduled_post,
)
from src.db.database import get_session


scheduled_posts_router = APIRouter(
    prefix="/servers/{server_id}/scheduled-posts",
    dependencies=[Depends(require_server_dashboard_access)],
)


@scheduled_posts_router.get("", response_model=list[ScheduledPostReadModel])
async def get_scheduled_posts(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await list_scheduled_posts(session, server_id)


@scheduled_posts_router.get("/runs", response_model=list[ScheduledPostRunReadModel])
async def get_scheduled_post_runs(
    server_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await list_scheduled_post_runs(session, server_id, limit=limit)


@scheduled_posts_router.post("", response_model=ScheduledPostReadModel, status_code=status.HTTP_201_CREATED)
async def post_scheduled_post(
    server_id: int,
    body: ScheduledPostWriteModel,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await create_scheduled_post(
        session, server_id=server_id, actor_user_id=actor_user_id, body=body
    )


@scheduled_posts_router.put("/{post_id}", response_model=ScheduledPostReadModel)
async def put_scheduled_post(
    server_id: int,
    post_id: UUID,
    body: ScheduledPostWriteModel,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await update_scheduled_post(
        session,
        server_id=server_id,
        post_id=post_id,
        actor_user_id=actor_user_id,
        body=body,
    )


@scheduled_posts_router.patch("/{post_id}/status", response_model=ScheduledPostReadModel)
async def patch_scheduled_post_status(
    server_id: int,
    post_id: UUID,
    body: ScheduledPostStatusModel,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await set_scheduled_post_status(
        session,
        server_id=server_id,
        post_id=post_id,
        actor_user_id=actor_user_id,
        new_status=body.status,
    )


@scheduled_posts_router.post("/{post_id}/send-now", response_model=ScheduledPostRunReadModel)
async def post_scheduled_post_now(
    server_id: int,
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    return await send_scheduled_post_now(
        session,
        server_id=server_id,
        post_id=post_id,
        actor_user_id=actor_user_id,
    )


@scheduled_posts_router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_scheduled_post(
    server_id: int,
    post_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("communications.scheduled_posts.manage")),
):
    await delete_scheduled_post(session, server_id, post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

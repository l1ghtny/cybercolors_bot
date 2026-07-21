from fastapi import APIRouter, Depends, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.models.bot_messages import BotMessageAuditReadModel, BotMessageCreateModel
from api.services.bot_messages import list_bot_message_audits, send_bot_message
from src.db.database import get_session


bot_messages_router = APIRouter(
    prefix="/servers/{server_id}/bot-messages",
    dependencies=[Depends(require_server_dashboard_access)],
)


@bot_messages_router.get("", response_model=list[BotMessageAuditReadModel])
async def get_bot_message_audits(
    server_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("audit.timeline.view")),
):
    return await list_bot_message_audits(session, server_id=server_id, limit=limit)


@bot_messages_router.post(
    "",
    response_model=BotMessageAuditReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def create_bot_message(
    server_id: int,
    body: BotMessageCreateModel,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(require_server_permission("communications.send_as_bot")),
):
    return await send_bot_message(
        session,
        server_id=server_id,
        actor_user_id=actor_user_id,
        body=body,
        source="dashboard",
    )

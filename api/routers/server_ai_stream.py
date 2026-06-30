import asyncio
import json
from time import monotonic

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.responses import StreamingResponse

from api.dependencies.current_user import get_discord_user_id_for_access_token
from api.services.ai_moderation import get_ai_suggestion_stream_state
from api.services.dashboard_access_service import assert_dashboard_access
from src.db.database import get_async_session, get_session

server_ai_stream_router = APIRouter(prefix="/servers/{server_id}/ai", tags=["servers:ai"])


def _bearer_from_authorization(authorization: str | None) -> str | None:
    if not authorization:
        return None
    token_type, _, token = authorization.partition(" ")
    if token_type.lower() != "bearer" or not token:
        return None
    return token


async def require_ai_stream_dashboard_access(
    server_id: int,
    access_token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> None:
    resolved_token = access_token or _bearer_from_authorization(authorization)
    if not resolved_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token is required")
    current_user_id = await get_discord_user_id_for_access_token(resolved_token)
    await assert_dashboard_access(
        session=session,
        server_id=server_id,
        caller_user_id=current_user_id,
        access_token=resolved_token,
    )


def _sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=True, default=str)}\n\n"


@server_ai_stream_router.get(
    "/suggestions/stream",
    dependencies=[Depends(require_ai_stream_dashboard_access)],
)
async def stream_ai_suggestions(
    server_id: int,
    request: Request,
    poll_seconds: int = Query(default=5, ge=2, le=60),
):
    async def events():
        last_state: dict | None = None
        last_heartbeat = monotonic()
        while not await request.is_disconnected():
            async with get_async_session() as session:
                state = await get_ai_suggestion_stream_state(session=session, server_id=server_id)
            if state != last_state:
                last_state = dict(state)
                yield _sse_event("ai_suggestions", state)
            elif monotonic() - last_heartbeat >= 30:
                last_heartbeat = monotonic()
                yield ": keepalive\n\n"
            await asyncio.sleep(poll_seconds)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

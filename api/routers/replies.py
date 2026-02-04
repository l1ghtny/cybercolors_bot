from typing import List

from fastapi import APIRouter, Depends, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.bot_replies import ReplyAddModel
from src.db.database import get_session
from src.db.models import Replies

replies = APIRouter(prefix="/replies", tags=["replies"])


@replies.get('/{server_id}')
async def get_replies_by_server_id(server_id: int, session: AsyncSession = Depends(get_session)):

    server_replies = (await session.exec(select(Replies).where(Replies.server_id == server_id).group_by(Replies.bot_reply).order_by(Replies.timestamp.desc()))).all()
    return server_replies


@replies.post('/{server_id}/add_replies')
async def add_replies(body: List[ReplyAddModel], session: AsyncSession = Depends(get_session)):
    for reply in body:
        session.add(Replies(server_id=reply.server_id, bot_reply=reply.bot_reply, created_by_id=reply.created_by_id, user_message=reply.user_message))
    await session.commit()
    return status.HTTP_201_CREATED
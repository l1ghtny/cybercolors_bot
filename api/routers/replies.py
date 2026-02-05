from typing import List

from fastapi import APIRouter, Depends, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.bot_replies import ReplyAddModel
from src.db.database import get_session
from src.db.models import Replies

replies = APIRouter(prefix="/replies", tags=["replies"])


@replies.get('/{server_id}', response_model=List[Replies])
async def get_replies_by_server_id(server_id: int, session: AsyncSession = Depends(get_session)):

    server_replies = (await session.exec(select(Replies).where(Replies.server_id == server_id).order_by(Replies.created_at.desc()))).all()
    return server_replies


@replies.post('/{server_id}/add_replies', status_code=201)
async def add_replies(body: List[ReplyAddModel], session: AsyncSession = Depends(get_session)):
    for reply in body:
        session.add(Replies(server_id=int(reply.server_id), bot_reply=reply.bot_reply, created_by_id=int(reply.admin_id), user_message=reply.user_message))
    await session.commit()
    return status.HTTP_201_CREATED


@replies.post('/{server_id}/delete_replies')
async def delete_replies(body: List[str], session: AsyncSession = Depends(get_session)):
    for reply_id in body:
        reply = (await session.exec(select(Replies).where(Replies.id == reply_id))).first()
        await session.delete(reply)

    await session.commit()

    return status.HTTP_200_OK
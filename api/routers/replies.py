from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_current_discord_user_id
from api.helpers.replies import enrich_user_data
from api.models.bot_replies import (
    ReplyAddModel,
    ReplyDuplicateRequestModel,
    ReplyDuplicateResponseModel,
    ReplyEditModel,
    ReplyModel,
)
from api.services.dashboard_access_service import assert_dashboard_access
from api.services.replies_service import duplicate_selected_replies
from src.db.database import get_session
from src.db.models import Replies, Triggers

replies = APIRouter(prefix="/replies", tags=["replies"])


@replies.get('/{server_id}', response_model=List[ReplyModel])
async def get_replies_by_server_id(server_id: int, session: AsyncSession = Depends(get_session)):
    server_replies = (
        await session.exec(
            select(Replies, Triggers.message)
            .outerjoin(Triggers, Triggers.reply_id == Replies.id)
            .where(Replies.server_id == server_id)
            .order_by(Replies.created_at.desc())
        )
    ).all()
    if not server_replies:
        raise HTTPException(status_code=404, detail="No replies found for this server")

    grouped: dict[UUID, ReplyModel] = {}
    for reply, trigger_message in server_replies:
        if reply.id not in grouped:
            user_data = await enrich_user_data(reply.created_by_id)
            grouped[reply.id] = ReplyModel(
                id=str(reply.id),
                user_messages=[],
                bot_reply=reply.bot_reply,
                created_at=reply.created_at,
                created_by=user_data,
            )
        if trigger_message and trigger_message not in grouped[reply.id].user_messages:
            grouped[reply.id].user_messages.append(trigger_message)

    return list(grouped.values())


@replies.post('/{server_id}/add_replies', status_code=201)
async def add_replies(body: List[ReplyAddModel], session: AsyncSession = Depends(get_session)):
    reply_cache: dict[tuple[int, str], Replies] = {}

    for reply in body:
        server_id_int = int(reply.server_id)
        admin_id_int = int(reply.admin_id)
        reply_key = (server_id_int, reply.bot_reply)

        existing_reply = reply_cache.get(reply_key)
        if not existing_reply:
            existing_reply = (
                await session.exec(
                    select(Replies).where(
                        Replies.server_id == server_id_int,
                        Replies.bot_reply == reply.bot_reply,
                    )
                )
            ).first()
            if not existing_reply:
                existing_reply = Replies(
                    server_id=server_id_int,
                    bot_reply=reply.bot_reply,
                    created_by_id=admin_id_int,
                )
                session.add(existing_reply)
                await session.flush()
            reply_cache[reply_key] = existing_reply

        trigger = (
            await session.exec(
                select(Triggers).where(
                    Triggers.reply_id == existing_reply.id,
                    Triggers.message == reply.user_message,
                )
            )
        ).first()
        if not trigger:
            session.add(Triggers(message=reply.user_message, reply_id=existing_reply.id))

    await session.commit()
    return status.HTTP_201_CREATED


@replies.post('/{server_id}/delete_replies')
async def delete_replies(body: List[UUID], session: AsyncSession = Depends(get_session)):
    for reply_id in body:
        reply = (await session.exec(select(Replies).where(Replies.id == reply_id))).first()
        if reply:
            triggers = (await session.exec(select(Triggers).where(Triggers.reply_id == reply.id))).all()
            for trigger in triggers:
                await session.delete(trigger)
            await session.delete(reply)

    await session.commit()

    return status.HTTP_200_OK


@replies.post('/{server_id}/edit_replies')
async def edit_replies(body: List[ReplyEditModel], session: AsyncSession = Depends(get_session)):
    for reply in body:
        existing_reply = (await session.exec(select(Replies).where(Replies.id == reply.id))).first()
        if existing_reply:
            existing_reply.bot_reply = reply.bot_reply

            existing_trigger = (
                await session.exec(
                    select(Triggers).where(
                        Triggers.reply_id == existing_reply.id,
                        Triggers.message == reply.user_message,
                    )
                )
            ).first()
            if not existing_trigger:
                session.add(Triggers(message=reply.user_message, reply_id=existing_reply.id))

    await session.commit()

    return status.HTTP_200_OK


@replies.post("/{server_id}/duplicate-selected", response_model=ReplyDuplicateResponseModel)
async def duplicate_selected_replies_to_server(
    server_id: int,
    body: ReplyDuplicateRequestModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    authorization: Annotated[str | None, Header()] = None,
):
    target_server_id = int(body.target_server_id)
    if target_server_id == server_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target_server_id must be different from source server",
        )

    await assert_dashboard_access(
        session=session,
        server_id=server_id,
        caller_user_id=current_user_id,
        authorization=authorization,
    )
    await assert_dashboard_access(
        session=session,
        server_id=target_server_id,
        caller_user_id=current_user_id,
        authorization=authorization,
    )

    result = await duplicate_selected_replies(
        session=session,
        source_server_id=server_id,
        target_server_id=target_server_id,
        reply_ids=body.reply_ids,
        actor_user_id=current_user_id,
    )
    await session.commit()
    return result

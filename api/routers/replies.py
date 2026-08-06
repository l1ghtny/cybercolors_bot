from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.auth import get_bearer_access_token
from api.dependencies.current_user import get_current_discord_user_id
from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.helpers.replies import enrich_user_data
from api.models.bot_replies import (
    ReplyAddModel,
    ReplyConceptCreateModel,
    ReplyConceptModel,
    ReplyConceptUpdateModel,
    ReplyDuplicateRequestModel,
    ReplyDuplicateResponseModel,
    ReplyEditModel,
    ReplyIntentCreateModel,
    ReplyIntentUpdateModel,
    ReplyModel,
    ReplyMutationResponseModel,
    ReplySettingsModel,
    ReplySettingsUpdateModel,
    ReplyTriggerCoverageRequestModel,
    ReplyTriggerCoverageResponseModel,
    ReplyTriggerVariationPreviewRequestModel,
    ReplyTriggerVariationPreviewResponseModel,
    ReplyVariationSuggestionRequestModel,
    ReplyVariationSuggestionResponseModel,
)
from api.services.dashboard_access_service import assert_dashboard_access
from api.services.replies_service import (
    ReplyConceptInUseError,
    ReplyConfigurationConflict,
    create_reply_concept,
    create_reply_intent,
    delete_reply_concept,
    duplicate_selected_replies,
    get_or_create_reply_settings,
    list_reply_concepts,
    preview_reply_trigger_coverage,
    preview_reply_trigger_variations,
    to_reply_concept_model,
    to_reply_settings_model,
    update_reply_concept,
    update_reply_intent,
    update_reply_settings,
)
from api.services.reply_variations import (
    ReplyVariationGenerationError,
    suggest_reply_variations,
)
from api.services.rbac_service import assert_user_has_permission
from src.db.database import get_session
from src.db.models import Replies, ReplyConcept, Triggers
from src.modules.on_message_processing.reply_matcher import invalidate_reply_matcher

replies = APIRouter(
    prefix="/replies",
    tags=["replies"],
    dependencies=[Depends(require_server_dashboard_access)],
)


def _group_reply_edits(
    body: List[ReplyEditModel],
) -> dict[UUID, tuple[str, set[str]]]:
    grouped: dict[UUID, tuple[str, set[str]]] = {}
    for edit in body:
        existing = grouped.get(edit.id)
        if existing is None:
            grouped[edit.id] = (edit.bot_reply, {edit.user_message})
            continue
        bot_reply, messages = existing
        if bot_reply != edit.bot_reply:
            raise ValueError("All edits for one reply must use the same bot_reply")
        messages.add(edit.user_message)
    return grouped


def _plan_trigger_sync(
    existing_triggers: list[Triggers],
    desired_messages: set[str],
) -> tuple[list[Triggers], set[str]]:
    existing_messages = {trigger.message for trigger in existing_triggers}
    to_delete = [
        trigger for trigger in existing_triggers if trigger.message not in desired_messages
    ]
    return to_delete, desired_messages - existing_messages


async def require_duplicate_target_server_replies_manage(
    body: ReplyDuplicateRequestModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    access_token: str = Depends(get_bearer_access_token),
) -> int:
    target_server_id = int(body.target_server_id)
    await assert_dashboard_access(
        session=session,
        server_id=target_server_id,
        caller_user_id=current_user_id,
        access_token=access_token,
    )
    await assert_user_has_permission(
        session=session,
        server_id=target_server_id,
        user_id=current_user_id,
        permission_key="replies.manage",
        access_token=access_token,
    )
    return target_server_id


@replies.get('/{server_id}', response_model=List[ReplyModel])
async def get_replies_by_server_id(server_id: int, session: AsyncSession = Depends(get_session)):
    server_replies = (
        await session.exec(
            select(Replies, Triggers)
            .outerjoin(Triggers, Triggers.reply_id == Replies.id)
            .where(Replies.server_id == server_id)
            .order_by(Replies.created_at.desc())
        )
    ).all()
    if not server_replies:
        raise HTTPException(status_code=404, detail="No replies found for this server")

    grouped: dict[UUID, ReplyModel] = {}
    for reply, trigger in server_replies:
        if reply.id not in grouped:
            user_data = await enrich_user_data(reply.created_by_id, server_id=server_id)
            grouped[reply.id] = ReplyModel(
                id=str(reply.id),
                user_messages=[],
                bot_reply=reply.bot_reply,
                created_at=reply.created_at,
                created_by=user_data,
                mention_user_ids=list(reply.mention_user_ids or []),
                mention_role_ids=list(reply.mention_role_ids or []),
                cooldown_seconds=reply.cooldown_seconds,
            )
        if trigger and trigger.message not in grouped[reply.id].user_messages:
            grouped[reply.id].user_messages.append(trigger.message)
            if trigger.source == "generated":
                grouped[reply.id].generated_variations.append(trigger.message)
            elif trigger.source == "manual":
                grouped[reply.id].manual_triggers.append(trigger.message)
            else:
                grouped[reply.id].representative_questions.append(trigger.message)

    return list(grouped.values())


@replies.get("/{server_id}/settings", response_model=ReplySettingsModel)
async def get_reply_settings(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    settings = await get_or_create_reply_settings(session, server_id)
    return to_reply_settings_model(settings)


@replies.put(
    "/{server_id}/settings",
    response_model=ReplySettingsModel,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def set_reply_settings(
    server_id: int,
    body: ReplySettingsUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    settings = await update_reply_settings(session, server_id, body)
    await session.commit()
    invalidate_reply_matcher(server_id)
    return to_reply_settings_model(settings)


@replies.get("/{server_id}/concepts", response_model=list[ReplyConceptModel])
async def get_reply_concepts(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    return [
        to_reply_concept_model(concept)
        for concept in await list_reply_concepts(session, server_id)
    ]


@replies.post(
    "/{server_id}/concepts",
    response_model=ReplyConceptModel,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def add_reply_concept(
    server_id: int,
    body: ReplyConceptCreateModel,
    session: AsyncSession = Depends(get_session),
):
    try:
        concept = await create_reply_concept(session, server_id, body)
    except ReplyConfigurationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    invalidate_reply_matcher(server_id)
    return to_reply_concept_model(concept)


@replies.put(
    "/{server_id}/concepts/{concept_id}",
    response_model=ReplyConceptModel,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def edit_reply_concept(
    server_id: int,
    concept_id: UUID,
    body: ReplyConceptUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    try:
        concept = await update_reply_concept(session, server_id, concept_id, body)
    except ReplyConfigurationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if concept is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Concept not found")
    await session.commit()
    invalidate_reply_matcher(server_id)
    return to_reply_concept_model(concept)


@replies.delete(
    "/{server_id}/concepts/{concept_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def remove_reply_concept(
    server_id: int,
    concept_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        deleted = await delete_reply_concept(session, server_id, concept_id)
    except ReplyConceptInUseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Concept not found")
    await session.commit()
    invalidate_reply_matcher(server_id)


@replies.post(
    "/{server_id}/coverage",
    response_model=ReplyTriggerCoverageResponseModel,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def preview_trigger_coverage(
    server_id: int,
    body: ReplyTriggerCoverageRequestModel,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await preview_reply_trigger_coverage(session, server_id, body.phrases)
    except ReplyConfigurationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@replies.post(
    "/{server_id}/coverage/variations",
    response_model=ReplyTriggerVariationPreviewResponseModel,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def preview_trigger_variations(
    server_id: int,
    body: ReplyTriggerVariationPreviewRequestModel,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await preview_reply_trigger_variations(session, server_id, body.text)
    except ReplyConfigurationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@replies.post(
    "/{server_id}/suggest-variations",
    response_model=ReplyVariationSuggestionResponseModel,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def suggest_variations(
    server_id: int,
    body: ReplyVariationSuggestionRequestModel,
    session: AsyncSession = Depends(get_session),
):
    concepts = list(
        (
            await session.exec(
                select(ReplyConcept).where(ReplyConcept.server_id == server_id)
            )
        ).all()
    )
    try:
        return await suggest_reply_variations(
            bot_reply=body.bot_reply,
            representative_questions=body.representative_questions,
            concepts=concepts,
        )
    except ReplyVariationGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@replies.post(
    "/{server_id}/intents",
    response_model=ReplyMutationResponseModel,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def add_reply_intent(
    server_id: int,
    body: ReplyIntentCreateModel,
    session: AsyncSession = Depends(get_session),
):
    try:
        await create_reply_intent(session, server_id, body)
    except ReplyConfigurationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    invalidate_reply_matcher(server_id)
    return ReplyMutationResponseModel(
        processed=(
            len(body.representative_questions)
            + len(body.manual_triggers)
            + len(body.generated_variations)
        ),
        created=(
            1
            + len(body.representative_questions)
            + len(body.manual_triggers)
            + len(body.generated_variations)
        ),
    )


@replies.put(
    "/{server_id}/intents/{reply_id}",
    response_model=ReplyMutationResponseModel,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def edit_reply_intent(
    server_id: int,
    reply_id: UUID,
    body: ReplyIntentUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    try:
        reply = await update_reply_intent(session, server_id, reply_id, body)
    except ReplyConfigurationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if reply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reply not found")
    await session.commit()
    invalidate_reply_matcher(server_id)
    return ReplyMutationResponseModel(
        processed=(
            len(body.representative_questions)
            + len(body.manual_triggers)
            + len(body.generated_variations)
        ),
        updated=1,
    )


@replies.post(
    '/{server_id}/add_replies',
    response_model=ReplyMutationResponseModel,
    status_code=201,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def add_replies(
    server_id: int,
    body: List[ReplyAddModel],
    session: AsyncSession = Depends(get_session),
):
    reply_cache: dict[tuple[int, str], Replies] = {}
    created_replies = 0
    created_triggers = 0

    for reply in body:
        server_id_int = int(reply.server_id)
        if server_id_int != server_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Payload server_id must match path server_id",
            )
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
                created_replies += 1
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
            session.add(
                Triggers(
                    message=reply.user_message,
                    reply_id=existing_reply.id,
                    source=reply.source,
                )
            )
            created_triggers += 1

    await session.commit()
    invalidate_reply_matcher(server_id)
    return ReplyMutationResponseModel(
        processed=len(body),
        created=created_replies + created_triggers,
    )


@replies.post(
    '/{server_id}/delete_replies',
    response_model=ReplyMutationResponseModel,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def delete_replies(
    server_id: int,
    body: List[UUID],
    session: AsyncSession = Depends(get_session),
):
    deleted_replies = 0
    deleted_triggers = 0
    for reply_id in body:
        reply = (
            await session.exec(
                select(Replies).where(
                    Replies.id == reply_id,
                    Replies.server_id == server_id,
                )
            )
        ).first()
        if reply:
            triggers = (await session.exec(select(Triggers).where(Triggers.reply_id == reply.id))).all()
            for trigger in triggers:
                await session.delete(trigger)
                deleted_triggers += 1
            await session.delete(reply)
            deleted_replies += 1

    await session.commit()
    invalidate_reply_matcher(server_id)

    return ReplyMutationResponseModel(
        processed=len(body),
        deleted=deleted_replies + deleted_triggers,
    )


@replies.post(
    '/{server_id}/edit_replies',
    response_model=ReplyMutationResponseModel,
    dependencies=[Depends(require_server_permission("replies.manage"))],
)
async def edit_replies(
    server_id: int,
    body: List[ReplyEditModel],
    session: AsyncSession = Depends(get_session),
):
    updated_replies = 0
    created_triggers = 0
    deleted_triggers = 0
    try:
        grouped_edits = _group_reply_edits(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    for reply_id, (bot_reply, desired_messages) in grouped_edits.items():
        existing_reply = (
            await session.exec(
                select(Replies).where(
                    Replies.id == reply_id,
                    Replies.server_id == server_id,
                )
            )
        ).first()
        if existing_reply:
            if existing_reply.bot_reply != bot_reply:
                existing_reply.bot_reply = bot_reply
                session.add(existing_reply)
                updated_replies += 1

            existing_triggers = (
                await session.exec(
                    select(Triggers).where(Triggers.reply_id == existing_reply.id)
                )
            ).all()
            to_delete, to_create = _plan_trigger_sync(
                list(existing_triggers),
                desired_messages,
            )
            for trigger in to_delete:
                await session.delete(trigger)
                deleted_triggers += 1
            for message in to_create:
                session.add(Triggers(message=message, reply_id=existing_reply.id))
                created_triggers += 1

    await session.commit()
    invalidate_reply_matcher(server_id)

    return ReplyMutationResponseModel(
        processed=len(body),
        created=created_triggers,
        updated=updated_replies,
        deleted=deleted_triggers,
    )


@replies.post("/{server_id}/duplicate-selected", response_model=ReplyDuplicateResponseModel)
async def duplicate_selected_replies_to_server(
    server_id: int,
    body: ReplyDuplicateRequestModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("replies.manage")),
    target_server_id: int = Depends(require_duplicate_target_server_replies_manage),
):
    if target_server_id == server_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target_server_id must be different from source server",
        )

    result = await duplicate_selected_replies(
        session=session,
        source_server_id=server_id,
        target_server_id=target_server_id,
        reply_ids=body.reply_ids,
        actor_user_id=current_user_id,
    )
    await session.commit()
    invalidate_reply_matcher(target_server_id)
    return result

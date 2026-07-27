from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.bot_replies import (
    ReplyConceptCreateModel,
    ReplyConceptModel,
    ReplyConceptUpdateModel,
    ReplyDuplicateResponseModel,
    ReplyIntentCreateModel,
    ReplyIntentUpdateModel,
    ReplySettingsModel,
    ReplySettingsUpdateModel,
    ReplyTriggerCoverageItemModel,
    ReplyTriggerCoveragePhraseModel,
    ReplyTriggerCoverageResponseModel,
    ReplyTriggerVariationGroupModel,
    ReplyTriggerVariationPreviewResponseModel,
)
from src.db.models import GlobalUser, Replies, ReplyConcept, Server, ServerReplySettings, Triggers
from src.modules.on_message_processing.processing_methods import normalize_reply_text
from src.modules.on_message_processing.reply_matcher import (
    CONCEPT_PLACEHOLDER_RE,
    analyze_reply_trigger_coverage,
    describe_reply_trigger_variations,
)


class ReplyConfigurationConflict(ValueError):
    pass


class ReplyConceptInUseError(ValueError):
    pass


async def _ensure_server_exists(session: AsyncSession, server_id: int) -> None:
    server = await session.get(Server, server_id)
    if server:
        return
    session.add(Server(server_id=server_id, server_name=str(server_id)))
    await session.flush()


async def _ensure_global_user_exists(session: AsyncSession, user_id: int) -> None:
    user = await session.get(GlobalUser, user_id)
    if user:
        return
    session.add(GlobalUser(discord_id=user_id, username=None))
    await session.flush()


async def get_or_create_reply_settings(
    session: AsyncSession,
    server_id: int,
) -> ServerReplySettings:
    await _ensure_server_exists(session, server_id)
    settings = await session.get(ServerReplySettings, server_id)
    if settings:
        return settings
    settings = ServerReplySettings(server_id=server_id)
    session.add(settings)
    await session.flush()
    return settings


def to_reply_settings_model(settings: ServerReplySettings) -> ReplySettingsModel:
    return ReplySettingsModel(
        server_id=str(settings.server_id),
        included_channel_ids=list(settings.included_channel_ids or []),
        excluded_channel_ids=list(settings.excluded_channel_ids or []),
        excluded_role_ids=list(settings.excluded_role_ids or []),
        excluded_user_ids=list(settings.excluded_user_ids or []),
    )


async def update_reply_settings(
    session: AsyncSession,
    server_id: int,
    body: ReplySettingsUpdateModel,
) -> ServerReplySettings:
    settings = await get_or_create_reply_settings(session, server_id)
    settings.included_channel_ids = body.included_channel_ids
    settings.excluded_channel_ids = body.excluded_channel_ids
    settings.excluded_role_ids = body.excluded_role_ids
    settings.excluded_user_ids = body.excluded_user_ids
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


def to_reply_concept_model(concept: ReplyConcept) -> ReplyConceptModel:
    return ReplyConceptModel(
        id=str(concept.id),
        server_id=str(concept.server_id),
        name=concept.name,
        variants=list(concept.variants or []),
    )


async def list_reply_concepts(
    session: AsyncSession,
    server_id: int,
) -> list[ReplyConcept]:
    return list(
        (
            await session.exec(
                select(ReplyConcept)
                .where(ReplyConcept.server_id == server_id)
                .order_by(ReplyConcept.name)
            )
        ).all()
    )


async def create_reply_concept(
    session: AsyncSession,
    server_id: int,
    body: ReplyConceptCreateModel,
) -> ReplyConcept:
    await _ensure_server_exists(session, server_id)
    existing = (
        await session.exec(
            select(ReplyConcept).where(
                ReplyConcept.server_id == server_id,
                ReplyConcept.name == body.name,
            )
        )
    ).first()
    if existing:
        raise ReplyConfigurationConflict(f"Concept '{body.name}' already exists")
    concept = ReplyConcept(server_id=server_id, name=body.name, variants=body.variants)
    session.add(concept)
    await session.flush()
    return concept


async def _server_trigger_rows(
    session: AsyncSession,
    server_id: int,
) -> list[tuple[Triggers, Replies]]:
    return list(
        (
            await session.exec(
                select(Triggers, Replies)
                .join(Replies, Triggers.reply_id == Replies.id)
                .where(Replies.server_id == server_id)
            )
        ).all()
    )


async def update_reply_concept(
    session: AsyncSession,
    server_id: int,
    concept_id: UUID,
    body: ReplyConceptUpdateModel,
) -> ReplyConcept | None:
    concept = (
        await session.exec(
            select(ReplyConcept).where(
                ReplyConcept.id == concept_id,
                ReplyConcept.server_id == server_id,
            )
        )
    ).first()
    if concept is None:
        return None
    if body.name != concept.name:
        duplicate = (
            await session.exec(
                select(ReplyConcept).where(
                    ReplyConcept.server_id == server_id,
                    ReplyConcept.name == body.name,
                    ReplyConcept.id != concept_id,
                )
            )
        ).first()
        if duplicate:
            raise ReplyConfigurationConflict(f"Concept '{body.name}' already exists")
        new_placeholder = "{{" + body.name + "}}"
        for trigger, _reply in await _server_trigger_rows(session, server_id):
            rewritten = CONCEPT_PLACEHOLDER_RE.sub(
                lambda match: (
                    new_placeholder
                    if match.group(1).casefold() == concept.name
                    else match.group(0)
                ),
                trigger.message,
            )
            if rewritten != trigger.message:
                trigger.message = rewritten
                session.add(trigger)
    concept.name = body.name
    concept.variants = body.variants
    session.add(concept)
    await session.flush()
    return concept


async def delete_reply_concept(
    session: AsyncSession,
    server_id: int,
    concept_id: UUID,
) -> bool:
    concept = (
        await session.exec(
            select(ReplyConcept).where(
                ReplyConcept.id == concept_id,
                ReplyConcept.server_id == server_id,
            )
        )
    ).first()
    if concept is None:
        return False
    used_by = [
        reply.id
        for trigger, reply in await _server_trigger_rows(session, server_id)
        if any(
            match.group(1).casefold() == concept.name
            for match in CONCEPT_PLACEHOLDER_RE.finditer(trigger.message)
        )
    ]
    if used_by:
        raise ReplyConceptInUseError(
            f"Concept '{concept.name}' is used by {len(set(used_by))} automatic reply rule(s)"
        )
    await session.delete(concept)
    await session.flush()
    return True


async def preview_reply_trigger_coverage(
    session: AsyncSession,
    server_id: int,
    phrases: list[ReplyTriggerCoveragePhraseModel],
) -> ReplyTriggerCoverageResponseModel:
    concepts = await list_reply_concepts(session, server_id)
    concepts_by_name = {
        concept.name.casefold(): tuple(concept.variants or []) for concept in concepts
    }
    missing_concepts = sorted(
        {
            match.group(1).casefold()
            for phrase in phrases
            for match in CONCEPT_PLACEHOLDER_RE.finditer(phrase.text)
            if match.group(1).casefold() not in concepts_by_name
        }
    )
    if missing_concepts:
        raise ReplyConfigurationConflict(
            "Unknown concepts: " + ", ".join(missing_concepts)
        )

    coverage = analyze_reply_trigger_coverage(
        [(phrase.id, phrase.text, phrase.source) for phrase in phrases],
        concepts_by_name,
    )
    return ReplyTriggerCoverageResponseModel(
        items=[
            ReplyTriggerCoverageItemModel(
                id=item.id,
                text=item.text,
                source=item.source,
                normalized_text=item.normalized_text,
                covered_by_id=item.covered_by_id,
                reason=item.reason,
            )
            for item in coverage
        ]
    )


async def preview_reply_trigger_variations(
    session: AsyncSession,
    server_id: int,
    trigger_text: str,
) -> ReplyTriggerVariationPreviewResponseModel:
    concepts = await list_reply_concepts(session, server_id)
    concepts_by_name = {
        concept.name.casefold(): tuple(concept.variants or []) for concept in concepts
    }
    missing_concepts = sorted(
        {
            match.group(1).casefold()
            for match in CONCEPT_PLACEHOLDER_RE.finditer(trigger_text)
            if match.group(1).casefold() not in concepts_by_name
        }
    )
    if missing_concepts:
        raise ReplyConfigurationConflict(
            "Unknown concepts: " + ", ".join(missing_concepts)
        )
    groups = describe_reply_trigger_variations(
        trigger_text,
        concepts_by_name,
    )
    return ReplyTriggerVariationPreviewResponseModel(
        groups=[
            ReplyTriggerVariationGroupModel(
                label=group.label,
                kind=group.kind,
                variants=list(group.variants),
            )
            for group in groups
        ],
    )


async def _prepare_intent_triggers(
    session: AsyncSession,
    server_id: int,
    representative_questions: list[str],
    manual_triggers: list[str],
    generated_variations: list[str],
    *,
    exclude_reply_id: UUID | None = None,
) -> tuple[list[str], list[str], list[str]]:
    phrases = [
        *[
            ReplyTriggerCoveragePhraseModel(
                id=f"representative:{index}", text=text, source="representative"
            )
            for index, text in enumerate(representative_questions)
        ],
        *[
            ReplyTriggerCoveragePhraseModel(
                id=f"manual:{index}", text=text, source="manual"
            )
            for index, text in enumerate(manual_triggers)
        ],
        *[
            ReplyTriggerCoveragePhraseModel(
                id=f"generated:{index}", text=text, source="generated"
            )
            for index, text in enumerate(generated_variations)
        ],
    ]
    coverage = await preview_reply_trigger_coverage(session, server_id, phrases)
    covered_ids = {item.id for item in coverage.items if item.covered_by_id is not None}
    covered_representative = [
        item.text
        for item in coverage.items
        if item.source == "representative" and item.covered_by_id is not None
    ]
    if covered_representative:
        raise ReplyConfigurationConflict(
            "Representative questions must be distinct after language matching: "
            + ", ".join(covered_representative[:5])
        )

    prepared_representative = list(representative_questions)
    prepared_manual = [
        text for index, text in enumerate(manual_triggers) if f"manual:{index}" not in covered_ids
    ]
    prepared_generated = [
        text
        for index, text in enumerate(generated_variations)
        if f"generated:{index}" not in covered_ids
    ]
    all_phrases = prepared_representative + prepared_manual + prepared_generated

    desired_keys = {normalize_reply_text(phrase) for phrase in all_phrases}
    collisions: list[str] = []
    for trigger, reply in await _server_trigger_rows(session, server_id):
        if exclude_reply_id is not None and reply.id == exclude_reply_id:
            continue
        if normalize_reply_text(trigger.message) in desired_keys:
            collisions.append(trigger.message)
    if collisions:
        raise ReplyConfigurationConflict(
            "These triggers are already used by another reply: " + ", ".join(collisions[:5])
        )
    return prepared_representative, prepared_manual, prepared_generated


async def create_reply_intent(
    session: AsyncSession,
    server_id: int,
    body: ReplyIntentCreateModel,
) -> Replies:
    await _ensure_server_exists(session, server_id)
    await _ensure_global_user_exists(session, int(body.admin_id))
    representative, manual, generated = await _prepare_intent_triggers(
        session,
        server_id,
        body.representative_questions,
        body.manual_triggers,
        body.generated_variations,
    )
    reply = Replies(
        server_id=server_id,
        bot_reply=body.bot_reply,
        created_by_id=int(body.admin_id),
    )
    session.add(reply)
    await session.flush()
    for message in representative:
        session.add(Triggers(message=message, reply_id=reply.id, source="representative"))
    for message in manual:
        session.add(Triggers(message=message, reply_id=reply.id, source="manual"))
    for message in generated:
        session.add(Triggers(message=message, reply_id=reply.id, source="generated"))
    await session.flush()
    return reply


async def update_reply_intent(
    session: AsyncSession,
    server_id: int,
    reply_id: UUID,
    body: ReplyIntentUpdateModel,
) -> Replies | None:
    reply = (
        await session.exec(
            select(Replies).where(Replies.id == reply_id, Replies.server_id == server_id)
        )
    ).first()
    if reply is None:
        return None
    representative, manual, generated = await _prepare_intent_triggers(
        session,
        server_id,
        body.representative_questions,
        body.manual_triggers,
        body.generated_variations,
        exclude_reply_id=reply_id,
    )
    existing = list(
        (await session.exec(select(Triggers).where(Triggers.reply_id == reply_id))).all()
    )
    desired = {
        **{message: "representative" for message in representative},
        **{message: "manual" for message in manual},
        **{message: "generated" for message in generated},
    }
    existing_by_message = {trigger.message: trigger for trigger in existing}
    for trigger in existing:
        source = desired.get(trigger.message)
        if source is None:
            await session.delete(trigger)
        elif trigger.source != source:
            trigger.source = source
            session.add(trigger)
    for message, source in desired.items():
        if message not in existing_by_message:
            session.add(Triggers(message=message, reply_id=reply_id, source=source))
    reply.bot_reply = body.bot_reply
    session.add(reply)
    await session.flush()
    return reply


async def duplicate_selected_replies(
    session: AsyncSession,
    source_server_id: int,
    target_server_id: int,
    reply_ids: list[UUID],
    actor_user_id: int,
) -> ReplyDuplicateResponseModel:
    unique_ids = list(dict.fromkeys(reply_ids))
    requested_replies = len(unique_ids)

    source_replies = (
        await session.exec(
            select(Replies).where(
                Replies.server_id == source_server_id,
                Replies.id.in_(unique_ids),
            )
        )
    ).all()

    source_reply_ids = {item.id for item in source_replies}
    missing_reply_ids = [str(item_id) for item_id in unique_ids if item_id not in source_reply_ids]

    if not source_replies:
        return ReplyDuplicateResponseModel(
            source_server_id=str(source_server_id),
            target_server_id=str(target_server_id),
            requested_replies=requested_replies,
            duplicated_replies=0,
            reused_replies=0,
            duplicated_triggers=0,
            skipped_triggers=0,
            missing_reply_ids=missing_reply_ids,
        )

    await _ensure_server_exists(session, target_server_id)
    await _ensure_global_user_exists(session, actor_user_id)

    source_trigger_rows = (
        await session.exec(
            select(Triggers).where(Triggers.reply_id.in_(list(source_reply_ids)))
        )
    ).all()
    triggers_by_source_reply: dict[UUID, list[tuple[str, str]]] = {}
    for trigger in source_trigger_rows:
        triggers_by_source_reply.setdefault(trigger.reply_id, []).append(
            (trigger.message, trigger.source or "representative")
        )

    referenced_concept_names = {
        match.group(1).casefold()
        for trigger in source_trigger_rows
        for match in CONCEPT_PLACEHOLDER_RE.finditer(trigger.message)
    }
    if referenced_concept_names:
        source_concepts = list(
            (
                await session.exec(
                    select(ReplyConcept).where(
                        ReplyConcept.server_id == source_server_id,
                        ReplyConcept.name.in_(list(referenced_concept_names)),
                    )
                )
            ).all()
        )
        target_concepts = list(
            (
                await session.exec(
                    select(ReplyConcept).where(
                        ReplyConcept.server_id == target_server_id,
                        ReplyConcept.name.in_(list(referenced_concept_names)),
                    )
                )
            ).all()
        )
        target_concepts_by_name = {concept.name: concept for concept in target_concepts}
        for source_concept in source_concepts:
            target_concept = target_concepts_by_name.get(source_concept.name)
            if target_concept is None:
                session.add(
                    ReplyConcept(
                        server_id=target_server_id,
                        name=source_concept.name,
                        variants=list(source_concept.variants or []),
                    )
                )
                continue
            merged_variants = list(
                dict.fromkeys((target_concept.variants or []) + (source_concept.variants or []))
            )
            if merged_variants != list(target_concept.variants or []):
                target_concept.variants = merged_variants
                session.add(target_concept)

    bot_replies = list({reply.bot_reply for reply in source_replies})
    existing_target_replies = (
        await session.exec(
            select(Replies).where(
                Replies.server_id == target_server_id,
                Replies.bot_reply.in_(bot_replies),
            )
        )
    ).all()
    target_reply_by_text = {reply.bot_reply: reply for reply in existing_target_replies}

    duplicated_replies = 0
    reused_replies = 0
    target_reply_ids: set[UUID] = {reply.id for reply in existing_target_replies}

    for source_reply in source_replies:
        existing_target = target_reply_by_text.get(source_reply.bot_reply)
        if existing_target:
            reused_replies += 1
            continue

        created_target = Replies(
            server_id=target_server_id,
            bot_reply=source_reply.bot_reply,
            created_by_id=actor_user_id,
        )
        session.add(created_target)
        await session.flush()
        target_reply_by_text[source_reply.bot_reply] = created_target
        target_reply_ids.add(created_target.id)
        duplicated_replies += 1

    existing_trigger_pairs: set[tuple[UUID, str]] = set()
    if target_reply_ids:
        existing_target_triggers = (
            await session.exec(
                select(Triggers).where(Triggers.reply_id.in_(list(target_reply_ids)))
            )
        ).all()
        existing_trigger_pairs = {(item.reply_id, item.message) for item in existing_target_triggers}

    duplicated_triggers = 0
    skipped_triggers = 0
    for source_reply in source_replies:
        target_reply = target_reply_by_text[source_reply.bot_reply]
        for trigger_text, trigger_source in triggers_by_source_reply.get(source_reply.id, []):
            key = (target_reply.id, trigger_text)
            if key in existing_trigger_pairs:
                skipped_triggers += 1
                continue
            session.add(
                Triggers(
                    message=trigger_text,
                    reply_id=target_reply.id,
                    source=trigger_source,
                )
            )
            existing_trigger_pairs.add(key)
            duplicated_triggers += 1

    await session.flush()
    return ReplyDuplicateResponseModel(
        source_server_id=str(source_server_id),
        target_server_id=str(target_server_id),
        requested_replies=requested_replies,
        duplicated_replies=duplicated_replies,
        reused_replies=reused_replies,
        duplicated_triggers=duplicated_triggers,
        skipped_triggers=skipped_triggers,
        missing_reply_ids=missing_reply_ids,
    )

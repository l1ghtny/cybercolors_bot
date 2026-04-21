from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_optional_current_discord_user_id, resolve_actor_user_id
from api.models.moderation_rules import (
    ModerationRuleBulkUpsertResponseModel,
    ModerationRuleCreateModel,
    ModerationRuleImportMessageModel,
    ModerationRuleImportTextModel,
    ModerationRuleParsePreviewModel,
    ModerationRuleReadModel,
    ParsedModerationRuleModel,
)
from api.services.moderation_rules_service import (
    create_manual_rule,
    deactivate_rule,
    import_rules,
    import_rules_from_message,
    list_rules,
    parse_rules_from_text,
    to_parsed_rule_model,
    to_rule_read_model,
)
from src.db.database import get_session

moderation_rules_router = APIRouter(prefix="/rules")


@moderation_rules_router.get("/{server_id}", response_model=list[ModerationRuleReadModel])
async def get_server_moderation_rules(
    server_id: int,
    include_inactive: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
):
    rules = await list_rules(session=session, server_id=server_id, include_inactive=include_inactive)
    return [to_rule_read_model(item) for item in rules]


@moderation_rules_router.post(
    "/{server_id}",
    response_model=ModerationRuleReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def add_server_moderation_rule(
    server_id: int,
    body: ModerationRuleCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    created_by_user_id = resolve_actor_user_id(body.created_by_user_id, current_user_id)
    rule = await create_manual_rule(
        session=session,
        server_id=server_id,
        title=body.title,
        description=body.description,
        code=body.code,
        sort_order=body.sort_order,
        created_by_user_id=created_by_user_id,
    )
    return to_rule_read_model(rule)


@moderation_rules_router.post("/{server_id}/parse", response_model=list[ParsedModerationRuleModel])
async def parse_server_moderation_rules(
    server_id: int,
    body: ModerationRuleParsePreviewModel,
):
    parsed = parse_rules_from_text(body.text)
    return [to_parsed_rule_model(item) for item in parsed]


@moderation_rules_router.post(
    "/{server_id}/import-text",
    response_model=ModerationRuleBulkUpsertResponseModel,
    status_code=status.HTTP_201_CREATED,
)
async def import_server_moderation_rules_from_text(
    server_id: int,
    body: ModerationRuleImportTextModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    created_by_user_id = resolve_actor_user_id(body.created_by_user_id, current_user_id)
    parsed = parse_rules_from_text(body.text)
    imported = await import_rules(
        session=session,
        server_id=server_id,
        parsed_rules=parsed,
        created_by_user_id=created_by_user_id,
        replace_existing=body.replace_existing,
    )
    return ModerationRuleBulkUpsertResponseModel(imported=[to_rule_read_model(item) for item in imported])


@moderation_rules_router.post(
    "/{server_id}/import-message",
    response_model=ModerationRuleBulkUpsertResponseModel,
    status_code=status.HTTP_201_CREATED,
)
async def import_server_moderation_rules_from_message(
    server_id: int,
    body: ModerationRuleImportMessageModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    created_by_user_id = resolve_actor_user_id(body.created_by_user_id, current_user_id)
    imported = await import_rules_from_message(
        session=session,
        server_id=server_id,
        channel_id=int(body.channel_id),
        message_id=int(body.message_id),
        created_by_user_id=created_by_user_id,
        replace_existing=body.replace_existing,
    )
    return ModerationRuleBulkUpsertResponseModel(imported=[to_rule_read_model(item) for item in imported])


@moderation_rules_router.delete("/{server_id}/{rule_id}", response_model=ModerationRuleReadModel)
async def disable_server_moderation_rule(
    server_id: int,
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    disabled = await deactivate_rule(session=session, server_id=server_id, rule_id=rule_id)
    return to_rule_read_model(disabled)

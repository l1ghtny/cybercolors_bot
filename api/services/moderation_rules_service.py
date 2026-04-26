import re
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_rules import (
    ModerationRuleMessageRefModel,
    ModerationRuleParseGuideModel,
    ModerationRuleReadModel,
    ParsedModerationRuleModel,
)
from api.services.discord_guilds import fetch_channel_message
from api.services.moderation_core import naive_utcnow
from src.db.models import ModerationRule, Server

RULE_START_RE = re.compile(r"^\s*(?P<num>[1-9]\d?)(?P<marker>\s*[\W_]{0,4})\s*(?P<body>.+)$")


@dataclass
class ParsedRule:
    marker: str | None
    code: str | None
    title: str
    description: str | None
    sort_order: int


def _normalize_text(value: str) -> str:
    cleaned = value.replace("ᅠ", " ")
    cleaned = re.sub(r"<:[^:>]+:\d+>", " ", cleaned)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"^\*+|\*+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _extract_title(description: str) -> str:
    if not description:
        return "Rule"
    for piece in description.split("."):
        title = piece.strip()
        if title:
            return title[:500]
    return description[:500]


def parse_rules_from_text(text: str) -> list[ParsedRule]:
    lines = [line.rstrip() for line in text.splitlines()]
    parsed: list[ParsedRule] = []
    current_marker: str | None = None
    current_code: str | None = None
    current_lines: list[str] = []

    def flush_current():
        nonlocal current_marker, current_code, current_lines
        if not current_lines:
            return
        merged = "\n".join(line for line in current_lines if line.strip())
        normalized_description = _normalize_text(merged)
        if not normalized_description:
            return
        parsed.append(
            ParsedRule(
                marker=current_marker,
                code=current_code,
                title=_extract_title(normalized_description),
                description=normalized_description,
                sort_order=len(parsed) + 1,
            )
        )

    for line in lines:
        match = RULE_START_RE.match(line)
        if match:
            marker_suffix = (match.group("marker") or "").strip()
            body = match.group("body").strip()
            # Prevent false positives like "2024 roadmap" and treat only explicit markers as rule starts.
            if not marker_suffix and not body.startswith("**"):
                match = None

        if match:
            flush_current()
            marker = f"{match.group('num')}{(match.group('marker') or '').strip()}"
            current_marker = marker
            current_code = match.group("num")
            current_lines = [body]
            continue

        if current_lines:
            current_lines.append(line)

    flush_current()
    return parsed


async def _get_or_create_server(session: AsyncSession, server_id: int) -> Server:
    server = await session.get(Server, server_id)
    if server:
        return server
    server = Server(server_id=server_id, server_name=str(server_id))
    session.add(server)
    await session.flush()
    return server


def to_rule_read_model(rule: ModerationRule) -> ModerationRuleReadModel:
    return ModerationRuleReadModel(
        id=str(rule.id),
        server_id=str(rule.server_id),
        code=rule.code,
        title=rule.title,
        description=rule.description,
        sort_order=rule.sort_order,
        source_channel_id=str(rule.source_channel_id) if rule.source_channel_id is not None else None,
        source_message_id=str(rule.source_message_id) if rule.source_message_id is not None else None,
        source_marker=rule.source_marker,
        is_active=rule.is_active,
        created_by_user_id=str(rule.created_by_user_id) if rule.created_by_user_id is not None else None,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def to_parsed_rule_model(parsed: ParsedRule) -> ParsedModerationRuleModel:
    return ParsedModerationRuleModel(
        marker=parsed.marker,
        code=parsed.code,
        title=parsed.title,
        description=parsed.description,
        sort_order=parsed.sort_order,
    )


async def list_rules(
    session: AsyncSession,
    server_id: int,
    include_inactive: bool = False,
) -> list[ModerationRule]:
    statement = select(ModerationRule).where(ModerationRule.server_id == server_id)
    if not include_inactive:
        statement = statement.where(ModerationRule.is_active == True)
    statement = statement.order_by(ModerationRule.sort_order.asc(), ModerationRule.created_at.asc())
    return (await session.exec(statement)).all()


async def create_manual_rule(
    session: AsyncSession,
    server_id: int,
    title: str,
    description: str | None,
    code: str | None,
    sort_order: int,
    created_by_user_id: int | None,
) -> ModerationRule:
    await _get_or_create_server(session, server_id)
    now = naive_utcnow()
    rule = ModerationRule(
        server_id=server_id,
        code=code,
        title=title,
        description=description,
        sort_order=sort_order,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
        is_active=True,
    )
    session.add(rule)
    await session.flush()
    await session.refresh(rule)
    return rule


async def deactivate_rule(
    session: AsyncSession,
    server_id: int,
    rule_id: UUID,
) -> ModerationRule:
    rule = await session.get(ModerationRule, rule_id)
    if not rule or rule.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation rule not found")
    rule.is_active = False
    rule.updated_at = naive_utcnow()
    session.add(rule)
    await session.flush()
    await session.refresh(rule)
    return rule


async def _deactivate_existing_rules(session: AsyncSession, server_id: int):
    existing_rules = await list_rules(session=session, server_id=server_id, include_inactive=False)
    now = naive_utcnow()
    for rule in existing_rules:
        rule.is_active = False
        rule.updated_at = now
        session.add(rule)


async def _active_rules_max_sort_order(session: AsyncSession, server_id: int) -> int:
    max_sort_order = (
        await session.exec(
            select(func.max(ModerationRule.sort_order)).where(
                ModerationRule.server_id == server_id,
                ModerationRule.is_active == True,
            )
        )
    ).one()
    return int(max_sort_order or 0)


async def import_rules(
    session: AsyncSession,
    server_id: int,
    parsed_rules: Iterable[ParsedRule],
    created_by_user_id: int | None,
    replace_existing: bool,
    source_channel_id: int | None = None,
    source_message_id: int | None = None,
) -> list[ModerationRule]:
    parsed_rules = list(parsed_rules)
    if not parsed_rules:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No parseable rules found in provided text",
        )

    await _get_or_create_server(session, server_id)
    if replace_existing:
        await _deactivate_existing_rules(session, server_id)
        sort_offset = 0
    else:
        sort_offset = await _active_rules_max_sort_order(session=session, server_id=server_id)

    now = naive_utcnow()
    created: list[ModerationRule] = []
    for item in parsed_rules:
        rule = ModerationRule(
            server_id=server_id,
            code=item.code,
            title=item.title,
            description=item.description,
            sort_order=sort_offset + item.sort_order,
            source_channel_id=source_channel_id,
            source_message_id=source_message_id,
            source_marker=item.marker,
            is_active=True,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(rule)
        created.append(rule)

    await session.flush()
    for item in created:
        await session.refresh(item)
    return created


async def import_rules_from_messages(
    session: AsyncSession,
    server_id: int,
    message_refs: list[ModerationRuleMessageRefModel],
    created_by_user_id: int | None,
    replace_existing: bool,
) -> list[ModerationRule]:
    if not message_refs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="messages cannot be empty",
        )

    parsed_chunks: list[tuple[ParsedRule, int, int]] = []
    for ref in message_refs:
        channel_id = int(ref.channel_id)
        message_id = int(ref.message_id)
        message = await fetch_channel_message(channel_id=channel_id, message_id=message_id)
        message_guild_id = message.get("guild_id")
        if message_guild_id is not None and str(message_guild_id).isdigit() and int(message_guild_id) != server_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Message {message_id} does not belong to target server",
            )

        for parsed in parse_rules_from_text(message.get("content", "")):
            parsed_chunks.append((parsed, channel_id, message_id))

    if not parsed_chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No parseable rules found in provided messages",
        )

    await _get_or_create_server(session, server_id)
    if replace_existing:
        await _deactivate_existing_rules(session, server_id)
        sort_offset = 0
    else:
        sort_offset = await _active_rules_max_sort_order(session=session, server_id=server_id)

    now = naive_utcnow()
    created: list[ModerationRule] = []
    for index, (parsed, channel_id, message_id) in enumerate(parsed_chunks, start=1):
        rule = ModerationRule(
            server_id=server_id,
            code=parsed.code,
            title=parsed.title,
            description=parsed.description,
            sort_order=sort_offset + index,
            source_channel_id=channel_id,
            source_message_id=message_id,
            source_marker=parsed.marker,
            is_active=True,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(rule)
        created.append(rule)

    await session.flush()
    for item in created:
        await session.refresh(item)
    return created


async def import_rules_from_message(
    session: AsyncSession,
    server_id: int,
    channel_id: int,
    message_id: int,
    created_by_user_id: int | None,
    replace_existing: bool,
) -> list[ModerationRule]:
    message = await fetch_channel_message(channel_id=channel_id, message_id=message_id)
    message_guild_id = message.get("guild_id")
    if message_guild_id is not None and str(message_guild_id).isdigit():
        if int(message_guild_id) != server_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provided message does not belong to target server",
            )
    content = message.get("content", "")
    parsed_rules = parse_rules_from_text(content)
    return await import_rules(
        session=session,
        server_id=server_id,
        parsed_rules=parsed_rules,
        created_by_user_id=created_by_user_id,
        replace_existing=replace_existing,
        source_channel_id=channel_id,
        source_message_id=message_id,
    )


def _get_rule_parse_guide_legacy() -> ModerationRuleParseGuideModel:
    return ModerationRuleParseGuideModel(
        title="Moderation Rule Formatting Guide",
        guidance=[
            "Put one rule per numbered item starting with a number marker such as `1.` or `1️⃣`.",
            "Keep the rule's first sentence concise; it becomes the short rule title.",
            "Keep any details in the following lines right below the same numbered item.",
            "Avoid mixing unrelated paragraphs between numbered rules.",
            "If importing multiple messages, keep each message using the same numbering style.",
        ],
        example=(
            "1. Harassment and insults are prohibited.\n"
            "Includes threats, bullying, discrimination, and repeated personal attacks.\n\n"
            "2. 18+ sexual content is prohibited.\n"
            "Nudity, pornography, and shock sexual content are not allowed."
        ),
    )


def get_rule_parse_guide(locale: str | None = None) -> ModerationRuleParseGuideModel:
    normalized = (locale or "en").strip().lower()
    if normalized == "ru":
        return ModerationRuleParseGuideModel(
            title="Гайд по формату правил модерации",
            guidance=[
                "Каждое правило оформляйте отдельным нумерованным пунктом, например `1.` или `1️⃣`.",
                "Первое предложение делайте кратким: оно станет коротким названием правила.",
                "Детали пишите следующими строками сразу под тем же пунктом.",
                "Не вставляйте между пунктами несвязанные абзацы.",
                "При импорте из нескольких сообщений придерживайтесь одного стиля нумерации.",
            ],
            example=(
                "1. Запрещены травля и оскорбления.\n"
                "Сюда относятся угрозы, дискриминация и повторяющиеся личные нападки.\n\n"
                "2. Запрещён сексуальный 18+ контент.\n"
                "Нагота, порнография и шокирующий контент не допускаются."
            ),
        )
    return ModerationRuleParseGuideModel(
        title="Moderation Rule Formatting Guide",
        guidance=[
            "Put one rule per numbered item starting with a number marker such as `1.` or `1️⃣`.",
            "Keep the rule's first sentence concise; it becomes the short rule title.",
            "Keep any details in the following lines right below the same numbered item.",
            "Avoid mixing unrelated paragraphs between numbered rules.",
            "If importing multiple messages, keep each message using the same numbering style.",
        ],
        example=(
            "1. Harassment and insults are prohibited.\n"
            "Includes threats, bullying, discrimination, and repeated personal attacks.\n\n"
            "2. 18+ sexual content is prohibited.\n"
            "Nudity, pornography, and shock sexual content are not allowed."
        ),
    )

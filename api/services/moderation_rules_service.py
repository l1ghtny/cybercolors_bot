import re
import hashlib
from datetime import datetime
from time import monotonic
from typing import Iterable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import desc, func, union_all
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_rules import (
    ModerationRuleUsageModel,
    ModerationRuleMessageRefModel,
    ModerationRuleParseGuideModel,
    ModerationRuleReadModel,
    RuleUsageActionSummaryModel,
    RuleUsageCaseSummaryModel,
    RuleUsageCitationModel,
    RuleUsageTopOffenderModel,
    ParsedModerationRuleModel,
)
from api.services.discord_guilds import fetch_channel_message
from api.services.moderation_core import build_actor, naive_utcnow
from api.services.moderation_rule_llm_parser import parse_rules_from_text_with_llm
from api.services.moderation_rule_sync_state import ModerationRuleSyncState, ModerationRuleSyncStatus
from api.services.moderation_rules_service_types import ParsedRule
from src.db.models import (
    ModerationAction,
    ModerationActionRuleCitation,
    ModerationCase,
    ModerationCaseRuleCitation,
    ModerationRule,
    Server,
)

RULE_START_RE = re.compile(r"^\s*(?P<num>[1-9]\d?)(?P<marker>\s*[\W_]{0,4})\s*(?P<body>.+)$")
CUSTOM_EMOJI_RE = re.compile(r"<a?:[^:>]+:\d+>")
CUSTOM_EMOJI_RULE_START_RE = re.compile(
    r"^\s*(?P<marker><a?:[^:>]*?(?P<num>[1-9]\d?|ten)[^:>]*?:\d+>)\s*(?P<body>.+)$",
    re.IGNORECASE,
)
KEYCAP_RULE_START_RE = re.compile(r"^\s*(?P<marker>[1-9]\ufe0f?\u20e3|🔟)\s*(?P<body>.+)$")
INLINE_RULE_BOUNDARY_RE = re.compile(
    r"(?<!^)(?=\s*(?:\*\*)?\s*(?:[1-9]\d?\s*[\).:-]|[1-9]\ufe0f?\u20e3|🔟|<a?:[^:>]*?(?:[1-9]\d?|ten)[^:>]*?:\d+>))",
    re.IGNORECASE,
)
RULE_USAGE_CACHE_TTL_SECONDS = 60
_rule_usage_cache: dict[tuple[int, UUID], tuple[float, ModerationRuleUsageModel]] = {}


def _normalize_text(value: str) -> str:
    cleaned = value.replace("ᅠ", " ")
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"^\*+|\*+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _normalize_rule_boundaries(text: str) -> str:
    emoji_tokens: list[str] = []

    def store_emoji(match: re.Match[str]) -> str:
        emoji_tokens.append(match.group(0))
        return f"@@DISCORD_EMOJI_{len(emoji_tokens) - 1}@@"

    protected = CUSTOM_EMOJI_RE.sub(store_emoji, text)
    normalized = INLINE_RULE_BOUNDARY_RE.sub("\n", protected)
    for index, emoji in enumerate(emoji_tokens):
        normalized = normalized.replace(f"@@DISCORD_EMOJI_{index}@@", emoji)
    return normalized


def _keycap_code(marker: str) -> str | None:
    normalized = marker.replace("\ufe0f", "")
    if normalized == "🔟":
        return "10"
    if normalized.endswith("\u20e3") and normalized[0].isdigit():
        return normalized[0]
    return None


def _custom_emoji_code(match: re.Match[str]) -> str:
    raw = match.group("num").lower()
    return "10" if raw == "ten" else raw


def _extract_title(description: str) -> str:
    if not description:
        return "Rule"
    for piece in description.split("."):
        title = piece.strip()
        if title:
            return title[:500]
    return description[:500]


def parse_rules_from_text(text: str) -> list[ParsedRule]:
    lines = [line.rstrip() for line in _normalize_rule_boundaries(text).splitlines()]
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
        title_source = _normalize_text(next((line for line in current_lines if line.strip()), merged))
        if not normalized_description:
            return
        parsed.append(
            ParsedRule(
                marker=current_marker,
                code=current_code,
                title=_extract_title(title_source or normalized_description),
                description=normalized_description,
                sort_order=len(parsed) + 1,
            )
        )

    for line in lines:
        custom_emoji_match = CUSTOM_EMOJI_RULE_START_RE.match(line)
        if custom_emoji_match:
            flush_current()
            current_marker = custom_emoji_match.group("marker")
            current_code = _custom_emoji_code(custom_emoji_match)
            current_lines = [custom_emoji_match.group("body").strip()]
            continue

        keycap_match = KEYCAP_RULE_START_RE.match(line)
        if keycap_match:
            flush_current()
            current_marker = keycap_match.group("marker")
            current_code = _keycap_code(current_marker)
            current_lines = [keycap_match.group("body").strip()]
            continue

        match = RULE_START_RE.match(line)
        if match:
            marker_suffix = (match.group("marker") or "").strip()
            body = match.group("body").strip()
            if marker_suffix.endswith("**") and not body.startswith("**"):
                marker_suffix = marker_suffix[:-2].strip()
                body = f"**{body}"
            # Prevent false positives like "2024 roadmap" and treat only explicit markers as rule starts.
            if not marker_suffix and not body.startswith("**"):
                match = None

        if match:
            flush_current()
            marker = f"{match.group('num')}{marker_suffix}"
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


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _segment_hash(rule: ParsedRule) -> str:
    payload = {
        "marker": rule.marker,
        "code": rule.code,
        "title": rule.title,
        "description": rule.description,
    }
    return _content_hash(str(payload))


async def _get_rule_sync_states(
    session: AsyncSession,
    rule_ids: Iterable[UUID],
) -> dict[UUID, ModerationRuleSyncState]:
    ids = list(rule_ids)
    if not ids:
        return {}
    states = (
        await session.exec(
            select(ModerationRuleSyncState).where(ModerationRuleSyncState.rule_id.in_(ids))
        )
    ).all()
    return {state.rule_id: state for state in states}


async def _upsert_rule_sync_state(
    session: AsyncSession,
    rule_id: UUID,
    *,
    sync_status: ModerationRuleSyncStatus,
    source_content_hash: str | None = None,
    source_segment_hash: str | None = None,
    sync_note: str | None = None,
    now: datetime | None = None,
) -> ModerationRuleSyncState:
    timestamp = now or naive_utcnow()
    state = await session.get(ModerationRuleSyncState, rule_id)
    if state is None:
        state = ModerationRuleSyncState(rule_id=rule_id, created_at=timestamp)
    state.sync_status = sync_status.value
    state.source_content_hash = source_content_hash
    state.source_segment_hash = source_segment_hash
    state.sync_note = sync_note
    state.updated_at = timestamp
    session.add(state)
    return state


async def get_rule_sync_states_for_rules(
    session: AsyncSession,
    rules: Iterable[ModerationRule],
) -> dict[UUID, ModerationRuleSyncState]:
    return await _get_rule_sync_states(session, [rule.id for rule in rules if rule.id is not None])


async def parse_rules_for_import(text: str) -> list[ParsedRule]:
    fallback_rules = parse_rules_from_text(text)
    return await parse_rules_from_text_with_llm(text, fallback_rules=fallback_rules)


def to_rule_read_model(
    rule: ModerationRule,
    usage_count: int | None = None,
    last_cited_at: datetime | None = None,
    sync_state: ModerationRuleSyncState | None = None,
) -> ModerationRuleReadModel:
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
        usage_count=usage_count,
        last_cited_at=last_cited_at,
        sync_status=sync_state.sync_status if sync_state is not None else None,
        sync_note=sync_state.sync_note if sync_state is not None else None,
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


async def get_rule_usage_stats_for_server(
    session: AsyncSession,
    server_id: int,
) -> dict[UUID, tuple[int, datetime | None]]:
    usage_union = union_all(
        select(
            ModerationActionRuleCitation.rule_id.label("rule_id"),
            ModerationActionRuleCitation.cited_at.label("cited_at"),
        ).where(
            ModerationActionRuleCitation.server_id == server_id,
            ModerationActionRuleCitation.rule_id.is_not(None),
        ),
        select(
            ModerationCaseRuleCitation.rule_id.label("rule_id"),
            ModerationCaseRuleCitation.cited_at.label("cited_at"),
        ).where(
            ModerationCaseRuleCitation.server_id == server_id,
            ModerationCaseRuleCitation.rule_id.is_not(None),
        ),
    ).subquery()

    rows = (
        await session.exec(
            select(
                usage_union.c.rule_id,
                func.count().label("usage_count"),
                func.max(usage_union.c.cited_at).label("last_cited_at"),
            ).group_by(usage_union.c.rule_id)
        )
    ).all()
    return {row[0]: (int(row[1] or 0), row[2]) for row in rows if row[0] is not None}


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
    if rule.id is not None:
        await _upsert_rule_sync_state(
            session,
            rule.id,
            sync_status=ModerationRuleSyncStatus.MANUAL,
            sync_note="Created manually in the dashboard.",
            now=now,
        )
    _invalidate_rule_usage_cache(server_id=server_id)
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
    _invalidate_rule_usage_cache(server_id=server_id, rule_ids=[rule_id])
    return rule


async def activate_rule(
    session: AsyncSession,
    server_id: int,
    rule_id: UUID,
) -> ModerationRule:
    rule = await session.get(ModerationRule, rule_id)
    if not rule or rule.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation rule not found")
    rule.is_active = True
    rule.updated_at = naive_utcnow()
    session.add(rule)
    await session.flush()
    await session.refresh(rule)
    _invalidate_rule_usage_cache(server_id=server_id, rule_ids=[rule_id])
    return rule


async def update_rule_manually(
    session: AsyncSession,
    server_id: int,
    rule_id: UUID,
    title: str,
    description: str | None,
    code: str | None,
    sort_order: int,
    is_active: bool | None,
) -> ModerationRule:
    rule = await session.get(ModerationRule, rule_id)
    if not rule or rule.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation rule not found")
    rule.title = title
    rule.description = description
    rule.code = code
    rule.sort_order = sort_order
    if is_active is not None:
        rule.is_active = is_active
    now = naive_utcnow()
    rule.updated_at = now
    session.add(rule)
    if rule.id is not None:
        await _upsert_rule_sync_state(
            session,
            rule.id,
            sync_status=ModerationRuleSyncStatus.MANUAL,
            sync_note="Edited manually in the dashboard; source-message sync will preserve this rule.",
            now=now,
        )
    await session.flush()
    await session.refresh(rule)
    _invalidate_rule_usage_cache(server_id=server_id, rule_ids=[rule_id])
    return rule


async def delete_rule_permanently(
    session: AsyncSession,
    server_id: int,
    rule_id: UUID,
) -> None:
    rule = await session.get(ModerationRule, rule_id)
    if not rule or rule.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation rule not found")

    deleted_at = naive_utcnow()
    sync_state = await session.get(ModerationRuleSyncState, rule_id)
    if sync_state is not None:
        await session.delete(sync_state)

    action_citations = (
        await session.exec(
            select(ModerationActionRuleCitation).where(
                ModerationActionRuleCitation.server_id == server_id,
                ModerationActionRuleCitation.rule_id == rule_id,
            )
        )
    ).all()
    for citation in action_citations:
        citation.rule_id = None
        citation.rule_deleted_at = deleted_at
        session.add(citation)

    case_citations = (
        await session.exec(
            select(ModerationCaseRuleCitation).where(
                ModerationCaseRuleCitation.server_id == server_id,
                ModerationCaseRuleCitation.rule_id == rule_id,
            )
        )
    ).all()
    for citation in case_citations:
        citation.rule_id = None
        citation.rule_deleted_at = deleted_at
        session.add(citation)

    linked_actions = (
        await session.exec(
            select(ModerationAction).where(
                ModerationAction.server_id == server_id,
                ModerationAction.rule_id == rule_id,
            )
        )
    ).all()
    for action in linked_actions:
        action.rule_id = None
        session.add(action)

    await session.delete(rule)
    await session.flush()
    _invalidate_rule_usage_cache(server_id=server_id, rule_ids=[rule_id])


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
    source_content: str | None = None,
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
    content_hash = _content_hash(source_content or "\n".join((item.description or item.title) for item in parsed_rules))
    for item, parsed in zip(created, parsed_rules, strict=False):
        await session.refresh(item)
        if item.id is not None:
            await _upsert_rule_sync_state(
                session,
                item.id,
                sync_status=ModerationRuleSyncStatus.SYNCED if source_message_id is not None else ModerationRuleSyncStatus.MANUAL,
                source_content_hash=content_hash if source_message_id is not None else None,
                source_segment_hash=_segment_hash(parsed) if source_message_id is not None else None,
                sync_note="Imported from Discord source message." if source_message_id is not None else "Imported manually from pasted text.",
                now=now,
            )
    _invalidate_rule_usage_cache(server_id=server_id)
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

    parsed_chunks: list[tuple[ParsedRule, int, int, str]] = []
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

        content = message.get("content", "")
        content_hash = _content_hash(content)
        for parsed in await parse_rules_for_import(content):
            parsed_chunks.append((parsed, channel_id, message_id, content_hash))

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
    for index, (parsed, channel_id, message_id, _) in enumerate(parsed_chunks, start=1):
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
    for item, (parsed, _, _, content_hash) in zip(created, parsed_chunks, strict=False):
        await session.refresh(item)
        if item.id is not None:
            await _upsert_rule_sync_state(
                session,
                item.id,
                sync_status=ModerationRuleSyncStatus.SYNCED,
                source_content_hash=content_hash,
                source_segment_hash=_segment_hash(parsed),
                sync_note="Imported from Discord source message.",
                now=now,
            )
    _invalidate_rule_usage_cache(server_id=server_id)
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
    parsed_rules = await parse_rules_for_import(content)
    return await import_rules(
        session=session,
        server_id=server_id,
        parsed_rules=parsed_rules,
        created_by_user_id=created_by_user_id,
        replace_existing=replace_existing,
        source_channel_id=channel_id,
        source_message_id=message_id,
        source_content=content,
    )


def _normalized_match_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_text(value).lower()
    return normalized or None


def _rule_match_keys_from_rule(rule: ModerationRule) -> list[str]:
    keys: list[str] = []
    for value in (rule.code, rule.source_marker, rule.title):
        key = _normalized_match_key(value)
        if key and key not in keys:
            keys.append(key)
    return keys


def _rule_match_keys_from_parsed(parsed: ParsedRule) -> list[str]:
    keys: list[str] = []
    for value in (parsed.code, parsed.marker, parsed.title):
        key = _normalized_match_key(value)
        if key and key not in keys:
            keys.append(key)
    return keys


def _index_existing_rules(existing: Iterable[ModerationRule]) -> dict[str, ModerationRule]:
    index: dict[str, ModerationRule] = {}
    for rule in existing:
        for key in _rule_match_keys_from_rule(rule):
            index.setdefault(key, rule)
    return index


async def sync_rules_from_source_message_edit(
    session: AsyncSession,
    server_id: int,
    channel_id: int,
    message_id: int,
    content: str,
) -> list[ModerationRule]:
    existing = (
        await session.exec(
            select(ModerationRule).where(
                ModerationRule.server_id == server_id,
                ModerationRule.source_channel_id == channel_id,
                ModerationRule.source_message_id == message_id,
                ModerationRule.is_active == True,
            )
        )
    ).all()
    if not existing:
        return []

    parsed_rules = await parse_rules_for_import(content)
    if not parsed_rules:
        return []

    now = naive_utcnow()
    content_hash = _content_hash(content)
    first_sort_order = min(rule.sort_order for rule in existing)
    created_by_user_id = existing[0].created_by_user_id
    states = await _get_rule_sync_states(session, [rule.id for rule in existing if rule.id is not None])
    existing_by_key = _index_existing_rules(existing)
    matched_ids: set[UUID] = set()
    changed: list[ModerationRule] = []
    created_pairs: list[tuple[ModerationRule, ParsedRule]] = []

    for index, parsed in enumerate(parsed_rules):
        matched = None
        for key in _rule_match_keys_from_parsed(parsed):
            candidate = existing_by_key.get(key)
            if candidate is not None and candidate.id not in matched_ids:
                matched = candidate
                break

        if matched is not None and matched.id is not None:
            matched_ids.add(matched.id)
            state = states.get(matched.id)
            protected_statuses = {ModerationRuleSyncStatus.MANUAL.value, ModerationRuleSyncStatus.CONFLICT.value}
            is_manual = state is not None and state.sync_status in protected_statuses
            if is_manual:
                matched.source_marker = matched.source_marker or parsed.marker
                matched.updated_at = now
                session.add(matched)
                await _upsert_rule_sync_state(
                    session,
                    matched.id,
                    sync_status=ModerationRuleSyncStatus.MANUAL,
                    source_content_hash=content_hash,
                    source_segment_hash=_segment_hash(parsed),
                    sync_note="Discord source changed; manual dashboard edits were preserved.",
                    now=now,
                )
            else:
                matched.code = parsed.code
                matched.title = parsed.title
                matched.description = parsed.description
                matched.sort_order = first_sort_order + index
                matched.source_marker = parsed.marker
                matched.is_active = True
                matched.updated_at = now
                session.add(matched)
                await _upsert_rule_sync_state(
                    session,
                    matched.id,
                    sync_status=ModerationRuleSyncStatus.SYNCED,
                    source_content_hash=content_hash,
                    source_segment_hash=_segment_hash(parsed),
                    sync_note="Updated from edited Discord source message.",
                    now=now,
                )
            changed.append(matched)
            continue

        rule = ModerationRule(
            server_id=server_id,
            code=parsed.code,
            title=parsed.title,
            description=parsed.description,
            sort_order=first_sort_order + index,
            source_channel_id=channel_id,
            source_message_id=message_id,
            source_marker=parsed.marker,
            is_active=True,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(rule)
        changed.append(rule)
        created_pairs.append((rule, parsed))

    await session.flush()
    for rule, parsed in created_pairs:
        if rule.id is not None:
            await _upsert_rule_sync_state(
                session,
                rule.id,
                sync_status=ModerationRuleSyncStatus.SYNCED,
                source_content_hash=content_hash,
                source_segment_hash=_segment_hash(parsed),
                sync_note="Created from edited Discord source message.",
                now=now,
            )

    for rule in existing:
        if rule.id is None or rule.id in matched_ids:
            continue
        state = states.get(rule.id)
        if state is not None and state.sync_status == ModerationRuleSyncStatus.MANUAL.value:
            await _upsert_rule_sync_state(
                session,
                rule.id,
                sync_status=ModerationRuleSyncStatus.CONFLICT,
                source_content_hash=content_hash,
                source_segment_hash=state.source_segment_hash,
                sync_note="Discord source no longer contains a matching rule; manual rule kept active for review.",
                now=now,
            )
            continue
        rule.is_active = False
        rule.updated_at = now
        session.add(rule)
        await _upsert_rule_sync_state(
            session,
            rule.id,
            sync_status=ModerationRuleSyncStatus.SYNCED,
            source_content_hash=content_hash,
            source_segment_hash=state.source_segment_hash if state is not None else None,
            sync_note="Deactivated because the rule was removed from the Discord source message.",
            now=now,
        )

    await session.flush()
    for rule in changed:
        await session.refresh(rule)
    _invalidate_rule_usage_cache(server_id=server_id)
    return changed


def _get_cached_rule_usage(server_id: int, rule_id: UUID) -> ModerationRuleUsageModel | None:
    cached = _rule_usage_cache.get((server_id, rule_id))
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= monotonic():
        _rule_usage_cache.pop((server_id, rule_id), None)
        return None
    return payload


def _store_cached_rule_usage(server_id: int, rule_id: UUID, payload: ModerationRuleUsageModel) -> None:
    _rule_usage_cache[(server_id, rule_id)] = (monotonic() + RULE_USAGE_CACHE_TTL_SECONDS, payload)


def _invalidate_rule_usage_cache(server_id: int, rule_ids: list[UUID] | None = None) -> None:
    if rule_ids is None:
        keys_to_delete = [key for key in _rule_usage_cache.keys() if key[0] == server_id]
    else:
        allowed_ids = set(rule_ids)
        keys_to_delete = [key for key in _rule_usage_cache.keys() if key[0] == server_id and key[1] in allowed_ids]
    for key in keys_to_delete:
        _rule_usage_cache.pop(key, None)


async def get_rule_usage(
    session: AsyncSession,
    server_id: int,
    rule_id: UUID,
) -> ModerationRuleUsageModel:
    cached = _get_cached_rule_usage(server_id=server_id, rule_id=rule_id)
    if cached is not None:
        return cached

    rule = await session.get(ModerationRule, rule_id)
    if not rule or rule.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule_not_found")

    action_count = int(
        (
            await session.exec(
                select(func.count())
                .select_from(ModerationActionRuleCitation)
                .where(
                    ModerationActionRuleCitation.server_id == server_id,
                    ModerationActionRuleCitation.rule_id == rule_id,
                )
            )
        ).one()
        or 0
    )
    case_count = int(
        (
            await session.exec(
                select(func.count())
                .select_from(ModerationCaseRuleCitation)
                .where(
                    ModerationCaseRuleCitation.server_id == server_id,
                    ModerationCaseRuleCitation.rule_id == rule_id,
                )
            )
        ).one()
        or 0
    )

    usage_union = union_all(
        select(ModerationActionRuleCitation.cited_at.label("cited_at")).where(
            ModerationActionRuleCitation.server_id == server_id,
            ModerationActionRuleCitation.rule_id == rule_id,
        ),
        select(ModerationCaseRuleCitation.cited_at.label("cited_at")).where(
            ModerationCaseRuleCitation.server_id == server_id,
            ModerationCaseRuleCitation.rule_id == rule_id,
        ),
    ).subquery()
    last_cited_at = (await session.exec(select(func.max(usage_union.c.cited_at)))).one()

    actor_cache = {}

    async def cached_actor(user_id: int):
        if user_id not in actor_cache:
            actor_cache[user_id] = await build_actor(session, server_id, user_id)
        return actor_cache[user_id]

    recent_action_rows = (
        await session.exec(
            select(
                ModerationActionRuleCitation.cited_at,
                ModerationAction,
            )
            .join(
                ModerationAction,
                ModerationAction.id == ModerationActionRuleCitation.action_id,
            )
            .where(
                ModerationActionRuleCitation.server_id == server_id,
                ModerationActionRuleCitation.rule_id == rule_id,
            )
            .options(
                selectinload(ModerationAction.global_user_target),
                selectinload(ModerationAction.global_user_moderator),
            )
            .order_by(ModerationActionRuleCitation.cited_at.desc())
            .limit(20)
        )
    ).all()

    recent_case_rows = (
        await session.exec(
            select(
                ModerationCaseRuleCitation.cited_at,
                ModerationCase,
            )
            .join(
                ModerationCase,
                ModerationCase.id == ModerationCaseRuleCitation.case_id,
            )
            .where(
                ModerationCaseRuleCitation.server_id == server_id,
                ModerationCaseRuleCitation.rule_id == rule_id,
            )
            .order_by(ModerationCaseRuleCitation.cited_at.desc())
            .limit(20)
        )
    ).all()

    recent_actions: list[RuleUsageActionSummaryModel] = []
    recent_cases: list[RuleUsageCaseSummaryModel] = []
    recent_citations: list[RuleUsageCitationModel] = []

    for cited_at, action in recent_action_rows:
        target_actor = await cached_actor(action.target_user_id)
        moderator_actor = await cached_actor(action.moderator_user_id)
        recent_actions.append(
            RuleUsageActionSummaryModel(
                id=str(action.id),
                action_type=action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type),
                target_user=target_actor,
                moderator=moderator_actor,
                reason=action.reason,
                created_at=action.created_at,
                expires_at=action.expires_at,
                is_active=action.is_active,
            )
        )
        recent_citations.append(
            RuleUsageCitationModel(
                cited_at=cited_at,
                source="action",
                source_id=str(action.id),
                source_title=f"{action.action_type.value if hasattr(action.action_type, 'value') else action.action_type} on {target_actor.display_name}",
                target=target_actor,
            )
        )

    for cited_at, moderation_case in recent_case_rows:
        target_actor = await cached_actor(moderation_case.target_user_id)
        recent_cases.append(
            RuleUsageCaseSummaryModel(
                id=str(moderation_case.id),
                title=moderation_case.title,
                status=moderation_case.status,
                created_at=moderation_case.created_at,
                target_user=target_actor,
            )
        )
        recent_citations.append(
            RuleUsageCitationModel(
                cited_at=cited_at,
                source="case",
                source_id=str(moderation_case.id),
                source_title=moderation_case.title,
                target=target_actor,
            )
        )

    offender_union = union_all(
        select(ModerationAction.target_user_id.label("user_id"))
        .join(
            ModerationActionRuleCitation,
            ModerationActionRuleCitation.action_id == ModerationAction.id,
        )
        .where(
            ModerationActionRuleCitation.server_id == server_id,
            ModerationActionRuleCitation.rule_id == rule_id,
        ),
        select(ModerationCase.target_user_id.label("user_id"))
        .join(
            ModerationCaseRuleCitation,
            ModerationCaseRuleCitation.case_id == ModerationCase.id,
        )
        .where(
            ModerationCaseRuleCitation.server_id == server_id,
            ModerationCaseRuleCitation.rule_id == rule_id,
        ),
    ).subquery()
    top_offender_rows = (
        await session.exec(
            select(
                offender_union.c.user_id,
                func.count().label("usage_count"),
            )
            .group_by(offender_union.c.user_id)
            .order_by(desc("usage_count"), offender_union.c.user_id.asc())
            .limit(5)
        )
    ).all()

    usage_count = action_count + case_count
    payload = ModerationRuleUsageModel(
        rule_id=str(rule.id),
        code=rule.code,
        title=rule.title,
        usage_count=usage_count,
        action_count=action_count,
        case_count=case_count,
        last_cited_at=last_cited_at,
        top_offenders=[
            RuleUsageTopOffenderModel(
                user=await cached_actor(int(row[0])),
                count=int(row[1] or 0),
                action_count=int(row[1] or 0),
            )
            for row in top_offender_rows
        ],
        recent_citations=sorted(recent_citations, key=lambda item: item.cited_at, reverse=True)[:20],
        rule=to_rule_read_model(
            rule=rule,
            usage_count=usage_count,
            last_cited_at=last_cited_at,
        ),
        recent_actions=recent_actions[:10],
        recent_cases=recent_cases[:10],
    )
    _store_cached_rule_usage(server_id=server_id, rule_id=rule_id, payload=payload)
    return payload

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

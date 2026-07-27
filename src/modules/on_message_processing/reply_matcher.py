import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Pattern

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import engine
from src.db.models import Replies, ReplyConcept, ServerReplySettings, Triggers
from src.modules.on_message_processing.processing_methods import (
    normalize_and_stem_reply_text,
    normalize_reply_text,
)


CONCEPT_PLACEHOLDER_RE = re.compile(r"{{\s*([\wа-яё-]+)\s*}}", re.IGNORECASE)
MATCHER_CACHE_TTL_SECONDS = max(int(os.getenv("REPLY_MATCHER_CACHE_TTL_SECONDS", "30")), 1)


@dataclass(frozen=True, slots=True)
class CompiledReplySettings:
    included_channel_ids: frozenset[str] = frozenset()
    excluded_channel_ids: frozenset[str] = frozenset()
    excluded_role_ids: frozenset[str] = frozenset()
    excluded_user_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CompiledReplyRule:
    reply_id: str
    response_text: str
    is_fstring: bool
    trigger_text: str
    source: str
    specificity: int
    pattern: Pattern[str]


@dataclass(frozen=True, slots=True)
class GuildReplyMatcher:
    server_id: int
    settings: CompiledReplySettings
    rules: tuple[CompiledReplyRule, ...]

    def match(self, message_content: str) -> CompiledReplyRule | None:
        normalized_message = normalize_and_stem_reply_text(message_content)
        if not normalized_message:
            return None
        for rule in self.rules:
            if rule.pattern.search(normalized_message):
                return rule
        return None


@dataclass(frozen=True, slots=True)
class ReplyTriggerCoverage:
    id: str
    text: str
    source: str
    normalized_text: str
    covered_by_id: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class _CacheEntry:
    matcher: GuildReplyMatcher
    expires_at: float


_matcher_cache: dict[int, _CacheEntry] = {}
_matcher_locks: dict[int, asyncio.Lock] = {}


def invalidate_reply_matcher(server_id: int | None = None) -> None:
    if server_id is None:
        _matcher_cache.clear()
        return
    _matcher_cache.pop(int(server_id), None)


def _settings_snapshot(settings: ServerReplySettings | None) -> CompiledReplySettings:
    if settings is None:
        return CompiledReplySettings()
    return CompiledReplySettings(
        included_channel_ids=frozenset(settings.included_channel_ids or []),
        excluded_channel_ids=frozenset(settings.excluded_channel_ids or []),
        excluded_role_ids=frozenset(settings.excluded_role_ids or []),
        excluded_user_ids=frozenset(settings.excluded_user_ids or []),
    )


def _literal_tokens(text: str) -> list[str]:
    return normalize_and_stem_reply_text(text).split()


def _compile_trigger_pattern(
    trigger_text: str,
    concepts: dict[str, tuple[str, ...]],
) -> tuple[Pattern[str], int] | None:
    units: list[str] = []
    specificity = 0
    cursor = 0
    for placeholder in CONCEPT_PLACEHOLDER_RE.finditer(trigger_text):
        literal = trigger_text[cursor:placeholder.start()]
        literal_tokens = _literal_tokens(literal)
        units.extend(re.escape(token) for token in literal_tokens)
        specificity += len(literal_tokens)

        concept_name = placeholder.group(1).casefold()
        variants = concepts.get(concept_name)
        if not variants:
            return None
        variant_patterns: list[str] = []
        for variant in variants:
            tokens = _literal_tokens(variant)
            if tokens:
                variant_patterns.append(r"\s+".join(re.escape(token) for token in tokens))
        if not variant_patterns:
            return None
        units.append("(?:" + "|".join(sorted(set(variant_patterns), key=len, reverse=True)) + ")")
        specificity += 1
        cursor = placeholder.end()

    trailing_tokens = _literal_tokens(trigger_text[cursor:])
    units.extend(re.escape(token) for token in trailing_tokens)
    specificity += len(trailing_tokens)
    if not units:
        return None

    expression = r"(?<!\w)" + r"\s+".join(units) + r"(?!\w)"
    return re.compile(expression, re.UNICODE), specificity


def analyze_reply_trigger_coverage(
    phrases: list[tuple[str, str, str]],
    concepts: dict[str, tuple[str, ...]],
) -> list[ReplyTriggerCoverage]:
    """Explain redundant triggers using the exact patterns used by the live matcher.

    Representative questions win over manual triggers, which win over generated
    variations. Within one source, the original order wins. A later phrase is
    covered when an earlier matcher pattern recognizes it or both compile to the
    same pattern (important for concept placeholders).
    """
    source_priority = {"representative": 0, "manual": 1, "generated": 2}
    indexed = list(enumerate(phrases))
    indexed.sort(key=lambda item: (source_priority.get(item[1][2], 99), item[0]))

    canonical: list[tuple[str, str, Pattern[str]]] = []
    results: dict[str, ReplyTriggerCoverage] = {}
    for _index, (phrase_id, phrase_text, source) in indexed:
        normalized_text = normalize_and_stem_reply_text(phrase_text)
        compiled = _compile_trigger_pattern(phrase_text, concepts)
        covered_by_id: str | None = None
        reason: str | None = None
        if compiled is not None:
            pattern, _specificity = compiled
            for canonical_id, canonical_text, canonical_pattern in canonical:
                if (
                    canonical_pattern.pattern == pattern.pattern
                    or canonical_pattern.search(normalized_text)
                ):
                    covered_by_id = canonical_id
                    reason = (
                        "exact_duplicate"
                        if normalize_reply_text(canonical_text)
                        == normalize_reply_text(phrase_text)
                        else "language_matching"
                    )
                    break
            if covered_by_id is None:
                canonical.append((phrase_id, phrase_text, pattern))

        results[phrase_id] = ReplyTriggerCoverage(
            id=phrase_id,
            text=phrase_text,
            source=source,
            normalized_text=normalized_text,
            covered_by_id=covered_by_id,
            reason=reason,
        )

    return [results[phrase_id] for phrase_id, _text, _source in phrases]


def compile_guild_reply_matcher(
    server_id: int,
    settings: ServerReplySettings | None,
    concepts: list[ReplyConcept],
    rows: list[tuple[Triggers, Replies]],
) -> GuildReplyMatcher:
    concepts_by_name = {
        concept.name.casefold(): tuple(concept.variants or [])
        for concept in concepts
    }
    rules: list[CompiledReplyRule] = []
    for trigger, reply in rows:
        compiled = _compile_trigger_pattern(trigger.message, concepts_by_name)
        if compiled is None:
            continue
        pattern, specificity = compiled
        response_text = reply.bot_reply
        rules.append(
            CompiledReplyRule(
                reply_id=str(reply.id),
                response_text=response_text,
                is_fstring=response_text.startswith("f'") or response_text.startswith('f"'),
                trigger_text=trigger.message,
                source=trigger.source or "representative",
                specificity=specificity,
                pattern=pattern,
            )
        )

    source_priority = {"representative": 2, "manual": 1, "generated": 0}
    rules.sort(
        key=lambda rule: (
            source_priority.get(rule.source, -1),
            rule.specificity,
            len(rule.trigger_text),
            rule.reply_id,
        ),
        reverse=True,
    )
    return GuildReplyMatcher(
        server_id=server_id,
        settings=_settings_snapshot(settings),
        rules=tuple(rules),
    )


async def _load_reply_matcher(server_id: int) -> GuildReplyMatcher:
    async with AsyncSession(engine) as session:
        settings = await session.get(ServerReplySettings, server_id)
        concepts = list(
            (
                await session.exec(
                    select(ReplyConcept).where(ReplyConcept.server_id == server_id)
                )
            ).all()
        )
        rows = list(
            (
                await session.exec(
                    select(Triggers, Replies)
                    .join(Replies, Triggers.reply_id == Replies.id)
                    .where(Replies.server_id == server_id)
                )
            ).all()
        )
    return compile_guild_reply_matcher(server_id, settings, concepts, rows)


async def get_reply_matcher(server_id: int) -> GuildReplyMatcher:
    server_id = int(server_id)
    now = time.monotonic()
    cached = _matcher_cache.get(server_id)
    if cached is not None and cached.expires_at > now:
        return cached.matcher

    lock = _matcher_locks.setdefault(server_id, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _matcher_cache.get(server_id)
        if cached is not None and cached.expires_at > now:
            return cached.matcher
        matcher = await _load_reply_matcher(server_id)
        _matcher_cache[server_id] = _CacheEntry(
            matcher=matcher,
            expires_at=now + MATCHER_CACHE_TTL_SECONDS,
        )
        return matcher

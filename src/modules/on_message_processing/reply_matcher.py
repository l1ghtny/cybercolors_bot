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
    russian_word_forms_matching_reply_stem,
)


CONCEPT_PLACEHOLDER_RE = re.compile(r"{{\s*([\wа-яё-]+)\s*}}", re.IGNORECASE)
CONCEPT_TEXT_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
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


@dataclass(frozen=True, slots=True)
class ReplyTriggerVariationGroup:
    label: str
    kind: str
    variants: tuple[str, ...]


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


def canonicalize_reply_concept_references(
    text: str,
    concepts: dict[str, tuple[str, ...]],
) -> str:
    """Replace configured concept variants with their canonical placeholders.

    Matching uses the same normalized Russian stems as the live reply matcher,
    while replacements preserve the rest of the administrator-facing phrase.
    This is a configuration-time helper; it is not called per message.
    """
    concepts_by_name = {
        name.casefold(): tuple(dict.fromkeys(variants))
        for name, variants in concepts.items()
        if variants
    }
    if not text or not concepts_by_name:
        return text

    def canonical_placeholder(match: re.Match[str]) -> str:
        name = match.group(1).casefold()
        return f"{{{{{name}}}}}" if name in concepts_by_name else match.group(0)

    canonical = CONCEPT_PLACEHOLDER_RE.sub(canonical_placeholder, text)
    placeholder_spans = [match.span() for match in CONCEPT_PLACEHOLDER_RE.finditer(canonical)]
    tokens = list(CONCEPT_TEXT_TOKEN_RE.finditer(canonical))
    token_stems = [normalize_and_stem_reply_text(match.group(0)) for match in tokens]

    variant_patterns: list[tuple[tuple[str, ...], str, int]] = []
    for concept_name, variants in concepts_by_name.items():
        for variant in variants:
            stems = tuple(normalize_and_stem_reply_text(variant).split())
            if stems:
                variant_patterns.append((stems, concept_name, len(normalize_reply_text(variant))))
    variant_patterns.sort(key=lambda item: (len(item[0]), item[2]), reverse=True)

    replacements: list[tuple[int, int, str]] = []
    token_index = 0
    while token_index < len(tokens):
        token = tokens[token_index]
        if any(start <= token.start() < end for start, end in placeholder_spans):
            token_index += 1
            continue

        matched = False
        for stems, concept_name, _variant_length in variant_patterns:
            end_index = token_index + len(stems)
            if end_index > len(tokens):
                continue
            candidate_tokens = tokens[token_index:end_index]
            if any(
                any(start < candidate.end() and candidate.start() < end for start, end in placeholder_spans)
                for candidate in candidate_tokens
            ):
                continue
            if tuple(token_stems[token_index:end_index]) != stems:
                continue
            replacements.append(
                (token.start(), candidate_tokens[-1].end(), f"{{{{{concept_name}}}}}")
            )
            token_index = end_index
            matched = True
            break
        if not matched:
            token_index += 1

    for start, end, placeholder in reversed(replacements):
        canonical = canonical[:start] + placeholder + canonical[end:]
    return canonical


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


def describe_reply_trigger_variations(
    trigger_text: str,
    concepts: dict[str, tuple[str, ...]],
) -> list[ReplyTriggerVariationGroup]:
    """Describe every useful substitution accepted by the live matcher.

    Returning substitutions instead of their Cartesian product avoids emitting
    grammatically invalid phrases while still exposing every dictionary form
    and reusable concept option that administrators do not need to add.
    """
    groups: list[ReplyTriggerVariationGroup] = []
    seen: set[tuple[str, str]] = set()

    def add_word_groups(value: str) -> None:
        for token in normalize_reply_text(value).split():
            forms = russian_word_forms_matching_reply_stem(token)
            key = ("word", token)
            if len(forms) < 2 or key in seen:
                continue
            seen.add(key)
            groups.append(
                ReplyTriggerVariationGroup(
                    label=token,
                    kind="word",
                    variants=forms,
                )
            )

    cursor = 0
    for placeholder in CONCEPT_PLACEHOLDER_RE.finditer(trigger_text):
        add_word_groups(trigger_text[cursor:placeholder.start()])
        concept_name = placeholder.group(1).casefold()
        variants = tuple(dict.fromkeys(concepts.get(concept_name, ())))
        if variants:
            concept_key = ("concept", concept_name)
            if concept_key not in seen:
                seen.add(concept_key)
                groups.append(
                    ReplyTriggerVariationGroup(
                        label=f"{{{{{concept_name}}}}}",
                        kind="concept",
                        variants=variants,
                    )
                )
            for variant in variants:
                add_word_groups(variant)
        cursor = placeholder.end()
    add_word_groups(trigger_text[cursor:])
    return groups


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

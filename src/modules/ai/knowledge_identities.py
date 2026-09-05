"""Indexed directory lookup. Literal checks validate only GIN/equality candidates."""

from dataclasses import dataclass, field
import os
from typing import Any

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

MAX_ALIAS_CANDIDATES = 100
MAX_IDENTITY_TARGETS = 8


def identity_retrieval_enabled(server_id: int) -> bool:
    configured = {part.strip() for part in os.getenv("AI_KNOWLEDGE_IDENTITY_SERVER_IDS", "").split(",")}
    return "*" in configured or str(server_id) in configured


@dataclass
class IdentitySearch:
    matches: list[dict[str, Any]] = field(default_factory=list)
    ambiguities: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False


def _alias_occurrence(query: str, alias: str) -> tuple[bool, bool]:
    """Validate full spelling and boundaries after indexed candidate retrieval.

    In particular, PostgreSQL's phrase parser equates foo_bar with foo bar.
    This check cannot discover names: it sees only the bounded indexed matches.
    """
    start = 0
    found = False
    while alias and (position := query.find(alias, start)) >= 0:
        end = position + len(alias)
        before = query[position - 1] if position else ""
        after = query[end] if end < len(query) else ""
        identifier = lambda char: bool(char) and (char.isalnum() or char in "_.")
        # A sentence-ending period is punctuation; a period followed by more
        # identifier text belongs to the handle (aronz.other != aronz).
        after_identifier = identifier(after) and not (
            after == "." and (end + 1 == len(query) or not identifier(query[end + 1]))
        )
        if not identifier(before) and not after_identifier:
            found = True
            if before == "@":
                return True, True
        start = end
    return found, False


def _identity(row) -> dict[str, Any]:
    return {
        "user_id": str(row.user_id), "username": row.username,
        "global_name": row.global_name, "server_nickname": row.server_nickname,
        "is_member": row.is_member,
    }


async def lookup_identity_targets(session: AsyncSession, *, server_id: int, user_ids: list[int]) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    rows = (await session.exec(text("""
        SELECT m.user_id, m.server_nickname, m.is_member, g.username, g.global_name
        FROM users AS m JOIN global_users AS g ON g.discord_id = m.user_id
        WHERE m.server_id = :server_id AND m.user_id = ANY(CAST(:user_ids AS bigint[]))
        ORDER BY m.user_id
    """), params={"server_id": server_id, "user_ids": user_ids})).all()
    return [{"identity": _identity(row), "evidence": [{
        "alias_kind": None, "matched_alias": None, "match_type": "explicit_target",
    }]} for row in rows]


async def search_identity_aliases(session: AsyncSession, *, server_id: int, query: str) -> IdentitySearch:
    # A complete @handle is also an equality candidate, including punctuation
    # that produces no lexemes. Normalize in the candidate query so this does
    # not add a separate database round trip. Explicit handles match usernames.
    params = {"server_id": server_id, "query": query, "limit": MAX_ALIAS_CANDIDATES + 1}
    rows = (await session.exec(text("""
        WITH normalized AS (
            SELECT kb_identity_normalize(:query) AS value
        ), input AS (
            SELECT value, CASE WHEN left(value, 1) = '@' THEN substr(value, 2) ELSE value END AS equality
            FROM normalized
        )
        SELECT input.value AS normalized_query, input.equality, candidates.*
        FROM input CROSS JOIN LATERAL (
            SELECT * FROM (
                SELECT normalized_alias, alias_kind FROM ai_knowledge_identity_aliases
                WHERE server_id = :server_id AND normalized_alias = input.equality
                UNION
                SELECT normalized_alias, alias_kind FROM ai_knowledge_identity_aliases
                WHERE server_id = :server_id
                  AND search_vector @@ kb_identity_any_terms(input.value)
                  AND to_tsvector('pg_catalog.simple', input.value) @@ alias_phrase
            ) AS found
            ORDER BY (normalized_alias = input.equality) DESC, length(normalized_alias) DESC, normalized_alias, alias_kind
            LIMIT :limit
        ) AS candidates
    """), params=params)).all()
    if not rows:
        return IdentitySearch()
    normalized, equality = rows[0].normalized_query, rows[0].equality
    result = IdentitySearch(truncated=len(rows) > MAX_ALIAS_CANDIDATES)
    aliases: dict[str, str] = {}
    explicit_handles: set[str] = set()
    for row in rows[:MAX_ALIAS_CANDIDATES]:
        found, handle = _alias_occurrence(normalized, row.normalized_alias)
        if not found:
            continue
        if handle:
            explicit_handles.add(row.normalized_alias)
            if row.alias_kind != "username":
                continue
        aliases[row.normalized_alias] = (
            "exact_alias" if row.normalized_alias == equality else "alias_phrase"
        )
    if not aliases:
        return result

    # Collision counts precede LIMIT and source eligibility. Someone without a
    # biography still counts as another possible referent of the same name.
    collisions = (await session.exec(text("""
        WITH people AS (
            SELECT DISTINCT ON (a.normalized_alias, a.user_id)
                a.normalized_alias, a.user_id, a.alias_kind, a.alias_text,
                m.server_nickname, m.is_member, g.username, g.global_name
            FROM ai_knowledge_identity_aliases AS a
            JOIN users AS m ON m.server_id = a.server_id AND m.user_id = a.user_id
            JOIN global_users AS g ON g.discord_id = a.user_id
            WHERE a.server_id = :server_id
              AND a.normalized_alias = ANY(CAST(:aliases AS text[]))
              AND (NOT (a.normalized_alias = ANY(CAST(:handles AS text[]))) OR a.alias_kind = 'username')
            ORDER BY a.normalized_alias, a.user_id, (a.alias_kind = 'username') DESC, a.alias_kind
        ), ranked AS (
            SELECT *, count(*) OVER (PARTITION BY normalized_alias) AS people_count,
                row_number() OVER (PARTITION BY normalized_alias ORDER BY user_id) AS person_rank
            FROM people
        )
        SELECT * FROM ranked WHERE person_rank <= :limit
        ORDER BY normalized_alias, user_id
    """), params={"server_id": server_id, "aliases": list(aliases), "handles": list(explicit_handles), "limit": MAX_IDENTITY_TARGETS})).all()
    groups: dict[str, list[Any]] = {}
    for row in collisions:
        groups.setdefault(row.normalized_alias, []).append(row)
    for alias, people in groups.items():
        if people[0].people_count > 1:
            result.ambiguities.append({
                "matched_alias": alias, "candidates": [_identity(row) for row in people],
                "overflow": people[0].people_count > MAX_IDENTITY_TARGETS,
            })
            result.truncated |= people[0].people_count > MAX_IDENTITY_TARGETS
            continue
        row = people[0]
        result.matches.append({"identity": _identity(row), "evidence": [{
            "alias_kind": row.alias_kind, "matched_alias": row.alias_text,
            "match_type": "explicit_handle" if alias in explicit_handles else aliases[alias],
        }]})
    return result

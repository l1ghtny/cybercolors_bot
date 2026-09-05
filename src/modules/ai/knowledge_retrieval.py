"""Combine indexed identity evidence with semantic KB passages."""

import logging
import re
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlmodel.ext.asyncio.session import AsyncSession

from src.modules.ai.embeddings import KnowledgeEmbedder, get_knowledge_embedder
from src.modules.ai.knowledge import (
    KNOWLEDGE_SOURCE_SCOPE, READY_SOURCE_STATUSES, normalize_knowledge_text,
    search_server_knowledge, vector_literal,
)
from src.modules.ai.knowledge_identities import (
    MAX_IDENTITY_TARGETS, IdentitySearch, identity_retrieval_enabled,
    lookup_identity_targets, search_identity_aliases,
)

logger = logging.getLogger(__name__)
_DISCORD_MENTION = re.compile(r"<@!?(\d{1,19})>")
_MATCH_ORDER = {"explicit_target": 0, "explicit_handle": 1, "exact_alias": 2, "alias_phrase": 3}


@asynccontextmanager
async def _database_branch(session: AsyncSession):
    """Bound candidate work and roll back a failed branch without losing peers."""
    async with session.begin_nested():
        previous = (await session.exec(text("SELECT setting::integer FROM pg_settings WHERE name = 'statement_timeout'"))).scalar_one()
        timeout = min(previous, 1500) if previous else 1500
        await session.exec(text("SELECT set_config('statement_timeout', :timeout, true)"), params={"timeout": str(timeout)})
        yield
        await session.exec(text("SELECT set_config('statement_timeout', :timeout, true)"), params={"timeout": str(previous)})


def _empty_result() -> dict[str, Any]:
    return {"items": [], "identity_matches": [], "ambiguities": [], "truncated": False, "degraded_components": []}


def _match_order(match: dict) -> tuple:
    return min((
        _MATCH_ORDER[evidence["match_type"]], -len(evidence.get("matched_alias") or ""),
        int(match["identity"]["user_id"]),
    ) for evidence in match["evidence"])


async def _subject_chunks(
    session: AsyncSession, *, server_id: int, user_ids: list[int], visibility: str,
    source_ids: list[str], query_vector: str | None, embedder: KnowledgeEmbedder | None,
) -> list[dict]:
    if not user_ids:
        return []
    distance = "chunk.embedding OPERATOR(public.<=>) CAST(:query_vector AS public.vector)" if query_vector else "NULL::double precision"
    source_filter = "AND CAST(source.id AS text) IN :source_ids" if source_ids else ""
    statement = text(f"""
        SELECT * FROM (
            SELECT chunk.id AS chunk_id, chunk.source_id, chunk.chunk_ordinal, chunk.chunk_text,
                source.source_type, source.subject_type, source.subject_user_id, source.title,
                source.visibility, source.source_url, source.indexed_at, {distance} AS distance,
                row_number() OVER (PARTITION BY source.subject_user_id ORDER BY
                    {distance} ASC NULLS LAST, source.indexed_at DESC NULLS LAST,
                    source.id, chunk.chunk_ordinal) AS subject_rank
            FROM ai_knowledge_chunks AS chunk JOIN ai_knowledge_sources AS source ON source.id = chunk.source_id
            WHERE {KNOWLEDGE_SOURCE_SCOPE} {source_filter}
              AND source.subject_user_id IN :user_ids
        ) AS ranked WHERE subject_rank <= 3
        ORDER BY subject_rank, subject_user_id
    """).bindparams(
        bindparam("ready_statuses", expanding=True), bindparam("visibility_values", expanding=True),
        bindparam("user_ids", expanding=True), *([bindparam("source_ids", expanding=True)] if source_ids else []),
    )
    params = {"server_id": server_id, "ready_statuses": list(READY_SOURCE_STATUSES),
              "visibility_values": [visibility], "user_ids": user_ids}
    if source_ids:
        params["source_ids"] = source_ids
    if query_vector:
        params["query_vector"] = query_vector
    rows = (await session.exec(statement, params=params)).all()
    return [{
        "source_id": str(row.source_id), "source_type": row.source_type, "subject_type": row.subject_type,
        "subject_user_id": str(row.subject_user_id), "title": row.title, "visibility": row.visibility,
        "chunk_id": str(row.chunk_id), "chunk_ordinal": row.chunk_ordinal, "text": row.chunk_text,
        "score": 1 - float(row.distance) if row.distance is not None else None,
        "distance": float(row.distance) if row.distance is not None else None,
        "source_url": row.source_url, "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
        "embedding_provider": embedder.provider_name if embedder else None,
        "embedding_model": embedder.model if embedder else None,
    } for row in rows]


def _merge_results(semantic: list[dict], subjects: list[dict], matches: list[dict], limit: int) -> tuple[list[dict], bool]:
    by_user = {match["identity"]["user_id"]: match for match in matches}
    user_order = {match["identity"]["user_id"]: rank for rank, match in enumerate(matches)}
    buckets: dict[str, list[dict]] = {}
    for item in subjects:
        buckets.setdefault(item["subject_user_id"], []).append(item)
    identity_items = [item for ordinal in range(3) for user_id in sorted(buckets, key=lambda uid: user_order[uid])
                      for item in buckets[user_id][ordinal:ordinal + 1]]
    items: dict[str, dict] = {}
    ranks: dict[str, float] = {}
    for method, candidates in (("semantic", semantic), ("identity", identity_items)):
        for rank, item in enumerate(candidates, 1):
            key = item["chunk_id"]
            merged = items.setdefault(key, {**item, "retrieval_methods": [], "identity": None, "identity_evidence": []})
            merged["retrieval_methods"].append(method)
            ranks[key] = ranks.get(key, 0.0) + 1 / (60 + rank)
            match = by_user.get(item.get("subject_user_id"))
            if match:
                merged["identity"] = match["identity"]
                merged["identity_evidence"] = match["evidence"]
    reserved: list[str] = []
    for match in matches:
        if _match_order(match)[0] <= 2:
            bucket = buckets.get(match["identity"]["user_id"], [])
            if bucket:
                reserved.append(bucket[0]["chunk_id"])
    ordered = list(dict.fromkeys([*reserved, *sorted(items, key=lambda key: (
        -ranks[key], "semantic" not in items[key]["retrieval_methods"],
        items[key]["source_id"], items[key]["chunk_ordinal"], key,
    ))]))
    return [items[key] for key in ordered[:limit]], len(reserved) > limit


async def retrieve_server_knowledge(
    session: AsyncSession, *, server_id: int, query: str, visibility: str = "public_answer",
    limit: int = 5, target_user_ids: list[int] | None = None,
    source_id: str | None = None, source_ids: list[str] | None = None,
    embedder: KnowledgeEmbedder | None = None, identity_enabled: bool | None = None,
) -> dict[str, Any]:
    result = _empty_result()
    query = normalize_knowledge_text(query)
    if not query:
        return result
    limit = min(max(int(limit), 1), 20)
    sources = [str(UUID(source_id))] if source_id else list(dict.fromkeys(str(UUID(value)) for value in (source_ids or [])))
    enabled = identity_retrieval_enabled(server_id) if identity_enabled is None else identity_enabled
    if not enabled or visibility == "moderation":
        result["items"] = await search_server_knowledge(
            session, server_id=server_id, query=query, visibility=visibility, limit=limit,
            embedder=embedder, source_ids=sources,
        )
        return result

    targets = list(dict.fromkeys([*(int(value) for value in target_user_ids or []),
                                *(int(value) for value in _DISCORD_MENTION.findall(query))]))
    if any(value <= 0 or value > 2**63 - 1 for value in targets):
        raise ValueError("Discord target IDs must be positive signed bigint values")
    result["truncated"] = len(targets) > MAX_IDENTITY_TARGETS
    targets = targets[:MAX_IDENTITY_TARGETS]
    directory = IdentitySearch()
    explicit_matches: list[dict] = []
    if targets:
        try:
            async with _database_branch(session):
                explicit_matches = await lookup_identity_targets(session, server_id=server_id, user_ids=targets)
        except Exception:
            logger.warning("knowledge_identity_targets_failed server_id=%s", server_id, exc_info=True)
            result["degraded_components"].append("identity")
    try:
        async with _database_branch(session):
            directory = await search_identity_aliases(session, server_id=server_id, query=query)
    except Exception:
        logger.warning("knowledge_identity_search_failed server_id=%s", server_id, exc_info=True)
        if "identity" not in result["degraded_components"]:
            result["degraded_components"].append("identity")

    explicit_ids = {match["identity"]["user_id"] for match in explicit_matches}
    excluded_ids: set[str] = set()
    # Resolve only the ambiguous alias to which an explicit selection belongs.
    for group in directory.ambiguities:
        candidate_ids = {candidate["user_id"] for candidate in group["candidates"]}
        selected = candidate_ids & explicit_ids
        excluded_ids.update(candidate_ids - selected)
        if not selected or group["overflow"]:
            result["ambiguities"].append(group)
    combined: dict[str, dict] = {}
    for match in [*explicit_matches, *directory.matches]:
        user_id = match["identity"]["user_id"]
        if user_id in excluded_ids:
            continue
        if user_id in combined:
            combined[user_id]["evidence"].extend(match["evidence"])
        else:
            combined[user_id] = match
    matches = sorted(combined.values(), key=_match_order)
    result["truncated"] |= directory.truncated or len(matches) > MAX_IDENTITY_TARGETS
    matches = matches[:MAX_IDENTITY_TARGETS]
    result["identity_matches"] = matches

    active_embedder = None
    query_vector = None
    semantic: list[dict] = []
    try:
        active_embedder = embedder or await get_knowledge_embedder()
        query_vector = vector_literal((await active_embedder.embed_texts([query]))[0])
        async with session.begin_nested():
            semantic = await search_server_knowledge(
                session, server_id=server_id, query=query, visibility=visibility, limit=20,
                embedder=active_embedder, query_vector=query_vector, source_ids=sources,
            )
    except Exception:
        logger.warning("knowledge_semantic_search_failed server_id=%s", server_id, exc_info=True)
        result["degraded_components"].append("semantic")
    overflow = any(group["overflow"] for group in directory.ambiguities)
    semantic = [item for item in semantic if item.get("subject_user_id") not in excluded_ids
                and (not overflow or not item.get("subject_user_id") or item["subject_user_id"] in combined)]
    subjects: list[dict] = []
    if matches:
        try:
            async with _database_branch(session):
                subjects = await _subject_chunks(
                    session, server_id=server_id, user_ids=[int(match["identity"]["user_id"]) for match in matches],
                    visibility=visibility, source_ids=sources, query_vector=query_vector, embedder=active_embedder,
                )
        except Exception:
            logger.warning("knowledge_subject_search_failed server_id=%s", server_id, exc_info=True)
            result["degraded_components"].append("subject_knowledge")
    result["items"], budget_truncated = _merge_results(semantic, subjects, matches, limit)
    result["truncated"] |= budget_truncated
    return result

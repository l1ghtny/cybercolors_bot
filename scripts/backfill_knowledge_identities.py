"""Build/reconcile current identity aliases without re-embedding KB content."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from src.db.database import engine, get_async_session


async def backfill_batch(session, *, server_id: int | None, after_user_id: int, batch_size: int) -> tuple[int, int]:
    """Lock accounts first, then memberships, in stable order for each batch."""
    params = {"server_id": server_id, "after": after_user_id, "limit": batch_size}
    user_ids = (await session.exec(text("""
        SELECT g.discord_id FROM global_users AS g
        WHERE g.discord_id > :after AND EXISTS (
            SELECT 1 FROM users AS m WHERE m.user_id = g.discord_id
              AND (CAST(:server_id AS bigint) IS NULL OR m.server_id = :server_id)
        ) ORDER BY g.discord_id LIMIT :limit FOR UPDATE OF g
    """), params=params)).scalars().all()
    if not user_ids:
        return after_user_id, 0
    memberships = (await session.exec(text("""
        SELECT m.server_id, m.user_id FROM users AS m
        WHERE m.user_id = ANY(CAST(:ids AS bigint[]))
          AND (CAST(:server_id AS bigint) IS NULL OR m.server_id = :server_id)
        ORDER BY m.user_id, m.server_id FOR UPDATE OF m
    """), params={"ids": user_ids, "server_id": server_id})).all()
    # One round trip refreshes the locked batch. The trigger helper replaces
    # removed fields too, making repeated runs a reconciliation operation.
    await session.exec(text("""
        SELECT kb_identity_refresh(m.server_id, m.user_id) FROM users AS m
        WHERE m.user_id = ANY(CAST(:ids AS bigint[]))
          AND (CAST(:server_id AS bigint) IS NULL OR m.server_id = :server_id)
        ORDER BY m.user_id, m.server_id
    """), params={"ids": user_ids, "server_id": server_id})
    return max(user_ids), len(memberships)


async def identity_audit(session, *, server_id: int | None) -> dict:
    row = (await session.exec(text("""
        WITH subjects AS (
            SELECT DISTINCT server_id, subject_user_id AS user_id FROM ai_knowledge_sources
            WHERE subject_user_id IS NOT NULL AND deleted_at IS NULL
              AND (CAST(:server_id AS bigint) IS NULL OR server_id = :server_id)
        )
        SELECT count(*) AS linked_accounts,
            count(*) FILTER (WHERE m.user_id IS NULL) AS missing_memberships,
            count(*) FILTER (WHERE coalesce(g.username, '') = '') AS missing_usernames,
            count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM ai_knowledge_identity_aliases AS a
                WHERE a.server_id = s.server_id AND a.user_id = s.user_id)) AS missing_aliases
        FROM subjects AS s LEFT JOIN users AS m ON m.server_id = s.server_id AND m.user_id = s.user_id
        LEFT JOIN global_users AS g ON g.discord_id = s.user_id
    """), params={"server_id": server_id})).mappings().one()
    return dict(row)


async def refresh_linked_accounts(*, server_id: int, limit: int, after_user_id: int = 0) -> dict:
    from api.services.moderation_users_service import _hydrate_membership_from_discord
    from src.db.models import GlobalUser, User
    async with get_async_session() as session:
        user_ids = (await session.exec(text("""
            SELECT DISTINCT subject_user_id FROM ai_knowledge_sources
            WHERE server_id = :server_id AND subject_user_id IS NOT NULL AND deleted_at IS NULL
              AND subject_user_id > :after
            ORDER BY subject_user_id LIMIT :limit
        """), params={"server_id": server_id, "limit": limit + 1, "after": after_user_id})).scalars().all()
    report = {"refreshed": 0, "unavailable": 0, "refresh_truncated": len(user_ids) > limit,
              "refresh_after_user_id": max(user_ids[:limit], default=after_user_id)}
    for user_id in user_ids[:limit]:
        async with get_async_session() as session:
            account = await session.get(GlobalUser, user_id)
            membership = await session.get(User, (user_id, server_id))
            if account is None:
                report["unavailable"] += 1
                continue
            _, display_name = await _hydrate_membership_from_discord(session, server_id, user_id, account, membership)
            await session.commit()
            report["refreshed" if display_name else "unavailable"] += 1
    return report


async def run(args):
    processed = 0
    cursor = args.after_user_id
    if args.refresh_linked:
        print(json.dumps(await refresh_linked_accounts(server_id=args.server_id, limit=args.refresh_limit,
                                                      after_user_id=args.refresh_after_user_id)))
    if not args.check:
        while True:
            for attempt in range(3):
                try:
                    async with get_async_session() as session:
                        next_cursor, count = await backfill_batch(session, server_id=args.server_id,
                            after_user_id=cursor, batch_size=args.batch_size)
                        await session.commit()
                    break
                except DBAPIError as exc:
                    if getattr(exc.orig, "sqlstate", None) not in {"40P01", "40001"} or attempt == 2:
                        raise
                    await asyncio.sleep(0.1 * (attempt + 1))
            if not count:
                break
            cursor = next_cursor
            processed += count
            print(json.dumps({"memberships_processed": processed, "after_user_id": cursor}), flush=True)
    async with get_async_session() as session:
        print(json.dumps(await identity_audit(session, server_id=args.server_id)))
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--server-id', type=int)
    target.add_argument('--all-servers', action='store_true')
    parser.add_argument('--batch-size', type=int, default=100)
    parser.add_argument('--after-user-id', type=int, default=0)
    parser.add_argument('--check', action='store_true', help='Read-only audit of missing identity data')
    parser.add_argument('--refresh-linked', action='store_true', help='Refresh linked accounts from Discord before backfill')
    parser.add_argument('--refresh-limit', type=int, default=100)
    parser.add_argument('--refresh-after-user-id', type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000 or not 1 <= args.refresh_limit <= 1000 or min(args.after_user_id, args.refresh_after_user_id) < 0:
        parser.error('Batch/refresh limits must be 1..1000 and the cursor must be nonnegative')
    if args.server_id is not None and args.server_id <= 0:
        parser.error('--server-id must be positive')
    if args.refresh_linked and (args.server_id is None or args.check):
        parser.error('--refresh-linked requires one --server-id and cannot be used with --check')
    asyncio.run(run(args))

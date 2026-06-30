from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.services.moderation_imports_juniper_attribution import fix_juniper_moderator_attribution
from src.db.database import engine, get_async_session


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fix moderator attribution for imported Juniper warns.")
    parser.add_argument("--server-id", type=int, required=True, help="Discord guild/server ID.")
    parser.add_argument("--run-id", type=UUID, default=None, help="Optional Juniper import run ID to limit updates.")
    parser.add_argument(
        "--moderator-map-json",
        type=Path,
        default=None,
        help="Optional JSON object mapping Juniper issuer handles to Discord user IDs.",
    )
    parser.add_argument(
        "--no-discord-search",
        action="store_true",
        help="Do not query Discord member search; only use --moderator-map-json.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Resolve and summarize without writing updates.")
    return parser


def _load_moderator_map(path: Path | None) -> dict[str, int] | None:
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(key).strip().casefold(): int(value) for key, value in raw.items()}


async def _main() -> None:
    args = _parser().parse_args()
    async with get_async_session() as session:
        summary = await fix_juniper_moderator_attribution(
            session,
            server_id=args.server_id,
            run_id=args.run_id,
            dry_run=args.dry_run,
            moderator_map=_load_moderator_map(args.moderator_map_json),
            use_discord_search=not args.no_discord_search,
        )
        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()
    await engine.dispose()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(_main())

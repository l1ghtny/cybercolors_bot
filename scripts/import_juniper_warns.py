from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.services.moderation_imports_juniper import import_juniper_warns_xlsx
from src.db.database import engine, get_async_session


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import Juniper .warns XLSX export into moderation actions.")
    parser.add_argument("path", type=Path, help="Path to the Juniper warns workbook.")
    parser.add_argument("--server-id", type=int, required=True, help="Discord guild/server ID to import into.")
    parser.add_argument("--started-by-user-id", type=int, default=None, help="Discord user ID recorded as import runner.")
    parser.add_argument(
        "--moderator-map-json",
        type=Path,
        default=None,
        help="Optional JSON object mapping Juniper issuer handles to Discord user IDs.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and summarize without writing actions.")
    return parser


async def _main() -> None:
    args = _parser().parse_args()
    moderator_map = None
    if args.moderator_map_json is not None:
        raw_map = json.loads(args.moderator_map_json.read_text(encoding="utf-8"))
        moderator_map = {str(key).strip().casefold(): int(value) for key, value in raw_map.items()}
    async with get_async_session() as session:
        summary = await import_juniper_warns_xlsx(
            session,
            path=args.path,
            server_id=args.server_id,
            started_by_user_id=args.started_by_user_id,
            dry_run=args.dry_run,
            moderator_map=moderator_map,
        )
        if not args.dry_run:
            await session.commit()
        else:
            await session.rollback()
    await engine.dispose()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(_main())

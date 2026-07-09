import argparse
import asyncio
import logging
import os
from contextlib import asynccontextmanager

import discord
from dotenv import load_dotenv
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import engine
from src.modules.historical_activity_import import (
    HistoricalActivityImportOptions,
    import_historical_activity,
)


@asynccontextmanager
async def session_factory():
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _resolve_token() -> str:
    for key in ("DISCORD_BOT_TOKEN", "DISCORD_TOKEN_TEST", "DISCORD_TOKEN"):
        value = os.getenv(key)
        if value:
            return value
    raise RuntimeError("DISCORD_BOT_TOKEN, DISCORD_TOKEN_TEST, or DISCORD_TOKEN must be set")


def _parse_channel_ids(raw_values: list[str] | None) -> set[int] | None:
    if not raw_values:
        return None
    values: set[int] = set()
    for raw_value in raw_values:
        for token in raw_value.split(","):
            token = token.strip()
            if not token:
                continue
            if not token.isdigit():
                raise ValueError(f"Invalid channel id: {token}")
            values.add(int(token))
    return values or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import historical Discord activity as daily aggregates.")
    parser.add_argument("server_id", type=int, help="Discord guild/server ID to import.")
    parser.add_argument(
        "--channel-id",
        action="append",
        dest="channel_ids",
        help="Limit import to one or more channel IDs. Repeat or pass comma-separated IDs.",
    )
    parser.add_argument("--page-size", type=int, default=100, choices=range(1, 101), metavar="1-100")
    parser.add_argument("--page-sleep-seconds", type=float, default=0.75)
    parser.add_argument("--max-pages-per-channel", type=int, default=None)
    parser.add_argument("--skip-threads", action="store_true", help="Import text channels only, without threads.")
    return parser.parse_args()


async def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.messages = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            stats = await import_historical_activity(
                client=client,
                session_factory=session_factory,
                options=HistoricalActivityImportOptions(
                    server_id=args.server_id,
                    channel_ids=_parse_channel_ids(args.channel_ids),
                    page_size=args.page_size,
                    page_sleep_seconds=max(0.0, args.page_sleep_seconds),
                    max_pages_per_channel=args.max_pages_per_channel,
                    include_threads=not args.skip_threads,
                ),
            )
            logging.info(
                "Historical activity import finished: channels_seen=%s channels_completed=%s pages=%s scanned=%s imported=%s bot_skipped=%s",
                stats.channels_seen,
                stats.channels_completed,
                stats.pages_scanned,
                stats.messages_scanned,
                stats.messages_imported,
                stats.bot_messages_skipped,
            )
        finally:
            await client.close()

    await client.start(_resolve_token())


if __name__ == "__main__":
    asyncio.run(main())

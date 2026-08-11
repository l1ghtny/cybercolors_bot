"""Create and migrate the persistent local PostgreSQL test schema."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.config import (  # noqa: E402
    TEST_DATABASE_ENVIRONMENT_FLAG,
    TEST_DATABASE_SCHEMA,
)


async def _create_schema(database_url: URL) -> None:
    engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(
                f'CREATE SCHEMA IF NOT EXISTS "{TEST_DATABASE_SCHEMA}"'
            )
    finally:
        await engine.dispose()


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    configured_url = os.getenv("DATABASE_URL")
    if not configured_url:
        raise SystemExit("DATABASE_URL is required")

    database_url = make_url(configured_url)
    if not database_url.drivername.startswith("postgresql"):
        raise SystemExit("DATABASE_URL must point to PostgreSQL")

    asyncio.run(_create_schema(database_url))

    migration_environment = os.environ.copy()
    migration_environment["DATABASE_URL"] = database_url.render_as_string(
        hide_password=False
    )
    migration_environment["DB_SCHEMA"] = TEST_DATABASE_SCHEMA
    migration_environment[TEST_DATABASE_ENVIRONMENT_FLAG] = "1"
    migration_environment.setdefault("DB_ECHO", "false")

    adjacent_alembic = Path(sys.executable).with_name("alembic")
    alembic = (
        str(adjacent_alembic)
        if adjacent_alembic.is_file()
        else shutil.which("alembic")
    )
    if alembic is None:
        raise SystemExit("alembic executable was not found")

    completed = subprocess.run(
        [alembic, "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=migration_environment,
        check=False,
    )
    if completed.returncode == 0:
        print(f"Schema {TEST_DATABASE_SCHEMA} is migrated to Alembic head.")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

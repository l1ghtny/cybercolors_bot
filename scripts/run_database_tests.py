"""Run PostgreSQL-backed tests in a disposable schema.

The configured DATABASE_URL is used only as a credential/server template. The
script creates a uniquely named schema, migrates it to Alembic head, runs the
requested pytest arguments, and drops the schema even when tests fail.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _quoted_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _test_schema_name(source_name: str | None) -> str:
    safe_source = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in (source_name or "postgres")
    )
    suffix = uuid4().hex[:10]
    return f"{safe_source[:45]}_test_{suffix}"


async def _database_admin(database_url: URL, statement: str) -> None:
    engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    configured_url = os.getenv("DATABASE_URL")
    if not configured_url:
        raise SystemExit("DATABASE_URL is required")

    source_url = make_url(configured_url)
    if not source_url.drivername.startswith("postgresql"):
        raise SystemExit("DATABASE_URL must point to PostgreSQL")

    test_schema = _test_schema_name(source_url.database)
    quoted_schema = _quoted_identifier(test_schema)
    test_environment = os.environ.copy()
    test_environment["DATABASE_URL"] = source_url.render_as_string(hide_password=False)
    test_environment["DB_SCHEMA"] = test_schema
    test_environment.setdefault("DB_ECHO", "false")
    alembic = shutil.which("alembic")
    if alembic is None:
        raise SystemExit("alembic executable was not found")

    pytest_arguments = sys.argv[1:] or ["tests"]
    print(f"Creating disposable PostgreSQL schema {test_schema}", flush=True)
    asyncio.run(
        _database_admin(
            source_url,
            f"CREATE SCHEMA {quoted_schema}",
        )
    )
    try:
        migration = subprocess.run(
            [alembic, "upgrade", "head"],
            cwd=PROJECT_ROOT,
            env=test_environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if migration.returncode != 0:
            print(migration.stdout, end="")
            print(migration.stderr, end="", file=sys.stderr)
            return migration.returncode
        print("Disposable schema migrated to Alembic head", flush=True)
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", *pytest_arguments],
            cwd=PROJECT_ROOT,
            env=test_environment,
            check=False,
        )
        return completed.returncode
    finally:
        print(f"Dropping disposable PostgreSQL schema {test_schema}", flush=True)
        asyncio.run(
            _database_admin(
                source_url,
                f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE",
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())

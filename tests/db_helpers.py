import pytest


async def ensure_pgvector_or_skip(conn) -> None:
    available = await conn.exec_driver_sql("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    if available.first() is None:
        pytest.skip("Postgres pgvector extension is not installed on this database server.")
    await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")

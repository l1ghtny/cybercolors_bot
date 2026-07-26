import os
import re
from urllib.parse import quote_plus


_POSTGRES_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def get_database_schema() -> str | None:
    schema = (os.getenv("DB_SCHEMA") or "").strip()
    if not schema:
        return None
    if not _POSTGRES_IDENTIFIER_RE.fullmatch(schema):
        raise ValueError("DB_SCHEMA must be a valid unquoted PostgreSQL identifier")
    return schema


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    db_host = os.getenv("DB_HOST")
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_port = os.getenv("DB_PORT", "5432")
    if all([db_host, db_name, db_user, db_password]):
        return (
            "postgresql+asyncpg://"
            f"{quote_plus(db_user)}:{quote_plus(db_password)}"
            f"@{db_host}:{db_port}/{quote_plus(db_name)}"
        )

    raise ValueError("DATABASE_URL or DB_HOST/DB_NAME/DB_USER/DB_PASSWORD environment variables are required")


def get_database_connect_args() -> dict[str, object]:
    """Return optional PostgreSQL session settings shared by app and Alembic."""
    schema = get_database_schema()
    if not schema:
        return {}
    return {"server_settings": {"search_path": schema}}

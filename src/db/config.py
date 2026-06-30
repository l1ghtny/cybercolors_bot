import os
from urllib.parse import quote_plus


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

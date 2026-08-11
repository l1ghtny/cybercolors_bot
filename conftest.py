"""Global pytest bootstrap that isolates every test from the normal schema."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from src.db.config import (
    TEST_DATABASE_ENVIRONMENT_FLAG,
    TEST_DATABASE_SCHEMA,
    require_test_database_schema,
)


PROJECT_ROOT = Path(__file__).resolve().parent

# This runs before pytest imports any test module (and therefore before the
# application creates its module-level SQLAlchemy engine).
load_dotenv(PROJECT_ROOT / ".env")
os.environ[TEST_DATABASE_ENVIRONMENT_FLAG] = "1"
os.environ.setdefault("DB_SCHEMA", TEST_DATABASE_SCHEMA)
os.environ.setdefault("DB_ECHO", "false")
require_test_database_schema(os.environ.get("DB_SCHEMA"))

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.run_database_tests import _test_schema_name
from src.db.config import (
    TEST_DATABASE_ENVIRONMENT_FLAG,
    TEST_DATABASE_SCHEMA,
    get_database_schema,
    is_test_database_schema,
    require_test_database_schema,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pytest_process_uses_reserved_test_schema():
    assert os.environ[TEST_DATABASE_ENVIRONMENT_FLAG] == "1"
    assert is_test_database_schema(get_database_schema())


@pytest.mark.parametrize("schema", [None, "", "public", "cybercolors", "customer_test"])
def test_normal_schemas_are_rejected_for_tests(schema):
    with pytest.raises(RuntimeError, match="refusing to use the normal database schema"):
        require_test_database_schema(schema)


@pytest.mark.parametrize(
    "schema",
    [TEST_DATABASE_SCHEMA, f"{TEST_DATABASE_SCHEMA}_0123456789"],
)
def test_reserved_test_schemas_are_allowed(schema):
    assert require_test_database_schema(schema) == schema


def test_disposable_runner_uses_reserved_test_namespace():
    schema = _test_schema_name()
    assert schema.startswith(f"{TEST_DATABASE_SCHEMA}_")
    assert is_test_database_schema(schema)


def test_tests_do_not_create_database_tables_from_model_metadata():
    forbidden = "metadata." + "create_all"
    offenders = []
    for path in (PROJECT_ROOT / "tests").glob("test_*.py"):
        if path == Path(__file__):
            continue
        if forbidden in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == []

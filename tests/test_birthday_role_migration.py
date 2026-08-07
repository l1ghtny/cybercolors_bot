from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "b5c6d7e8f9a0_add_per_server_birthday_state.py"
)


def test_per_server_birthday_state_migration_backfills_every_membership():
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'down_revision = "a4b5c6d7e8f9"' in migration
    assert '"birthday_greeted_at"' in migration
    assert '"birthday_role_added_at"' in migration
    assert "birthday.user_id = membership.user_id" in migration
    assert "birthday.role_added_at IS NOT NULL" in migration
    assert 'op.drop_column("users", "birthday_role_added_at")' in migration
    assert 'op.drop_column("users", "birthday_greeted_at")' in migration

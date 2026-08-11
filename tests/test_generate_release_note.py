from datetime import UTC, datetime

import pytest

from scripts.generate_release_note import build_migration, validate_note


def _note() -> dict:
    return {
        "id": "2026-08-12-example-change",
        "published_at": datetime(2026, 8, 12, 12, tzinfo=UTC),
        "title_en": "Clear title",
        "title_ru": "Понятный заголовок",
        "summary_en": "The exact user-visible outcome.",
        "summary_ru": "Точный результат для пользователя.",
        "change_type": "improved",
        "surface": "both",
        "feature_en": "Members · Identity",
        "feature_ru": "Участники · Имена",
        "action_label_en": "Open members",
        "action_label_ru": "Открыть участников",
        "action_path": "/dashboard/{server_id}/users",
        "changes": [
            {"en": "One concrete change.", "ru": "Одно конкретное изменение."},
        ],
    }


def test_build_migration_creates_reversible_bilingual_release_note() -> None:
    migration = build_migration(
        revision="abc123def456",
        down_revision="previous1234",
        note=_note(),
    )

    compile(migration, "generated_release_note.py", "exec")
    assert "revision = 'abc123def456'" in migration
    assert "down_revision = 'previous1234'" in migration
    assert "Понятный заголовок" in migration
    assert "/dashboard/{server_id}/users" in migration
    assert "op.inline_literal" in migration
    assert "sa.JSON()" in migration
    assert "table.delete().where(table.c.id == NOTE_ID)" in migration


def test_validate_note_rejects_partial_or_unsafe_actions() -> None:
    note = _note()
    note["action_label_ru"] = None
    with pytest.raises(ValueError, match="supplied together"):
        validate_note(note)

    note = _note()
    note["action_path"] = "https://example.com"
    with pytest.raises(ValueError, match="must stay under"):
        validate_note(note)

from __future__ import annotations

from typing import Any

from src.db.models import ModerationAction, ModerationImportSource, ModerationImportSourceItem

JUNIPER_SOURCE_LABEL = "Juniper"
JUNIPER_UNKNOWN_DATE_NOTE_EN = "Imported from Juniper, date unknown"
JUNIPER_UNKNOWN_DATE_NOTE_RU = "Импортировано из Juniper, дата неизвестна"


def unknown_source_date_note(locale: str | None = None) -> str:
    if (locale or "").strip().lower() == "en":
        return JUNIPER_UNKNOWN_DATE_NOTE_EN
    return JUNIPER_UNKNOWN_DATE_NOTE_RU


def _source_value(item: ModerationImportSourceItem) -> str:
    source = item.source
    return source.value if hasattr(source, "value") else str(source)


def _source_label(source: str) -> str:
    if source == ModerationImportSource.JUNIPER.value:
        return JUNIPER_SOURCE_LABEL
    return source


def _source_created_at_known(item: ModerationImportSourceItem) -> bool:
    payload = item.normalized_payload_json or {}
    if isinstance(payload, dict) and "source_created_at_known" in payload:
        return bool(payload["source_created_at_known"])
    return True


def action_import_metadata(
    action: ModerationAction,
    *,
    locale: str | None = None,
) -> dict[str, Any]:
    items = list(getattr(action, "import_source_items", None) or [])
    if not items:
        return {
            "import_source": None,
            "import_source_label": None,
            "source_created_at_known": True,
            "source_created_at_note": None,
            "created_at_label": None,
        }

    item = sorted(items, key=lambda current: current.created_at)[0]
    source = _source_value(item)
    source_created_at_known = _source_created_at_known(item)
    note = None
    created_at_label = None
    if source == ModerationImportSource.JUNIPER.value and not source_created_at_known:
        note = unknown_source_date_note(locale)
        created_at_label = note

    return {
        "import_source": source,
        "import_source_label": _source_label(source),
        "source_created_at_known": source_created_at_known,
        "source_created_at_note": note,
        "created_at_label": created_at_label,
    }

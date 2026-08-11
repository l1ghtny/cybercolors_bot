#!/usr/bin/env python3
"""Generate a validated Alembic migration for one product release note."""

from __future__ import annotations

import argparse
import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = ROOT / "alembic" / "versions"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _nonempty(value: str, label: str, maximum: int | None = None) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} must not be empty")
    if maximum is not None and len(cleaned) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters")
    return cleaned


def validate_note(note: dict) -> None:
    _nonempty(note["id"], "id", 128)
    _nonempty(note["title_en"], "title_en", 200)
    _nonempty(note["title_ru"], "title_ru", 200)
    _nonempty(note["summary_en"], "summary_en")
    _nonempty(note["summary_ru"], "summary_ru")
    _nonempty(note["feature_en"], "feature_en", 100)
    _nonempty(note["feature_ru"], "feature_ru", 100)
    if note["change_type"] not in {"added", "fixed", "improved"}:
        raise ValueError("change_type must be added, fixed, or improved")
    if note["surface"] not in {"dashboard", "bot", "both"}:
        raise ValueError("surface must be dashboard, bot, or both")
    if not note["changes"]:
        raise ValueError("at least one bilingual change is required")
    for index, change in enumerate(note["changes"], start=1):
        _nonempty(change["en"], f"change {index} English text")
        _nonempty(change["ru"], f"change {index} Russian text")

    action_values = (
        note["action_label_en"],
        note["action_label_ru"],
        note["action_path"],
    )
    if any(action_values) and not all(action_values):
        raise ValueError("action label translations and path must be supplied together")
    if note["action_label_en"]:
        _nonempty(note["action_label_en"], "action_label_en", 120)
        _nonempty(note["action_label_ru"], "action_label_ru", 120)
        path = _nonempty(note["action_path"], "action_path", 300)
        if not path.startswith("/dashboard/{server_id}/"):
            raise ValueError("action_path must stay under /dashboard/{server_id}/")


def build_migration(*, revision: str, down_revision: str, note: dict) -> str:
    validate_note(note)
    published_at: datetime = note["published_at"]
    changes_json = json.dumps(note["changes"], ensure_ascii=False)
    return f'''"""Add product release note {note["id"]}.

Revision ID: {revision}
Revises: {down_revision}
Create Date: {datetime.now(UTC).isoformat()}
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = {revision!r}
down_revision = {down_revision!r}
branch_labels = None
depends_on = None


NOTE_ID = {note["id"]!r}


def _release_notes_table() -> sa.TableClause:
    return sa.table(
        "product_release_notes",
        sa.column("id", sa.String),
        sa.column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.column("title_en", sa.String),
        sa.column("title_ru", sa.String),
        sa.column("summary_en", sa.Text),
        sa.column("summary_ru", sa.Text),
        sa.column("change_type", sa.String),
        sa.column("surface", sa.String),
        sa.column("feature_en", sa.String),
        sa.column("feature_ru", sa.String),
        sa.column("action_label_en", sa.String),
        sa.column("action_label_ru", sa.String),
        sa.column("action_path", sa.String),
        sa.column("changes", sa.JSON),
        sa.column("is_published", sa.Boolean),
    )


def upgrade() -> None:
    table = _release_notes_table()
    op.get_bind().execute(
        table.insert().values(
            id=NOTE_ID,
            published_at=datetime(
                {published_at.year}, {published_at.month}, {published_at.day},
                {published_at.hour}, {published_at.minute}, {published_at.second},
                tzinfo=timezone.utc,
            ),
            title_en={note["title_en"]!r},
            title_ru={note["title_ru"]!r},
            summary_en={note["summary_en"]!r},
            summary_ru={note["summary_ru"]!r},
            change_type={note["change_type"]!r},
            surface={note["surface"]!r},
            feature_en={note["feature_en"]!r},
            feature_ru={note["feature_ru"]!r},
            action_label_en={note["action_label_en"]!r},
            action_label_ru={note["action_label_ru"]!r},
            action_path={note["action_path"]!r},
            changes=sa.cast(
                op.inline_literal({changes_json!r}, type_=sa.Text()),
                sa.JSON(),
            ),
            is_published=True,
        )
    )


def downgrade() -> None:
    table = _release_notes_table()
    op.get_bind().execute(table.delete().where(table.c.id == NOTE_ID))
'''


def _single_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise ValueError(f"expected one Alembic head, found: {', '.join(heads)}")
    return heads[0]


def _published_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--published-at", default=datetime.now(UTC).isoformat())
    parser.add_argument("--change-type", required=True, choices=("added", "fixed", "improved"))
    parser.add_argument("--surface", required=True, choices=("dashboard", "bot", "both"))
    parser.add_argument("--feature-en", required=True)
    parser.add_argument("--feature-ru", required=True)
    parser.add_argument("--title-en", required=True)
    parser.add_argument("--title-ru", required=True)
    parser.add_argument("--summary-en", required=True)
    parser.add_argument("--summary-ru", required=True)
    parser.add_argument("--change-en", action="append", required=True)
    parser.add_argument("--change-ru", action="append", required=True)
    parser.add_argument("--action-label-en")
    parser.add_argument("--action-label-ru")
    parser.add_argument("--action-path")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not SLUG_RE.fullmatch(args.slug):
        raise ValueError("slug must contain lowercase letters, numbers, and single hyphens")
    if len(args.change_en) != len(args.change_ru):
        raise ValueError("--change-en and --change-ru must be supplied in matching pairs")

    published_at = _published_at(args.published_at)
    note_id = f"{published_at:%Y-%m-%d}-{args.slug}"
    note = {
        "id": note_id,
        "published_at": published_at,
        "title_en": args.title_en,
        "title_ru": args.title_ru,
        "summary_en": args.summary_en,
        "summary_ru": args.summary_ru,
        "change_type": args.change_type,
        "surface": args.surface,
        "feature_en": args.feature_en,
        "feature_ru": args.feature_ru,
        "action_label_en": args.action_label_en,
        "action_label_ru": args.action_label_ru,
        "action_path": args.action_path,
        "changes": [
            {"en": english, "ru": russian}
            for english, russian in zip(args.change_en, args.change_ru, strict=True)
        ],
    }
    validate_note(note)
    if any(note_id in path.read_text(encoding="utf-8") for path in VERSIONS_DIR.glob("*.py")):
        raise ValueError(f"release note id already exists: {note_id}")

    revision = secrets.token_hex(6)
    down_revision = _single_head()
    content = build_migration(revision=revision, down_revision=down_revision, note=note)
    destination = VERSIONS_DIR / f"{revision}_add_{args.slug.replace('-', '_')}_release_note.py"
    if args.dry_run:
        print(destination)
        print(content)
        return 0
    destination.write_text(content, encoding="utf-8")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

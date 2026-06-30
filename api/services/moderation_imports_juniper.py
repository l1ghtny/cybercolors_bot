from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.moderation_import_metadata import unknown_source_date_note
from api.services.moderation_imports_service import (
    IMPORT_SYSTEM_USER_ID,
    ImportedModerationActionPayload,
    create_import_run,
    finish_import_run,
    import_moderation_action,
    record_skipped_source_item,
)
from src.db.models import ActionType, ModerationImportConfidence, ModerationImportSource

XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
ID_RE = re.compile(r"^\d{17,20}$")
DIGIT_RE = re.compile(r"[1-9]")
EXPECTED_HEADERS = ("Хэндл", "ID", "Варн", "Выдан")


@dataclass(frozen=True)
class JuniperWarnRow:
    row_number: int
    handle: str
    user_id: int
    warn_text: str
    issuer_handle: str | None
    rule_codes: tuple[str, ...]


def _cell_column(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    value = 0
    for char in letters:
        value = value * 26 + (ord(char.upper()) - ord("A") + 1)
    return value


def _shared_strings(zip_file: ZipFile) -> list[str]:
    try:
        payload = zip_file.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(payload)
    values: list[str] = []
    for item in root.findall(f"{{{XLSX_MAIN_NS}}}si"):
        parts = [node.text or "" for node in item.findall(f".//{{{XLSX_MAIN_NS}}}t")]
        values.append("".join(parts))
    return values


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        parts = [node.text or "" for node in cell.findall(f".//{{{XLSX_MAIN_NS}}}t")]
        return "".join(parts).strip()

    value_node = cell.find(f"{{{XLSX_MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return None

    raw_value = value_node.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)].strip()
        except (IndexError, ValueError):
            return raw_value
    return raw_value


def _read_first_sheet_rows(path: Path) -> list[tuple[int, list[str | None]]]:
    with ZipFile(path) as zip_file:
        shared_strings = _shared_strings(zip_file)
        sheet_payload = zip_file.read("xl/worksheets/sheet1.xml")

    root = ET.fromstring(sheet_payload)
    rows: list[tuple[int, list[str | None]]] = []
    for row in root.findall(f".//{{{XLSX_MAIN_NS}}}row"):
        row_number = int(row.attrib.get("r", "0") or "0")
        cells: dict[int, str | None] = {}
        for cell in row.findall(f"{{{XLSX_MAIN_NS}}}c"):
            cell_ref = cell.attrib.get("r", "")
            if not cell_ref:
                continue
            cells[_cell_column(cell_ref)] = _cell_value(cell, shared_strings)
        max_column = max(cells.keys(), default=0)
        rows.append((row_number, [cells.get(index) for index in range(1, max_column + 1)]))
    return rows


def _clean_cell(value: str | None) -> str:
    return (value or "").strip()


def _normalize_discord_id(raw_value: str) -> str:
    value = raw_value.strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value


def _rule_codes(warn_text: str) -> tuple[str, ...]:
    seen: set[str] = set()
    codes: list[str] = []
    for match in DIGIT_RE.finditer(warn_text):
        code = match.group(0)
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return tuple(codes)


def parse_juniper_warns_xlsx(path: str | Path) -> tuple[list[JuniperWarnRow], list[dict]]:
    rows = _read_first_sheet_rows(Path(path))
    if not rows:
        return [], [{"row": None, "error": "empty workbook"}]

    header = tuple(_clean_cell(value) for value in rows[0][1][:4])
    errors: list[dict] = []
    if header != EXPECTED_HEADERS:
        errors.append({"row": rows[0][0], "error": f"unexpected header: {header}"})

    parsed: list[JuniperWarnRow] = []
    for row_number, values in rows[1:]:
        padded = [*(values[:4]), None, None, None, None][:4]
        handle = _clean_cell(padded[0])
        raw_user_id = _normalize_discord_id(_clean_cell(padded[1]))
        warn_text = _clean_cell(padded[2])
        issuer_handle = _clean_cell(padded[3]) or None

        if not any((handle, raw_user_id, warn_text, issuer_handle)):
            continue
        row_errors = []
        if not ID_RE.match(raw_user_id):
            row_errors.append("invalid user id")
        if not warn_text:
            row_errors.append("missing warning text")
        if row_errors:
            errors.append({"row": row_number, "error": ", ".join(row_errors), "raw": values})
            continue

        parsed.append(
            JuniperWarnRow(
                row_number=row_number,
                handle=handle or raw_user_id,
                user_id=int(raw_user_id),
                warn_text=warn_text,
                issuer_handle=issuer_handle,
                rule_codes=_rule_codes(warn_text),
            )
        )
    return parsed, errors


def _moderator_id_by_handle(issuer_handle: str | None, moderator_map: dict[str, int] | None) -> int | None:
    if not issuer_handle:
        return None
    if not moderator_map:
        return None
    return moderator_map.get(issuer_handle.strip().casefold())


async def import_juniper_warns_xlsx(
    session: AsyncSession,
    *,
    path: str | Path,
    server_id: int,
    started_by_user_id: int | None = None,
    dry_run: bool = False,
    moderator_map: dict[str, int] | None = None,
) -> dict:
    rows, parse_errors = parse_juniper_warns_xlsx(path)
    run = await create_import_run(
        session,
        server_id=server_id,
        source=ModerationImportSource.JUNIPER,
        started_by_user_id=started_by_user_id,
        dry_run=dry_run,
    )
    summary = {
        "rows": len(rows),
        "parse_errors": len(parse_errors),
        "imported": 0,
        "skipped": 0,
        "duplicates": 0,
        "missing_issuer": 0,
        "unmapped_issuer": 0,
        "manual_review": len(parse_errors),
        "dry_run": dry_run,
        "source_created_at_note": unknown_source_date_note(),
        "parse_error_details": parse_errors[:20],
    }

    try:
        for row in rows:
            raw_payload = {
                "sheet": "Лист1",
                "row_number": row.row_number,
                "handle": row.handle,
                "user_id": str(row.user_id),
                "warn_text": row.warn_text,
                "issuer_handle": row.issuer_handle,
            }
            moderator_user_id = _moderator_id_by_handle(row.issuer_handle, moderator_map)
            confidence = ModerationImportConfidence.PARSED
            if row.issuer_handle is None:
                summary["missing_issuer"] += 1
                confidence = ModerationImportConfidence.MANUAL_REVIEW
            elif moderator_user_id is None:
                summary["unmapped_issuer"] += 1
                confidence = ModerationImportConfidence.INFERRED

            commentary_parts = [
                unknown_source_date_note(),
            ]
            if row.issuer_handle:
                commentary_parts.append(f"Выдал(а) в Juniper: {row.issuer_handle}.")
            if moderator_user_id is None:
                commentary_parts.append("Discord ID модератора не найден при импорте.")

            payload = ImportedModerationActionPayload(
                source=ModerationImportSource.JUNIPER,
                source_item_type="juniper_warns_xlsx",
                source_item_id=f"Лист1:{row.row_number}",
                server_id=server_id,
                action_type=ActionType.WARN,
                target_user_id=row.user_id,
                target_username=row.handle,
                moderator_user_id=moderator_user_id,
                moderator_username=row.issuer_handle,
                reason=row.warn_text,
                rule_codes=row.rule_codes,
                commentary=" ".join(commentary_parts),
                created_at=None,
                is_active=True,
                confidence=confidence,
                raw_payload=raw_payload,
            )
            result = await import_moderation_action(session, run, payload)
            if result.imported:
                summary["imported"] += 1
            elif result.reason == "duplicate":
                summary["duplicates"] += 1
                summary["skipped"] += 1
            else:
                summary["skipped"] += 1

        for error in parse_errors:
            result = await record_skipped_source_item(
                session,
                run,
                source_item_type="juniper_warns_xlsx_parse_error",
                source_item_id=f"Лист1:{error.get('row')}",
                raw_payload=error,
                reason=error["error"],
                confidence=ModerationImportConfidence.MANUAL_REVIEW,
            )
            if result.reason == "duplicate":
                summary["duplicates"] += 1
            else:
                summary["skipped"] += 1

        summary["manual_review"] = (
            summary["parse_errors"]
            + summary["missing_issuer"]
            + summary["unmapped_issuer"]
        )
        await finish_import_run(session, run, summary=summary)
        return {"run_id": str(run.id), **summary}
    except Exception as exc:
        await finish_import_run(session, run, summary=summary, error_message=str(exc))
        raise

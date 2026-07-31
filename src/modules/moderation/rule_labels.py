from __future__ import annotations

from src.modules.localization.service import tr


def _normalize_rule_label_part(value: str) -> str:
    return " ".join(value.casefold().replace("\ufe0f", "").replace("\u20e3", "").split()).strip(" :.-")


def _rule_title_starts_with_label(normalized_title: str, normalized_label: str) -> bool:
    if not normalized_title or not normalized_label:
        return False
    return normalized_title == normalized_label or normalized_title.startswith(
        (f"{normalized_label} ", f"{normalized_label}:", f"{normalized_label}.", f"{normalized_label}-")
    )


def format_rule_label(
    code: str | None,
    title: str | None,
    *,
    locale: str | None = None,
    localize_numeric_code: bool = False,
) -> str:
    """Format a rule once, even when its stored title already contains its code."""
    code = (code or "").strip()
    title = (title or "").strip()
    if not code:
        return title or tr(locale, "common.rule_fallback")

    normalized_title = _normalize_rule_label_part(title)
    normalized_code = _normalize_rule_label_part(code)
    if _rule_title_starts_with_label(normalized_title, normalized_code):
        return title

    if code.isdigit():
        keycap_code = "".join(f"{digit}\ufe0f\u20e3" for digit in code)
        # Imported titles may have been created in a different server locale.
        # Recognize both supported prefixes before adding the current one.
        localized_labels = {
            _normalize_rule_label_part(f"{tr(candidate_locale, 'modlog.rule_label')} {keycap_code}")
            for candidate_locale in (locale, "en", "ru")
        }
        if any(_rule_title_starts_with_label(normalized_title, label) for label in localized_labels):
            return title
        if localize_numeric_code:
            return f"{tr(locale, 'modlog.rule_label')} {keycap_code}: {title}".strip(": ")

    return f"{code} {title}".strip()

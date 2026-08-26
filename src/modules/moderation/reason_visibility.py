LEGACY_COMMENTARY_MARKERS = ("\nCommentary:", "\nКомментарий:")


def strip_legacy_commentary_suffix(reason: str | None) -> str:
    """Remove importer-era private commentary appended to a public reason."""
    display_reason = (reason or "").strip()
    marker_index = max(
        (display_reason.rfind(marker) for marker in LEGACY_COMMENTARY_MARKERS),
        default=-1,
    )
    if marker_index >= 0:
        return display_reason[:marker_index].rstrip()
    return display_reason

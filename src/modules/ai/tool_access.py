from collections.abc import Iterable


AI_COMPANION_TOOL_NAMES: tuple[str, ...] = (
    "get_available_commands",
    "get_active_rules",
    "get_member_profile",
    "get_server_activity",
    "search_server_knowledge",
    "search_youtube_channel_catalog",
    "web_search",
)
AI_COMPANION_TOOL_NAME_SET = frozenset(AI_COMPANION_TOOL_NAMES)


def default_ai_companion_tool_names() -> list[str]:
    return list(AI_COMPANION_TOOL_NAMES)


def normalize_ai_companion_tool_names(
    values: Iterable[str],
    *,
    reject_unknown: bool = True,
) -> list[str]:
    requested = {str(value) for value in values}
    unknown = sorted(requested - AI_COMPANION_TOOL_NAME_SET)
    if unknown and reject_unknown:
        raise ValueError(f"Unknown AI companion tools: {', '.join(unknown)}")
    return [name for name in AI_COMPANION_TOOL_NAMES if name in requested]

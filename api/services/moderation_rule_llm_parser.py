import json
import os
import re
from typing import Any

from api.services.moderation_rules_service_types import ParsedRule


RULE_IMPORT_SYSTEM_PROMPT = """
You parse Discord server rules from a copied Discord message.
Return JSON only, with this shape:
{"rules":[{"marker": string|null, "code": string|null, "title": string, "description": string|null, "sort_order": number}]}

Rules:
- Preserve Discord custom emoji tokens like <:rule_1:123> in marker or description when they are part of the rule.
- Preserve visible emoji number markers such as 1️⃣ or 🔟 in marker.
- Use code for the human rule number when it is clear, including 10 for 🔟 or custom emoji names containing ten.
- Keep descriptions faithful to the source text. Do not invent or rewrite policy meaning.
- Split multiple rules even when they are in one paragraph or one Discord message.
- Ignore non-rule headings, greetings, channel mentions, and commentary.
""".strip()


def _llm_rules_enabled() -> bool:
    raw_value = os.getenv("RULE_IMPORT_LLM_ENABLED", "true").strip().lower()
    return raw_value not in {"0", "false", "no", "off"} and bool(os.getenv("OPENAI_API_KEY"))


def _rules_model() -> str:
    return os.getenv("RULE_IMPORT_LLM_MODEL") or os.getenv("AI_MODEL") or "gpt-5.4-nano"


def _extract_json_object(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parsed_rules_from_llm_json(content: str) -> list[ParsedRule]:
    payload = _extract_json_object(content)
    if payload is None:
        return []
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list):
        return []

    parsed: list[ParsedRule] = []
    for index, item in enumerate(raw_rules, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        description_value = item.get("description")
        description = str(description_value).strip() if description_value is not None else None
        if description == "":
            description = None
        marker_value = item.get("marker")
        code_value = item.get("code")
        marker = str(marker_value).strip() if marker_value is not None else None
        code = str(code_value).strip() if code_value is not None else None
        if marker == "":
            marker = None
        if code == "":
            code = None
        raw_sort_order = item.get("sort_order")
        sort_order = int(raw_sort_order) if isinstance(raw_sort_order, int | float) else index
        parsed.append(
            ParsedRule(
                marker=marker,
                code=code,
                title=title[:500],
                description=description,
                sort_order=max(1, sort_order),
            )
        )
    parsed.sort(key=lambda rule: rule.sort_order)
    for index, item in enumerate(parsed, start=1):
        item.sort_order = index
    return parsed


async def parse_rules_from_text_with_llm(
    text: str,
    *,
    fallback_rules: list[ParsedRule],
    provider: Any | None = None,
) -> list[ParsedRule]:
    if not text.strip() or not _llm_rules_enabled():
        return fallback_rules

    from src.modules.ai.models import AIMessage, AIRequest
    from src.modules.ai.providers import AIProviderError, OpenAIProvider

    active_provider = provider or OpenAIProvider()
    request = AIRequest(
        task="assistant",
        model=_rules_model(),
        system_prompt=RULE_IMPORT_SYSTEM_PROMPT,
        messages=[
            AIMessage(
                role="user",
                content=(
                    "Parse this Discord rules message into the required JSON shape.\n\n"
                    f"{text}"
                ),
            )
        ],
        max_output_tokens=2500,
        metadata={"task": "moderation_rule_import_parse"},
    )
    try:
        response = await active_provider.complete(request)
    except (AIProviderError, RuntimeError, ValueError):
        return fallback_rules

    llm_rules = parsed_rules_from_llm_json(response.content or "")
    if not llm_rules:
        return fallback_rules
    if len(fallback_rules) > 1 and len(llm_rules) < len(fallback_rules):
        return fallback_rules
    return llm_rules

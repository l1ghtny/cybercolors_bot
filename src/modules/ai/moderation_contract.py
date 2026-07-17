from __future__ import annotations

import re
from dataclasses import replace

from src.modules.ai.models import AIResponseFormat, MessageModerationInput, ModerationVerdict


MODERATION_CATEGORIES = (
    "harassment",
    "hate_or_slur",
    "credible_threat",
    "self_harm",
    "sexual_explicit",
    "spam",
    "scam_or_phishing",
    "malware",
    "privacy_or_doxxing",
    "moderation_evasion",
    "other",
)
MODERATION_CATEGORY_SET = frozenset(MODERATION_CATEGORIES)
MODERATION_SEVERITIES = ("none", "low", "medium", "high")
MODERATION_ACTIONS = ("none", "watch", "warn", "mute", "kick", "ban", "manual_review")
MODERATION_EVIDENCE_SOURCES = ("none", "text", "visual", "link", "context", "mixed")
MODERATION_CONTEXT_TYPES = (
    "none",
    "banter",
    "sarcasm",
    "quote",
    "fiction",
    "roleplay",
    "game",
    "moderation_meta",
    "uncertain",
)
VISUAL_SEXUAL_LEVELS = ("none", "suggestive", "explicit", "uncertain")
MODERATION_CONFIDENCE_THRESHOLDS = {
    "low": 0.90,
    "standard": 0.75,
    "high": 0.55,
}

URL_PATTERN = re.compile(r"https?://[^\s<>|]+", re.IGNORECASE)
LINK_ONLY_TOKEN_PATTERN = re.compile(r"^<?https?://[^\s<>|]+>?$", re.IGNORECASE)

MODERATION_RESPONSE_FORMAT = AIResponseFormat(
    name="cybercolors_moderation_verdict",
    description="A schema-constrained Discord moderation assessment.",
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "flagged": {"type": "boolean"},
            "severity": {"type": "string", "enum": list(MODERATION_SEVERITIES)},
            "categories": {
                "type": "array",
                "items": {"type": "string", "enum": list(MODERATION_CATEGORIES)},
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Confidence that the overall flagged or unflagged decision is correct.",
            },
            "reason": {"type": "string"},
            "suggested_action": {"type": "string", "enum": list(MODERATION_ACTIONS)},
            "rule_ids": {"type": "array", "items": {"type": "string"}},
            "targeted": {"type": "boolean"},
            "credible_threat": {"type": "boolean"},
            "credible_self_harm": {"type": "boolean"},
            "link_content_inspected": {"type": "boolean"},
            "is_banter_or_hyperbole": {"type": "boolean"},
            "requires_context": {"type": "boolean"},
            "repeated_behavior_evidence": {"type": "boolean"},
            "evidence_source": {
                "type": "string",
                "enum": list(MODERATION_EVIDENCE_SOURCES),
            },
            "context_type": {
                "type": "string",
                "enum": list(MODERATION_CONTEXT_TYPES),
            },
            "visual_sexual_level": {
                "type": "string",
                "enum": list(VISUAL_SEXUAL_LEVELS),
            },
        },
        "required": [
            "flagged",
            "severity",
            "categories",
            "confidence",
            "reason",
            "suggested_action",
            "rule_ids",
            "targeted",
            "credible_threat",
            "credible_self_harm",
            "link_content_inspected",
            "is_banter_or_hyperbole",
            "requires_context",
            "repeated_behavior_evidence",
            "evidence_source",
            "context_type",
            "visual_sexual_level",
        ],
    },
)


def apply_moderation_policy(
    verdict: ModerationVerdict,
    *,
    strictness: str,
    moderation_input: MessageModerationInput | None,
) -> ModerationVerdict:
    if not verdict.flagged:
        return _normalize_unflagged(verdict)

    normalized_strictness = strictness if strictness in MODERATION_CONFIDENCE_THRESHOLDS else "standard"
    categories = list(dict.fromkeys(item for item in verdict.categories if item in MODERATION_CATEGORY_SET))
    original_categories = list(categories)
    policy_notes: list[str] = []

    threshold = MODERATION_CONFIDENCE_THRESHOLDS[normalized_strictness]
    if verdict.confidence < threshold:
        categories.clear()
        policy_notes.append(
            f"Confidence {verdict.confidence:.2f} is below the {normalized_strictness} threshold {threshold:.2f}."
        )

    if verdict.requires_context and normalized_strictness != "high":
        categories.clear()
        policy_notes.append("The model requires more context before the message is actionable.")

    _remove_category_unless(
        categories,
        "harassment",
        verdict.targeted,
        policy_notes,
        "Harassment requires a clear target.",
    )
    _remove_category_unless(
        categories,
        "credible_threat",
        verdict.credible_threat,
        policy_notes,
        "Threat moderation requires the model to affirm credible intent.",
    )
    _remove_category_unless(
        categories,
        "self_harm",
        verdict.credible_self_harm,
        policy_notes,
        "Self-harm moderation requires the model to affirm credible self-harm content.",
    )

    if verdict.is_banter_or_hyperbole or verdict.context_type in {
        "banter",
        "sarcasm",
        "quote",
        "fiction",
        "roleplay",
        "game",
    }:
        if not verdict.targeted:
            _remove_categories(
                categories,
                {"harassment"},
                policy_notes,
                "Non-targeted banter, quoted speech, fiction, roleplay, or game context is not harassment.",
            )
        if not verdict.credible_threat:
            _remove_categories(
                categories,
                {"credible_threat"},
                policy_notes,
                "Non-credible threat language in banter, quoted speech, fiction, roleplay, or game context is not actionable.",
            )

    if "sexual_explicit" in categories:
        visual_evidence = verdict.evidence_source in {"visual", "mixed"}
        uninspected_link_evidence = verdict.evidence_source == "link" and not verdict.link_content_inspected
        if visual_evidence and verdict.visual_sexual_level != "explicit":
            _remove_categories(
                categories,
                {"sexual_explicit"},
                policy_notes,
                "Visual sexual content requires the structured visual level to be explicit.",
            )
        elif uninspected_link_evidence:
            _remove_categories(
                categories,
                {"sexual_explicit"},
                policy_notes,
                "Uninspected link content cannot establish explicit sexual content.",
            )

    if moderation_input is not None:
        if (
            _is_link_only_message(moderation_input)
            and verdict.evidence_source == "link"
            and not verdict.link_content_inspected
        ):
            categories.clear()
            policy_notes.append("An uninspected link-only message has no actionable content evidence.")

        if (
            (moderation_input.author_is_admin or moderation_input.author_is_moderator)
            and URL_PATTERN.search(moderation_input.content)
        ):
            _remove_categories(
                categories,
                {"spam"},
                policy_notes,
                "Trusted staff resource links are not spam without another canonical violation.",
            )

    if not categories:
        return _suppress_verdict(verdict, policy_notes)

    suggested_action = verdict.suggested_action
    if suggested_action == "watch" and not verdict.repeated_behavior_evidence:
        suggested_action = "manual_review"
        policy_notes.append("Watch requires structured evidence of repeated or ongoing behavior.")

    categories_changed = categories != original_categories
    return replace(
        verdict,
        flagged=True,
        severity="low" if verdict.severity == "none" else verdict.severity,
        categories=categories,
        suggested_action=suggested_action,
        rule_ids=[] if categories_changed else verdict.rule_ids,
        reason=_reason_with_policy_notes(verdict.reason, policy_notes),
    )


def _normalize_unflagged(verdict: ModerationVerdict) -> ModerationVerdict:
    return replace(
        verdict,
        flagged=False,
        severity="none",
        categories=[],
        suggested_action="none",
        rule_ids=[],
    )


def _suppress_verdict(verdict: ModerationVerdict, policy_notes: list[str]) -> ModerationVerdict:
    notes = policy_notes or ["The structured verdict did not contain an actionable canonical category."]
    return replace(
        verdict,
        flagged=False,
        severity="none",
        categories=[],
        reason=_reason_with_policy_notes(verdict.reason, notes),
        suggested_action="none",
        rule_ids=[],
    )


def _reason_with_policy_notes(reason: str, policy_notes: list[str]) -> str:
    if not policy_notes:
        return reason
    policy_reason = " ".join(dict.fromkeys(policy_notes))
    cleaned_reason = reason.strip()
    return f"{policy_reason} Original AI reason: {cleaned_reason}" if cleaned_reason else policy_reason


def _remove_category_unless(
    categories: list[str],
    category: str,
    condition: bool,
    policy_notes: list[str],
    note: str,
) -> None:
    if condition:
        return
    _remove_categories(categories, {category}, policy_notes, note)


def _remove_categories(
    categories: list[str],
    disallowed: set[str],
    policy_notes: list[str],
    note: str,
) -> None:
    retained = [item for item in categories if item not in disallowed]
    if len(retained) == len(categories):
        return
    categories[:] = retained
    policy_notes.append(note)


def _is_link_only_message(moderation_input: MessageModerationInput) -> bool:
    if moderation_input.images:
        return False
    content = moderation_input.content.strip()
    if not content:
        return False
    tokens = [token.strip("<>|()[]") for token in content.split() if token.strip("|<>")]
    return bool(tokens) and all(LINK_ONLY_TOKEN_PATTERN.fullmatch(token) for token in tokens)

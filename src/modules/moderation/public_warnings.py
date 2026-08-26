from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import ActionType, ModerationAction, ModerationActionRuleCitation
from src.modules.moderation.rule_labels import format_rule_label
from src.modules.moderation.reason_visibility import strip_legacy_commentary_suffix


@dataclass(frozen=True, slots=True)
class PublicWarning:
    """Warning data that is safe to expose in a public Discord response."""

    created_at: datetime
    rule_labels: tuple[str, ...]
    reason: str | None


def _public_text_variants(value: str) -> set[str]:
    normalized = " ".join(
        value.casefold()
        .replace("\ufe0f", "")
        .replace("\u20e3", "")
        .replace(":", " ")
        .split()
    )
    variants = {normalized} if normalized else set()
    for prefix in ("rule ", "правило "):
        if normalized.startswith(prefix):
            variants.add(normalized[len(prefix) :].strip())
    return variants


def _public_reason(action: ModerationAction, rule_labels: tuple[str, ...]) -> str | None:
    reason = strip_legacy_commentary_suffix(action.reason)
    if not reason:
        return None

    reason_variants = _public_text_variants(reason)
    rule_variants = {
        variant
        for label in rule_labels
        for variant in _public_text_variants(label)
    }
    return None if reason_variants & rule_variants else reason


def _public_rule_labels(action: ModerationAction, locale: str | None) -> tuple[str, ...]:
    if action.rule_citations:
        citations = sorted(
            action.rule_citations,
            key=lambda item: (
                item.cited_at or datetime.min.replace(tzinfo=timezone.utc),
                str(item.id),
            ),
        )
        return tuple(
            format_rule_label(
                citation.rule.code if citation.rule is not None else citation.rule_code_snapshot,
                citation.rule.title if citation.rule is not None else citation.rule_title_snapshot,
                locale=locale,
                localize_numeric_code=True,
            )
            for citation in citations
        )
    if action.rule is not None:
        return (
            format_rule_label(
                action.rule.code,
                action.rule.title,
                locale=locale,
                localize_numeric_code=True,
            ),
        )
    return ()


async def list_active_public_warnings(
    session: AsyncSession,
    *,
    server_id: int,
    user_id: int,
    locale: str | None = None,
    limit: int = 10,
) -> tuple[list[PublicWarning], int]:
    filters = (
        ModerationAction.server_id == server_id,
        ModerationAction.target_user_id == user_id,
        ModerationAction.action_type == ActionType.WARN,
        ModerationAction.is_active.is_(True),
    )
    total = int(
        (
            await session.exec(
                select(func.count()).select_from(ModerationAction).where(*filters)
            )
        ).one()
        or 0
    )
    actions = (
        await session.exec(
            select(ModerationAction)
            .where(*filters)
            .options(
                selectinload(ModerationAction.rule),
                selectinload(ModerationAction.rule_citations).selectinload(
                    ModerationActionRuleCitation.rule
                ),
            )
            .order_by(ModerationAction.created_at.desc())
            .limit(limit)
        )
    ).all()
    warnings = []
    for action in actions:
        rule_labels = _public_rule_labels(action, locale)
        warnings.append(
            PublicWarning(
                created_at=action.created_at,
                rule_labels=rule_labels,
                reason=_public_reason(action, rule_labels),
            )
        )
    return warnings, total

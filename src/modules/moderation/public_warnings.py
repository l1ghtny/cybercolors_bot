from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import ActionType, ModerationAction, ModerationActionRuleCitation
from src.modules.localization.service import tr
from src.modules.moderation.rule_labels import format_rule_label


@dataclass(frozen=True, slots=True)
class PublicWarning:
    """Warning data that is safe to expose in a public Discord response."""

    created_at: datetime
    rule_labels: tuple[str, ...]


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
    return (tr(locale, "warns.rule_unavailable"),)


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
    return [
        PublicWarning(
            created_at=action.created_at,
            rule_labels=_public_rule_labels(action, locale),
        )
        for action in actions
    ], total

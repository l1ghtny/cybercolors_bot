from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import ModerationAction, ModerationActionCounter


async def allocate_moderation_action_number(
    session: AsyncSession,
    server_id: int,
) -> int:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.exec(
            sa.text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('moderation_action_number:' || CAST(:server_id AS text), 0)"
                ")"
            ),
            params={"server_id": str(server_id)},
        )

    counter = await session.get(
        ModerationActionCounter,
        server_id,
        with_for_update=True,
    )
    if counter is None:
        current_max = (
            await session.exec(
                select(func.max(ModerationAction.action_number)).where(
                    ModerationAction.server_id == server_id
                )
            )
        ).one()
        next_number = int(current_max or 0) + 1
        counter = ModerationActionCounter(
            server_id=server_id,
            last_number=next_number,
        )
    else:
        counter.last_number += 1
        next_number = counter.last_number

    session.add(counter)
    await session.flush()
    return next_number


async def resolve_moderation_action_reference(
    session: AsyncSession,
    *,
    server_id: int,
    reference: str,
) -> ModerationAction | None:
    normalized = str(reference).strip().removeprefix("#")
    if normalized.isdigit():
        return (
            await session.exec(
                select(ModerationAction).where(
                    ModerationAction.server_id == server_id,
                    ModerationAction.action_number == int(normalized),
                )
            )
        ).first()

    try:
        action_id = UUID(normalized)
    except ValueError:
        return None
    action = await session.get(ModerationAction, action_id)
    if action is None or action.server_id != server_id:
        return None
    return action

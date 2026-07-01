import asyncio
from uuid import uuid4

from sqlmodel import select

from api.services.moderation_rule_sync_state import ModerationRuleSyncState, ModerationRuleSyncStatus
from api.services.moderation_rules_service import (
    import_rules,
    parse_rules_from_text,
    sync_rules_from_source_message_edit,
    update_rule_manually,
)
from src.db.database import engine, get_async_session
from src.db.models import ModerationRule, Server


def _make_discord_id() -> int:
    return 8_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


async def _source_sync_preserves_manual_rule() -> None:
    server_id = _make_discord_id()
    channel_id = _make_discord_id()
    message_id = _make_discord_id()
    original_content = "1 **No spam.** Keep it calm.\n2 **No insults.** Be decent."

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name=f"server-{server_id}", bot_active=True))
        await session.flush()
        imported = await import_rules(
            session=session,
            server_id=server_id,
            parsed_rules=parse_rules_from_text(original_content),
            created_by_user_id=None,
            replace_existing=True,
            source_channel_id=channel_id,
            source_message_id=message_id,
            source_content=original_content,
        )

        manual_rule = imported[0]
        synced_rule = imported[1]
        await update_rule_manually(
            session=session,
            server_id=server_id,
            rule_id=manual_rule.id,
            title="Manual no spam",
            description="Manual correction that should survive source edits.",
            code="1",
            sort_order=1,
            is_active=True,
        )

        changed = await sync_rules_from_source_message_edit(
            session=session,
            server_id=server_id,
            channel_id=channel_id,
            message_id=message_id,
            content="1 **No spam from Discord.** Edited remotely.\n2 **No insults from Discord.** Edited remotely.",
        )
        await session.flush()

        refreshed_manual = await session.get(ModerationRule, manual_rule.id)
        refreshed_synced = await session.get(ModerationRule, synced_rule.id)
        states = (
            await session.exec(
                select(ModerationRuleSyncState).where(
                    ModerationRuleSyncState.rule_id.in_([manual_rule.id, synced_rule.id])
                )
            )
        ).all()
        states_by_rule = {state.rule_id: state for state in states}

    await engine.dispose()

    assert {item.id for item in changed} == {manual_rule.id, synced_rule.id}
    assert refreshed_manual.title == "Manual no spam"
    assert refreshed_manual.description == "Manual correction that should survive source edits."
    assert refreshed_manual.source_message_id == message_id
    assert states_by_rule[manual_rule.id].sync_status == ModerationRuleSyncStatus.MANUAL.value
    assert "manual dashboard edits were preserved" in (states_by_rule[manual_rule.id].sync_note or "")

    assert refreshed_synced.title == "No insults from Discord"
    assert refreshed_synced.description == "No insults from Discord. Edited remotely."
    assert states_by_rule[synced_rule.id].sync_status == ModerationRuleSyncStatus.SYNCED.value


def test_source_sync_preserves_manual_rule(monkeypatch):
    monkeypatch.setenv("RULE_IMPORT_LLM_ENABLED", "false")
    asyncio.run(_source_sync_preserves_manual_rule())

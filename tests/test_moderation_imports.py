import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import select

from api.services.moderation_imports_discord import import_discord_baseline
from api.services.moderation_imports_service import (
    ImportedModerationActionPayload,
    create_import_run,
    import_moderation_action,
)
from src.db.database import engine, get_async_session
from src.db.models import (
    ActionType,
    GlobalUser,
    ModerationAction,
    ModerationImportSource,
    ModerationImportSourceItem,
    Server,
)


def _make_discord_id() -> int:
    return 8_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


def _snowflake_for(dt: datetime) -> str:
    discord_epoch_ms = 1420070400000
    timestamp_ms = int(dt.timestamp() * 1000)
    return str((timestamp_ms - discord_epoch_ms) << 22)


async def _quiet_import_idempotency_scenario() -> None:
    server_id = _make_discord_id()
    target_id = _make_discord_id()
    moderator_id = _make_discord_id()

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="import-server", bot_active=True))
        session.add(GlobalUser(discord_id=target_id, username="target"))
        session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
        await session.flush()

        run = await create_import_run(
            session,
            server_id=server_id,
            source=ModerationImportSource.DISCORD,
            started_by_user_id=moderator_id,
        )
        payload = ImportedModerationActionPayload(
            source=ModerationImportSource.DISCORD,
            source_item_type="discord_audit_log",
            source_item_id="audit-1",
            server_id=server_id,
            action_type=ActionType.KICK,
            target_user_id=target_id,
            target_username="target",
            moderator_user_id=moderator_id,
            moderator_username="moderator",
            reason="bad behavior",
            created_at=datetime(2026, 1, 2, 3, 4, 5),
            raw_payload={"id": "audit-1", "action_type": 20},
        )

        first = await import_moderation_action(session, run, payload)
        second = await import_moderation_action(session, run, payload)

        assert first.imported is True
        assert second.imported is False
        assert second.reason == "duplicate"
        assert first.action is not None
        assert second.action is not None
        assert first.action.id == second.action.id

        action_rows = (
            await session.exec(
                select(ModerationAction).where(
                    ModerationAction.server_id == server_id,
                    ModerationAction.target_user_id == target_id,
                    ModerationAction.action_type == ActionType.KICK,
                )
            )
        ).all()
        source_rows = (
            await session.exec(
                select(ModerationImportSourceItem).where(ModerationImportSourceItem.server_id == server_id)
            )
        ).all()
        assert len(action_rows) == 1
        assert len(source_rows) == 1
        await session.rollback()


async def _discord_baseline_scenario(monkeypatch) -> None:
    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    banned_user_id = _make_discord_id()
    kicked_user_id = _make_discord_id()
    timeout_user_id = _make_discord_id()
    audit_dt = datetime.now(timezone.utc)

    async def fake_fetch_guild_bans(server_id_arg: int, limit: int = 1000, after: int | None = None):
        assert server_id_arg == server_id
        if after is not None:
            return []
        return [
            {
                "reason": "legacy active ban",
                "user": {"id": str(banned_user_id), "username": "banned", "discriminator": "0"},
            }
        ]

    async def fake_fetch_guild_audit_logs(
        server_id_arg: int,
        *,
        limit: int = 100,
        before: int | None = None,
        action_type: int | None = None,
    ):
        assert server_id_arg == server_id
        if before is not None:
            return {"audit_log_entries": [], "users": []}
        return {
            "users": [
                {"id": str(moderator_id), "username": "mod", "discriminator": "0"},
                {"id": str(banned_user_id), "username": "banned", "discriminator": "0"},
                {"id": str(kicked_user_id), "username": "kicked", "discriminator": "0"},
                {"id": str(timeout_user_id), "username": "muted", "discriminator": "0"},
            ],
            "audit_log_entries": [
                {
                    "id": _snowflake_for(audit_dt),
                    "action_type": 22,
                    "target_id": str(banned_user_id),
                    "user_id": str(moderator_id),
                    "reason": "audit ban reason",
                },
                {
                    "id": str(int(_snowflake_for(audit_dt)) - 1),
                    "action_type": 20,
                    "target_id": str(kicked_user_id),
                    "user_id": str(moderator_id),
                    "reason": "audit kick reason",
                },
                {
                    "id": str(int(_snowflake_for(audit_dt)) - 2),
                    "action_type": 24,
                    "target_id": str(timeout_user_id),
                    "user_id": str(moderator_id),
                    "reason": "timeout reason",
                    "changes": [
                        {
                            "key": "communication_disabled_until",
                            "new_value": "2026-07-01T12:00:00.000000+00:00",
                        }
                    ],
                },
            ],
        }

    import api.services.moderation_imports_discord as discord_imports

    monkeypatch.setattr(discord_imports, "fetch_guild_bans", fake_fetch_guild_bans)
    monkeypatch.setattr(discord_imports, "fetch_guild_audit_logs", fake_fetch_guild_audit_logs)

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="discord-import-server", bot_active=True))
        await session.flush()

        summary = await import_discord_baseline(session, server_id=server_id, started_by_user_id=moderator_id)

        actions = (
            await session.exec(
                select(ModerationAction).where(ModerationAction.server_id == server_id)
            )
        ).all()
        action_types = sorted(action.action_type for action in actions)
        assert summary["audit_imported"] == 3
        assert summary["active_bans_imported"] == 0
        assert action_types == [ActionType.BAN, ActionType.KICK, ActionType.MUTE]
        active_ban = next(action for action in actions if action.action_type == ActionType.BAN)
        assert active_ban.is_active is True
        assert active_ban.reason == "audit ban reason"

        source_items = (
            await session.exec(
                select(ModerationImportSourceItem).where(ModerationImportSourceItem.server_id == server_id)
            )
        ).all()
        assert len(source_items) == 4  # 3 audit entries plus skipped current-ban state already represented.
        await session.rollback()


def test_import_moderation_action_is_idempotent_and_quiet():
    asyncio.run(_quiet_import_idempotency_scenario())
    asyncio.run(engine.dispose())


def test_import_discord_baseline_imports_audit_and_current_ban_gap(monkeypatch):
    asyncio.run(_discord_baseline_scenario(monkeypatch))
    asyncio.run(engine.dispose())
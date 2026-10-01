import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import discord
import pytest

from src.db.models import GlobalUser, ServerModerationSettings
from src.modules.moderation import ban_worker
from src.modules.moderation.action_resolution import ACTION_RESOLUTION_EXPIRED
from src.modules.localization.service import tr


@pytest.mark.parametrize("already_unbanned", [False, True])
def test_expired_bans_with_mod_log_save_resolution_and_action_numbers(monkeypatch, already_unbanned):
    async def scenario():
        server_id = 478278763239702538
        actions = [
            SimpleNamespace(
                id=uuid4(),
                server_id=server_id,
                target_user_id=100 + number,
                action_number=number,
                is_active=True,
                resolution_type=None,
            )
            for number in (42, 43)
        ]
        settings = SimpleNamespace(mod_log_channel_id=999)
        target = SimpleNamespace(username="member")

        async def get(model, identifier):
            if model is ServerModerationSettings:
                return settings
            assert model is GlobalUser
            return target

        session = SimpleNamespace(get=AsyncMock(side_effect=get), add=Mock(), commit=AsyncMock())

        @asynccontextmanager
        async def session_scope():
            yield session

        guild = SimpleNamespace(id=server_id, unban=AsyncMock())
        if already_unbanned:
            guild.unban.side_effect = discord.NotFound(
                SimpleNamespace(status=404, reason="Not Found"),
                {"code": 10026, "message": "Unknown Ban"},
            )
        client = SimpleNamespace(get_guild=Mock(return_value=guild))
        expired_bans = AsyncMock(return_value=actions)
        send_log = AsyncMock()
        monkeypatch.setattr(ban_worker, "get_async_session", session_scope)
        monkeypatch.setattr(ban_worker, "get_expired_active_bans", expired_bans)
        monkeypatch.setattr(ban_worker, "get_server_locale", AsyncMock(return_value="en"))
        monkeypatch.setattr(ban_worker, "send_mod_log_message", send_log)

        assert await ban_worker.process_expired_bans(client, guild_ids={server_id}) == (2, 0)
        expired_bans.assert_awaited_once_with(session, limit=500)
        assert guild.unban.await_count == 2
        assert send_log.await_count == 2
        session.commit.assert_awaited_once()
        assert session.add.call_count == 2
        for action, log_call in zip(actions, send_log.await_args_list, strict=True):
            assert action.is_active is False
            assert action.resolution_type == ACTION_RESOLUTION_EXPIRED
            embed = log_call.kwargs["embed"]
            assert f"ban #{action.action_number}" in embed.fields[1].value
            assert f"#{action.action_number}" in embed.footer.text
            assert embed.fields[3].value == tr("en", "common.bool_false" if already_unbanned else "common.bool_true")
            assert log_call.kwargs["guild"] is guild
            assert log_call.kwargs["mod_log_channel_id"] == settings.mod_log_channel_id

    asyncio.run(scenario())

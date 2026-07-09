import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from api.services.server_temp_voice import (
    build_temp_voice_archive_transcript,
    delete_active_temp_voice_channel,
    get_temp_voice_archive_detail,
    list_temp_voice_archives,
)
import api.services.server_temp_voice as temp_voice_service
from src.db.database import engine, get_async_session
from src.db.models import (
    AttachmentLog,
    DeletedMessage,
    GlobalUser,
    MessageLog,
    Server,
    TempVoiceLog,
    TempVoiceParticipant,
    VoiceChannel,
)


def _make_discord_id() -> int:
    return 9_100_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


async def _temp_voice_archive_scenario() -> None:
    await engine.dispose()
    server_id = _make_discord_id()
    owner_id = _make_discord_id()
    channel_id = _make_discord_id()
    message_id = _make_discord_id()
    deleted_message_id = _make_discord_id()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    temp_log_id = uuid4()

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="archive-server", bot_active=True))
        session.add(GlobalUser(discord_id=owner_id, username="owner"))
        await session.flush()
        session.add(
            TempVoiceLog(
                id=temp_log_id,
                server_id=server_id,
                channel_id=channel_id,
                trigger_channel_id=_make_discord_id(),
                owner_user_id=owner_id,
                channel_name="owner's room",
                created_at=now,
                deleted_at=now + timedelta(minutes=30),
            )
        )
        await session.flush()
        session.add(
            TempVoiceParticipant(
                log_id=temp_log_id,
                server_id=server_id,
                channel_id=channel_id,
                user_id=owner_id,
                joined_at=now,
                left_at=now + timedelta(minutes=15),
            )
        )
        session.add(
            MessageLog(
                message_id=message_id,
                log_id=temp_log_id,
                user_id=owner_id,
                channel_id=channel_id,
                content="hello from voice text",
                created_at=now + timedelta(minutes=1),
                reply_to_message_id=None,
                server_id=server_id,
            )
        )
        session.add(
            AttachmentLog(
                message_id=message_id,
                storage_key="https://cdn.discordapp.com/live.png",
                file_name="live.png",
                content_type="image/png",
            )
        )
        session.add(
            DeletedMessage(
                server_id=server_id,
                message_id=deleted_message_id,
                channel_id=channel_id,
                author_user_id=owner_id,
                content="deleted from voice text",
                attachments_json=json.dumps(
                    [
                        {
                            "storage_key": "https://cdn.discordapp.com/deleted.png",
                            "file_name": "deleted.png",
                            "content_type": "image/png",
                        }
                    ]
                ),
                deleted_at=now + timedelta(minutes=2),
            )
        )
        await session.commit()

        archives = await list_temp_voice_archives(session=session, server_id=server_id)
        assert len(archives) == 1
        assert archives[0].message_count == 1
        assert archives[0].deleted_message_count == 1
        assert archives[0].attachment_count == 1
        assert archives[0].deleted_attachment_count == 1
        assert archives[0].duration_seconds == 1800

        detail = await get_temp_voice_archive_detail(session=session, server_id=server_id, log_id=temp_log_id)
        assert len(detail.participants) == 1
        assert detail.participants[0].display_name == "owner"
        assert detail.participants[0].duration_seconds == 900
        assert [message.deleted for message in detail.messages] == [False, True]
        assert detail.messages[0].attachments[0].file_name == "live.png"
        assert detail.messages[1].attachments[0].file_name == "deleted.png"

        transcript = await build_temp_voice_archive_transcript(session=session, server_id=server_id, log_id=temp_log_id)
        assert "hello from voice text" in transcript
        assert "deleted attachment: deleted.png" in transcript

    await engine.dispose()


def test_temp_voice_archive_list_detail_and_transcript():
    asyncio.run(_temp_voice_archive_scenario())


async def _delete_active_temp_voice_channel_scenario(monkeypatch) -> None:
    await engine.dispose()
    server_id = _make_discord_id()
    owner_id = _make_discord_id()
    channel_id = _make_discord_id()
    trigger_channel_id = _make_discord_id()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    temp_log_id = uuid4()
    deleted_channels: list[int] = []

    async def fake_delete_channel(channel_id_arg: int, *, reason: str | None = None) -> None:
        deleted_channels.append(channel_id_arg)
        assert "dashboard" in (reason or "")

    monkeypatch.setattr(temp_voice_service, "delete_channel", fake_delete_channel)

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="cleanup-server", bot_active=True))
        session.add(GlobalUser(discord_id=owner_id, username="owner"))
        await session.flush()
        session.add(
            VoiceChannel(
                server_id=server_id,
                channel_id=channel_id,
                trigger_channel_id=trigger_channel_id,
                owner_user_id=owner_id,
                channel_name="owner's active room",
                created_at=now,
            )
        )
        session.add(
            TempVoiceLog(
                id=temp_log_id,
                server_id=server_id,
                channel_id=channel_id,
                trigger_channel_id=trigger_channel_id,
                owner_user_id=owner_id,
                channel_name="owner's active room",
                created_at=now,
            )
        )
        session.add(
            TempVoiceParticipant(
                log_id=temp_log_id,
                server_id=server_id,
                channel_id=channel_id,
                user_id=owner_id,
                joined_at=now,
            )
        )
        await session.commit()

        summary = await delete_active_temp_voice_channel(
            session=session,
            server_id=server_id,
            log_id=temp_log_id,
            actor_user_id=owner_id,
        )
        await session.commit()

        assert deleted_channels == [channel_id]
        assert summary.deleted_at is not None
        assert summary.duration_seconds >= 0
        assert await session.get(VoiceChannel, (server_id, channel_id)) is None

        detail = await get_temp_voice_archive_detail(session=session, server_id=server_id, log_id=temp_log_id)
        assert detail.deleted_at is not None
        assert detail.participants[0].left_at is not None

    await engine.dispose()


def test_delete_active_temp_voice_channel(monkeypatch):
    asyncio.run(_delete_active_temp_voice_channel_scenario(monkeypatch))

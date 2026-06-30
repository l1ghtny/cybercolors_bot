import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from api.services.server_temp_voice import (
    build_temp_voice_archive_transcript,
    get_temp_voice_archive_detail,
    list_temp_voice_archives,
)
from src.db.database import engine, get_async_session
from src.db.models import AttachmentLog, DeletedMessage, GlobalUser, MessageLog, Server, TempVoiceLog


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

        detail = await get_temp_voice_archive_detail(session=session, server_id=server_id, log_id=temp_log_id)
        assert [message.deleted for message in detail.messages] == [False, True]
        assert detail.messages[0].attachments[0].file_name == "live.png"
        assert detail.messages[1].attachments[0].file_name == "deleted.png"

        transcript = await build_temp_voice_archive_transcript(session=session, server_id=server_id, log_id=temp_log_id)
        assert "hello from voice text" in transcript
        assert "deleted attachment: deleted.png" in transcript

    await engine.dispose()


def test_temp_voice_archive_list_detail_and_transcript():
    asyncio.run(_temp_voice_archive_scenario())

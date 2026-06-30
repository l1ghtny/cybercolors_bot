import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from api.services.moderation_actions_service import browse_deleted_attachments_for_server
from src.db.database import engine, get_async_session
from src.db.models import DeletedMessage, GlobalUser, Server


def _make_discord_id() -> int:
    return 9_200_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


async def _deleted_attachments_scenario() -> None:
    await engine.dispose()
    server_id = _make_discord_id()
    author_id = _make_discord_id()
    moderator_id = _make_discord_id()
    channel_id = _make_discord_id()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="deleted-attachments", bot_active=True))
        session.add(GlobalUser(discord_id=author_id, username="author"))
        session.add(GlobalUser(discord_id=moderator_id, username="mod"))
        session.add(
            DeletedMessage(
                server_id=server_id,
                message_id=_make_discord_id(),
                channel_id=channel_id,
                author_user_id=author_id,
                deleted_by_user_id=author_id,
                content="self deleted",
                attachments_json=json.dumps(
                    [
                        {
                            "storage_key": "https://cdn.discordapp.com/self.png",
                            "file_name": "self.png",
                            "content_type": "image/png",
                        },
                        {
                            "storage_key": "https://cdn.discordapp.com/self.txt",
                            "file_name": "self.txt",
                            "content_type": "text/plain",
                        },
                    ]
                ),
                deleted_at=now,
            )
        )
        session.add(
            DeletedMessage(
                server_id=server_id,
                message_id=_make_discord_id(),
                channel_id=channel_id,
                author_user_id=author_id,
                deleted_by_user_id=moderator_id,
                content="moderator deleted",
                attachments_json=json.dumps(
                    [
                        {
                            "storage_key": "https://cdn.discordapp.com/mod.jpg",
                            "file_name": "mod.jpg",
                            "content_type": "image/jpeg",
                        }
                    ]
                ),
                deleted_at=now + timedelta(seconds=1),
            )
        )
        await session.commit()

        images = await browse_deleted_attachments_for_server(session=session, server_id=server_id, kind="image")
        assert [row.attachment.file_name for row in images] == ["mod.jpg", "self.png"]

        self_deleted = await browse_deleted_attachments_for_server(
            session=session,
            server_id=server_id,
            kind="all",
            deletion_type="self",
            sort_by="deletion_type",
        )
        assert [row.attachment.file_name for row in self_deleted] == ["self.png", "self.txt"]
        assert {row.deletion_type for row in self_deleted} == {"self"}

    await engine.dispose()


def test_deleted_attachments_are_flattened_and_filterable():
    asyncio.run(_deleted_attachments_scenario())

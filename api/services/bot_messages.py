from collections.abc import Awaitable, Callable

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.bot_messages import BotMessageAuditReadModel, BotMessageCreateModel
from api.services.discord_guilds import (
    TEXT_CHANNEL_TYPES,
    create_channel_message,
    fetch_channel,
    fetch_channel_message,
)
from src.db.models import (
    BotMessageAuditEvent,
    GlobalUser,
    ServerSecuritySettings,
    utcnow_utc_tz,
)

DiscordSender = Callable[..., Awaitable[dict]]
ChannelFetcher = Callable[[int, int], Awaitable[dict | None]]
MessageFetcher = Callable[[int, int], Awaitable[dict]]


def to_bot_message_audit_read_model(event: BotMessageAuditEvent) -> BotMessageAuditReadModel:
    message_id = str(event.discord_message_id) if event.discord_message_id is not None else None
    return BotMessageAuditReadModel(
        id=event.id,
        server_id=str(event.server_id),
        channel_id=str(event.channel_id),
        discord_message_id=message_id,
        reply_to_message_id=(
            str(event.reply_to_message_id) if event.reply_to_message_id is not None else None
        ),
        actor_user_id=str(event.actor_user_id),
        source=event.source,
        status=event.status,
        content=event.content,
        error_text=event.error_text,
        created_at=event.created_at,
        sent_at=event.sent_at,
        jump_url=(
            f"https://discord.com/channels/{event.server_id}/{event.channel_id}/{message_id}"
            if message_id is not None
            else None
        ),
    )


async def _ensure_actor_exists(session: AsyncSession, actor_user_id: int) -> None:
    if await session.get(GlobalUser, actor_user_id) is not None:
        return
    session.add(GlobalUser(discord_id=actor_user_id, username=None))
    await session.flush()


async def _assert_public_responses_enabled(session: AsyncSession, server_id: int) -> None:
    settings = await session.get(ServerSecuritySettings, server_id)
    if settings is not None and settings.public_bot_responses_paused:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Public bot responses are paused by the server security settings",
        )


async def send_bot_message(
    session: AsyncSession,
    *,
    server_id: int,
    actor_user_id: int,
    body: BotMessageCreateModel,
    source: str,
    sender: DiscordSender = create_channel_message,
    channel_fetcher: ChannelFetcher = fetch_channel,
    message_fetcher: MessageFetcher = fetch_channel_message,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> BotMessageAuditReadModel:
    if source not in {"dashboard", "discord_context"}:
        raise ValueError(f"Unsupported bot message source: {source}")

    await _assert_public_responses_enabled(session, server_id)
    attachments = attachments or []
    if not body.content.strip() and not attachments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Add message text or at least one image",
        )
    channel_id = int(body.channel_id)
    channel = await channel_fetcher(server_id, channel_id)
    if channel is None or int(channel.get("type", -1)) not in TEXT_CHANNEL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select a text or announcement channel from this server",
        )

    reply_to_message_id = int(body.reply_to_message_id) if body.reply_to_message_id else None
    if reply_to_message_id is not None:
        await message_fetcher(channel_id, reply_to_message_id)

    await _ensure_actor_exists(session, actor_user_id)
    audit_content = body.content
    if attachments:
        attachment_summary = ", ".join(filename for filename, _, _ in attachments)
        audit_content = f"{body.content}\n\n[Attachments: {attachment_summary}]".strip()

    audit = BotMessageAuditEvent(
        server_id=server_id,
        channel_id=channel_id,
        reply_to_message_id=reply_to_message_id,
        actor_user_id=actor_user_id,
        source=source,
        status="pending",
        content=audit_content,
    )
    session.add(audit)
    await session.commit()

    try:
        sender_kwargs = {
            "channel_id": channel_id,
            "content": body.content or None,
            "reply_to_message_id": reply_to_message_id,
            "notify_replied_user": (
                body.notify_replied_user if reply_to_message_id is not None else False
            ),
        }
        if attachments:
            sender_kwargs["files"] = attachments
        discord_message = await sender(
            **sender_kwargs,
        )
        raw_message_id = discord_message.get("id")
        if raw_message_id is None or not str(raw_message_id).isdigit():
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Discord did not return a message id",
            )
    except Exception as error:
        audit.status = "failed"
        audit.error_text = str(getattr(error, "detail", error))[:2000]
        session.add(audit)
        await session.commit()
        raise

    audit.discord_message_id = int(raw_message_id)
    audit.status = "sent"
    audit.sent_at = utcnow_utc_tz()
    audit.error_text = None
    session.add(audit)
    await session.commit()
    return to_bot_message_audit_read_model(audit)


async def list_bot_message_audits(
    session: AsyncSession,
    *,
    server_id: int,
    limit: int = 50,
) -> list[BotMessageAuditReadModel]:
    events = (
        await session.exec(
            select(BotMessageAuditEvent)
            .where(BotMessageAuditEvent.server_id == server_id)
            .order_by(BotMessageAuditEvent.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    return [to_bot_message_audit_read_model(event) for event in events]

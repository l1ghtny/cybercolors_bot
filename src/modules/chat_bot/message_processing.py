import os

from api.services.ai_settings import can_invoke_answer_flow
from src.db.database import get_async_session
from src.db.models import ServerAISettings
from src.modules.chat_bot.create_response import create_one_response, create_response_to_dialog
from src.modules.ai.discord_media import ai_images_from_discord_message
from src.modules.localization.service import tr
from src.misc_files.check_if_message_has_reply import check_replies

REPLY_THREAD_LIMIT = 20


async def decide_on_response(message, client, *, locale: str | None = None):
    if check_replies(message) is False:
        bot_response, token_total = await create_one_response(message, client)
    else:
        n, messages_raw = await count_replies(message)
        if n > REPLY_THREAD_LIMIT:
            bot_response = tr(locale, "ai_reply.thread_limit", limit=REPLY_THREAD_LIMIT)
            token_total = 0
        elif verify_user(messages_raw, message, client):
            messages_processed = await organise_messages(messages_raw, client)
            messages_processed.append(
                {
                    "role": "user",
                    "content": await remove_bot_mention(message, client),
                    "images": ai_images_from_discord_message(message),
                }
            )
            bot_response, token_total = await create_response_to_dialog(messages_processed, message=message)
        else:
            bot_response = tr(locale, "ai_reply.thread_multi_user")
            token_total = 0
    return bot_response, token_total


async def check_bot_mention(message_to_check, client):
    mentions = message_to_check.mentions
    has_bot_request = False
    for i in mentions:
        if i == client.user:
            has_bot_request = not has_bot_request
    return has_bot_request


async def check_for_channel(message_to_check_for_channel, client):
    guild = getattr(message_to_check_for_channel, "guild", None)
    channel = getattr(message_to_check_for_channel, "channel", None)
    author = getattr(message_to_check_for_channel, "author", None)
    if guild is not None and channel is not None:
        async with get_async_session() as session:
            settings = await session.get(ServerAISettings, guild.id)
            if settings is not None:
                role_ids = [role.id for role in getattr(author, "roles", [])]
                return (
                    can_invoke_answer_flow(settings, channel_id=channel.id, role_ids=role_ids),
                    channel,
                )

    legacy_channel_ids = []
    for env_name in ("chat_gpt_channel_id", "new_channel_chat_gpt_id"):
        raw_channel_id = os.getenv(env_name)
        if raw_channel_id and raw_channel_id.isdigit():
            legacy_channel_ids.append(int(raw_channel_id))

    if not legacy_channel_ids or channel is None:
        return False, None

    return channel.id in set(legacy_channel_ids), channel


async def remove_bot_mention(message_to_remove_mention, client):
    content = message_to_remove_mention.content
    bot_id = client.user.id
    new_content = content.replace(f"<@{bot_id}>", "")
    new_content = new_content.replace(f"<@!{bot_id}>", "")
    return new_content


async def count_replies(message):
    n = 0
    messages_raw = []
    while check_replies(message) is True:
        n = n + 1
        channel = message.channel
        reference = message.reference
        my_message_id = reference.message_id
        message = await channel.fetch_message(my_message_id)
        messages_raw.append(
            {
                "author": message.author.id,
                "content": message.content,
                "images": ai_images_from_discord_message(message),
            }
        )
    return n, messages_raw


async def organise_messages(messages, client):
    messages.reverse()
    messages_processed = []
    for i in messages:
        if i["content"].startswith(f"<@{client.user.id}>"):
            content = i["content"]
            new_message = content.replace(f"<@{client.user.id}>", "")
            new_message = new_message.replace(f"<@!{client.user.id}>", "")
            messages_processed.append({"role": "user", "content": new_message, "images": i.get("images") or []})
        elif i["author"] == client.user.id:
            new_message = i["content"]
            messages_processed.append({"role": "assistant", "content": new_message})
        else:
            new_message = i["content"]
            messages_processed.append({"role": "user", "content": new_message, "images": i.get("images") or []})
    return messages_processed


def verify_user(messages, message, client):
    bot_id = client.user.id
    current_author_id = message.author.id
    owners = {
        i["author"]
        for i in messages
        if i["author"] != bot_id and _is_bot_request(i.get("content") or "", bot_id)
    }
    owners.add(current_author_id)
    return len(owners) == 1


def _is_bot_request(content: str, bot_id: int) -> bool:
    return f"<@{bot_id}>" in content or f"<@!{bot_id}>" in content

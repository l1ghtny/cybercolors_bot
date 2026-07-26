from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import engine
from src.db.models import Replies, ServerReplySettings, Triggers
from src.modules.on_message_processing.processing_methods import (
    normalize_reply_text,
    normalized_reply_trigger_matches,
)


def automatic_reply_allowed(message, settings: ServerReplySettings | None) -> bool:
    if settings is None:
        return True

    channel_ids = {str(message.channel.id)}
    parent_id = getattr(message.channel, "parent_id", None)
    if parent_id is None:
        parent_id = getattr(getattr(message.channel, "parent", None), "id", None)
    if parent_id is not None:
        channel_ids.add(str(parent_id))

    included_channels = set(settings.included_channel_ids or [])
    excluded_channels = set(settings.excluded_channel_ids or [])
    if excluded_channels.intersection(channel_ids):
        return False
    if included_channels and not included_channels.intersection(channel_ids):
        return False

    author = message.author
    if str(author.id) in set(settings.excluded_user_ids or []):
        return False
    author_role_ids = {
        str(role.id)
        for role in (getattr(author, "roles", None) or [])
    }
    if set(settings.excluded_role_ids or []).intersection(author_role_ids):
        return False
    return True


async def check_for_replies(message):
    database_found = False
    message_content = normalize_reply_text(message.content)
    server_id = message.guild.id
    
    async with AsyncSession(engine) as session:
        settings = await session.get(ServerReplySettings, server_id)
        if not automatic_reply_allowed(message, settings):
            return False, server_id
        # Join Triggers and Replies to get both in one go
        statement = select(Triggers, Replies).join(Replies).where(Replies.server_id == server_id)
        result = await session.exec(statement)
        rows = result.all()
    
    for trigger, reply in rows:
        trigger_text_raw = trigger.message
        response_text = reply.bot_reply
        
        # Handle the f-string style response if it starts with f' or f"
        is_fstring = response_text.startswith("f'") or response_text.startswith('f"')
        
        if normalized_reply_trigger_matches(trigger_text_raw, message_content):
            database_found = True
            await send_reply(message, response_text, is_fstring)
            break
                
    return database_found, server_id

async def send_reply(message, response_text, is_fstring):
    if is_fstring:
        try:
            # Dangerous, but maintaining compatibility with existing logic
            # Using eval to process f-string. 
            # Note: We need to be careful about what variables are available in eval.
            processed_response = eval(response_text)
            if message.content.isupper():
                processed_response = processed_response.upper()
            await message.reply(processed_response)
        except Exception:
            # Fallback to literal if eval fails
            final_resp = response_text.upper() if message.content.isupper() else response_text
            await message.reply(final_resp)
    else:
        final_resp = response_text.upper() if message.content.isupper() else response_text
        await message.reply(final_resp)

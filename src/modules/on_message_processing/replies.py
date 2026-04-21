import string
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import engine
from src.db.models import Triggers, Replies
from src.modules.on_message_processing.processing_methods import em_replace, e_replace, string_found


async def check_for_replies(message):
    database_found = False
    message_content_base = message.content.lower()
    message_content_e = em_replace(message_content_base)
    message_content_punctuation = e_replace(message_content_e)

    # Content without punctuation for matching
    message_content = message_content_punctuation.translate(str.maketrans('', '', string.punctuation))
    server_id = message.guild.id
    
    async with AsyncSession(engine) as session:
        # Join Triggers and Replies to get both in one go
        statement = select(Triggers, Replies).join(Replies).where(Replies.server_id == server_id)
        result = await session.exec(statement)
        rows = result.all()
    
    for trigger, reply in rows:
        trigger_text_raw = trigger.message
        # Remove punctuation from trigger for better matching
        trigger_text = trigger_text_raw.translate(str.maketrans('', '', string.punctuation))
        response_text = reply.bot_reply
        
        # Handle the f-string style response if it starts with f' or f"
        is_fstring = response_text.startswith("f'") or response_text.startswith('f"')
        
        if trigger_text_raw.startswith('<'):
            # Simple "contains" match
            if trigger_text in message_content:
                database_found = True
                await send_reply(message, response_text, is_fstring)
                break # Stop after first match? Or continue? Original code toggled database_found.
        else:
            # Word-boundary match
            if string_found(trigger_text, message_content):
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

import string

from sqlmodel import select

from src.db.database import get_session
from src.db.models import Message
from src.modules.on_message_processing.processing_methods import em_replace, e_replace, string_found


async def check_for_replies(message):
    database_found = False
    message_content_base = message.content.lower()
    message_content_e = em_replace(message_content_base)
    message_content_punctuation = e_replace(message_content_e)

    message_content = message_content_punctuation.translate(str.maketrans('', '', string.punctuation))
    server_id = message.guild.id
    async with get_session() as session:
        query = select(Message).where(Message.server_id == server_id)
        result = await session.exec(query)
        all_rows = result.all()
    for item in all_rows:
        request_base = item['request_phrase']
        request = request_base.translate(str.maketrans('', '', string.punctuation))
        response_base = (item['respond_phrase'])
        response = string.Template("f'$string'").substitute(string=response_base)
        if request_base.startswith('<'):
            if request in message_content:
                database_found = not database_found
                await message.reply(response_base)
        else:
            find_phrase = string_found(request, message_content)
            if find_phrase is True:
                database_found = not database_found
                if not message.content.isupper():
                    try:
                        await message.reply(eval(response))
                    except SyntaxError:
                        await message.reply(response_base)
                    except NameError:
                        await message.reply(response_base)
                else:
                    response = response.upper()
                    try:
                        await message.reply(eval(response))
                    except SyntaxError:
                        await message.reply(response_base.upper())
                    except NameError:
                        await message.reply(response_base.upper())
    return database_found, server_id

import string

from src.misc_files import basevariables
from src.modules.on_message_processing.processing_methods import em_replace, e_replace, string_found


async def check_for_replies(message):
    database_found = False
    message_content_base = message.content.lower()
    message_content_e = em_replace(message_content_base)
    message_content_punctuation = e_replace(message_content_e)

    message_content = message_content_punctuation.translate(str.maketrans('', '', string.punctuation))
    server_id = message.guild.id
    conn, cursor = await basevariables.access_db_on_message(message)
    query = 'SELECT * from messages WHERE server_id=%s'
    values = (server_id,)
    cursor.execute(query, values)
    all_rows = cursor.fetchall()
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
    return conn, cursor, database_found, server_id

import src.modules.chat_bot.openai_main


async def create_one_response(message, client):
    from src.modules.chat_bot.message_processing import remove_bot_mention
    content = await remove_bot_mention(message, client)
    response, token_total = src.modules.chat_bot.openai_main.one_response(content)
    return response, token_total


async def create_response_to_dialog(message_list):
    response, token_total = src.modules.chat_bot.openai_main.multiple_responses(message_list)
    return response, token_total

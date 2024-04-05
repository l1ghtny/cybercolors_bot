import os

from modules.chat_bot.create_response import create_one_response, create_response_to_dialog
from misc_files.blocking_script import run_blocking
from misc_files.check_if_message_has_reply import check_replies


async def decide_on_response(message, client):
    if check_replies(message) is False:
        bot_response, token_total = await run_blocking(client, create_one_response, message, client)
    else:
        n, messages_raw = await count_replies(message)
        if n > 8:
            bot_response = 'Извини, я могу запомнить только пять запросов, не более. Если хочешь пообщаться, обратись ко мне заново'
            token_total = 0
        else:
            if verify_user(messages_raw, message, client) is True:
                messages_processed = organise_messages(messages_raw, client)
                messages_processed.append({'role': 'user', 'content': message.content})
                bot_response, token_total = await run_blocking(client, create_response_to_dialog, messages_processed)
            else:
                bot_response = 'В цепочке ответов более одного пользователя. Я могу поддерживать диалог только с одним пользователем, извини'
                token_total = 0
    return bot_response, token_total


def check_bot_mention(message_to_check, client):
    mentions = message_to_check.mentions
    has_bot_request = False
    for i in mentions:
        if i == client.user:
            has_bot_request = not has_bot_request
    return has_bot_request


def check_for_channel(message_to_check_for_channel, client):
    bot_channel_id = int(os.getenv('chat_gpt_channel_id'))
    bot_den_channel_id = int(os.getenv('new_channel_chat_gpt_id'))
    bot_channel = client.get_channel(bot_channel_id)
    bot_den_channel = client.get_channel(bot_den_channel_id)
    if bot_channel == message_to_check_for_channel.channel or bot_den_channel == message_to_check_for_channel.channel:
        allowed_channel = True
    else:
        allowed_channel = False
    return allowed_channel, bot_channel


def remove_bot_mention(message_to_remove_mention, client):
    content = message_to_remove_mention.content
    bot_id = client.user.id
    new_content = content.replace(f'<@{bot_id}>', '')
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
        messages_raw.append({
            "author": message.author.id,
            "content": message.content
        })
    return n, messages_raw


def organise_messages(messages, client):
    messages.reverse()
    messages_processed = []
    for i in messages:
        if i['content'].startswith(f'<@{client.user.id}>'):
            content = i['content']
            new_message = content.replace(f'<@{client.user.id}>', '')
            messages_processed.append({'role': 'user', 'content': new_message})
        elif i['author'] == client.user.id:
            new_message = i['content']
            messages_processed.append({'role': 'assistant', 'content': new_message})
        else:
            new_message = i['content']
            messages_processed.append({'role': 'user', 'content': new_message})
    return messages_processed


def verify_user(messages, message, client):
    user_verified = False
    messages_authors = []
    for i in messages:
        messages_authors.append(i['author'])
    unique = set(messages_authors)
    unique.remove(client.user.id)
    unique.add(message.author.id)
    if len(unique) == 1:
        user_verified = not user_verified
    return user_verified

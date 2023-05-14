from twitter_link_fix.twitter_main import twitter_link_replace


async def manage_message(message, user):
    files = []
    for item in message.attachments:
        file = await item.to_file()
        files.append(file)
    await message.delete()
    await twitter_link_replace(message, user, attachment=files)

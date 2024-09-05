from src.misc_files.check_if_message_has_reply import check_replies
from src.modules.twitter_link_fix.twitter_main import twitter_link_replace


async def manage_message(message, user):
    files = []
    for item in message.attachments:
        file = await item.to_file()
        files.append(file)
    if check_replies(message) is True:
        reference = message.reference
        reply_id = reference.message_id
        reply = await message.channel.fetch_message(reply_id)
    else:
        reply = None
    await message.delete()
    await twitter_link_replace(message, user,  reply, attachment=files)

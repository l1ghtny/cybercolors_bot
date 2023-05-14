import discord

from misc_files.check_if_message_has_reply import check_replies
from twitter_link_fix.twitter_main import twitter_link_replace


async def manage_message(message, user, client):
    files = []
    for item in message.attachments:
        file = await item.to_file()
        files.append(file)
    if check_replies(message) is True:
        reference = message.reference
        reply_id = reference.message_id
        reply = await message.channel.fetch_message(reply_id)
        embed = discord.Embed(colour=discord.Colour.dark_blue(), title='Ответ на', url=reply.jump_url)
        embed.set_author(name=reply.author.display_name, url=reply.jump_url, icon_url=reply.author.avatar)
        temp_channel = client.get_channel(1107254818059321374)
    else:
        reply = None,
        embed = None
        temp_channel = None
    await message.delete()
    await twitter_link_replace(message, user,  reply, attachment=files)

import discord


async def twitter_link_replace(message, from_user, attachment):
    if message.channel.type == discord.ChannelType.text:
        webhook_channel = message.channel
        channel_type = 'text'
    else:
        webhook_channel = message.channel.parent
        channel_type = 'not_text'
        thread = message.channel
    webhook = await webhook_channel.create_webhook(name=from_user.name)
    new_message = message.content.replace('twitter', 'fxtwitter')
    if channel_type == 'text':
        await webhook.send(str(new_message), username=from_user.display_name, avatar_url=from_user.avatar, files=attachment)
    else:
        await webhook.send(str(new_message), username=from_user.display_name, avatar_url=from_user.avatar,
                           files=attachment, thread=thread)
    webhooks = await webhook_channel.webhooks()
    for webhook in webhooks:
        await webhook.delete()

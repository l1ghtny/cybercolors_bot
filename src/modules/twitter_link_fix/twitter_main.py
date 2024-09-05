import discord


async def twitter_link_replace(message, from_user, reply, attachment):
    if message.channel.type == discord.ChannelType.text:
        webhook_channel = message.channel
        channel_type = 'text'
    else:
        webhook_channel = message.channel.parent
        channel_type = 'not_text'
        thread = message.channel
    webhook = await webhook_channel.create_webhook(name=from_user.name)
    new_message_2 = message.content.replace('twitter', 'vxtwitter')
    new_message = new_message_2.replace('https://x.com/', 'https://vxtwitter.com/')
    if channel_type == 'text':
        if reply is None:
            await webhook.send(str(new_message), username=from_user.display_name, avatar_url=from_user.avatar, files=attachment)
        else:
            if from_user != reply.author:
                webhook_message = await webhook.send(str(new_message), username=from_user.display_name, avatar_url=from_user.avatar,
                                   files=attachment, wait=True)
                reply_embed = discord.Embed(colour=discord.Colour.dark_blue(), title='Сообщение с ответом', url=webhook_message.jump_url)
                reply_embed.set_author(name=webhook_message.author.display_name, url=webhook_message.jump_url, icon_url=from_user.avatar)
                await reply.reply('Тебе ответили \U0001F446', embed=reply_embed)
            else:
                webhook_message = await webhook.send(str(new_message), username=from_user.display_name,
                                                     avatar_url=from_user.avatar,
                                                     files=attachment, wait=True)
                reply_embed = discord.Embed(colour=discord.Colour.dark_blue(), title='Сообщение с ответом',
                                            url=webhook_message.jump_url)
                reply_embed.set_author(name=webhook_message.author.display_name, url=webhook_message.jump_url,
                                       icon_url=from_user.avatar)
                await reply.reply('Упоминаю это сообщение \U0001F446', embed=reply_embed, silent=True)
    else:
        if reply is None:
            await webhook.send(str(new_message), username=from_user.display_name, avatar_url=from_user.avatar,
                               files=attachment, thread=thread)
        else:
            if from_user != reply.author:
                webhook_message = await webhook.send(str(new_message), username=from_user.display_name, avatar_url=from_user.avatar,
                                   files=attachment, thread=thread, wait=True)
                reply_embed = discord.Embed(colour=discord.Colour.dark_blue(), title='Сообщение с ответом',
                                            url=webhook_message.jump_url)
                reply_embed.set_author(name=webhook_message.author.display_name, url=webhook_message.jump_url,
                                       icon_url=from_user.avatar)
                await reply.reply('Тебе ответили \U0001F446', embed=reply_embed)
            else:
                webhook_message = await webhook.send(str(new_message), username=from_user.display_name,
                                                     avatar_url=from_user.avatar,
                                                     files=attachment, thread=thread, wait=True)
                reply_embed = discord.Embed(colour=discord.Colour.dark_blue(), title='Сообщение с ответом',
                                            url=webhook_message.jump_url)
                reply_embed.set_author(name=webhook_message.author.display_name, url=webhook_message.jump_url,
                                       icon_url=from_user.avatar)
                await reply.reply('Упоминаю это сообщение \U0001F446', embed=reply_embed, silent=True)
    webhooks = await webhook_channel.webhooks()
    for webhook in webhooks:
        await webhook.delete()

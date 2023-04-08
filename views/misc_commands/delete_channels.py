import discord
import discord.ui


class Channels(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(custom_id='channels_list', channel_types=[discord.ChannelType.text],
                         placeholder='Фича пока находится разработке', min_values=1, max_values=15, disabled=False)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        d_channels = self.values
        deleted_channels_info = []
        for items in d_channels:
            await discord.TextChannel.delete(items)
            deleted_channels_info.append(items.name)
        await interaction.followup.send(f'Удалены следующие каналы: {deleted_channels_info}')
        message = self.info
        await DropDownViewChannels.disable_all_items(message)


class DropDownViewChannels(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.disabled = None
        select = Channels()
        self.add_item(select)
        select.info = self

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

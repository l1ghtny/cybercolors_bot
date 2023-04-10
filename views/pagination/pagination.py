import math

import discord
import discord.ui


class PaginationView(discord.ui.View):
    current_page: int = 1
    sep: int = 15

    def __init__(self, data, user, title, footer, maximum):
        super().__init__(timeout=None)
        self.message = None
        self.roundup = math.ceil(len(data) / self.sep)
        self.interaction_user = user
        self.title = title
        self.footer = footer
        self.max = maximum

    async def send(self, interaction):
        self.message = await interaction.channel.send(view=self)
        await self.update_message(self.data[:self.sep])

    def create_embed(self, data):
        embed = discord.Embed(
            title=f"{self.title}:   Страница {self.current_page} / {self.roundup}")
        for item in data:
            embed.add_field(name=item['label'], value=item['value'], inline=False)
        embed.set_footer(text=f'{self.footer}: {self.counted}. Макс {self.max} на странице: {self.sep}')
        return embed

    async def update_message(self, data):
        self.update_buttons()
        await self.message.edit(embed=self.create_embed(data), view=self)

    def update_buttons(self):
        if self.current_page == 1:
            self.first_page_button.disabled = True
            self.prev_button.disabled = True
            self.first_page_button.style = discord.ButtonStyle.gray
            self.prev_button.style = discord.ButtonStyle.gray
        else:
            self.first_page_button.disabled = False
            self.prev_button.disabled = False
            self.first_page_button.style = discord.ButtonStyle.green
            self.prev_button.style = discord.ButtonStyle.primary

        if self.current_page == self.roundup:
            self.next_button.disabled = True
            self.last_page_button.disabled = True
            self.last_page_button.style = discord.ButtonStyle.gray
            self.next_button.style = discord.ButtonStyle.gray
        else:
            self.next_button.disabled = False
            self.last_page_button.disabled = False
            self.last_page_button.style = discord.ButtonStyle.green
            self.next_button.style = discord.ButtonStyle.primary

    def get_current_page_data(self):
        until_item = self.current_page * self.sep
        from_item = until_item - self.sep
        if self.current_page == 1:
            from_item = 0
            until_item = self.sep
        if self.current_page == self.roundup:
            from_item = self.current_page * self.sep - self.sep
            until_item = len(self.data)
        return self.data[from_item:until_item]

    @discord.ui.button(style=discord.ButtonStyle.green, emoji='\U000023EA')
    async def first_page_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.interaction_user == interaction.user:
            await interaction.response.defer()
            self.current_page = 1

            await self.update_message(self.get_current_page_data())
        else:
            await interaction.response.send_message('Это не твоё. Вызови себе своё и нажимай сколько хочешь', ephemeral=True)

    @discord.ui.button(emoji='\U000025C0',
                       style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.interaction_user == interaction.user:
            await interaction.response.defer()
            self.current_page -= 1
            await self.update_message(self.get_current_page_data())
        else:
            await interaction.response.send_message('Это не твоё. Вызови себе своё и нажимай сколько хочешь', ephemeral=True)

    @discord.ui.button(emoji='\U000025B6',
                       style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.interaction_user == interaction.user:
            await interaction.response.defer()
            self.current_page += 1
            await self.update_message(self.get_current_page_data())
        else:
            await interaction.response.send_message('Это не твоё. Вызови себе своё и нажимай сколько хочешь', ephemeral=True)

    @discord.ui.button(emoji='\U000023ED',
                       style=discord.ButtonStyle.green)
    async def last_page_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.interaction_user == interaction.user:
            await interaction.response.defer()
            self.current_page = int(len(self.data) / self.sep) + 1
            await self.update_message(self.get_current_page_data())
        else:
            await interaction.response.send_message('Это не твоё. Вызови себе своё и нажимай сколько хочешь', ephemeral=True)

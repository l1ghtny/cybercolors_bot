import discord.ui

from src.misc_files import basevariables


class DeleteOneReply(discord.ui.View):
    def __init__(self, interaction, user, message_id, options_disabled: bool, multiple_options_view=None, multiple_options_select=None, options=None) -> None:
        super().__init__(timeout=None)
        self.interaction = interaction
        self.user = user
        self.message_id = message_id
        self.multiple_options_view = multiple_options_view
        self.multiple_options_select = multiple_options_select
        self.options = options
        list_button = [i for i in self.children if i.custom_id == 'get_list_back'][0]
        list_button.disabled = options_disabled


    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        message = await self.interaction.original_response()
        await message.edit(view=self)

    @discord.ui.button(label='Да, хочу удалить', custom_id='delete_the_reply', style=discord.ButtonStyle.gray,
                       emoji='\U0001F5D1')
    async def delete_the_reply(self, interaction: discord.Interaction, button):
        await self.disable_all_items()
        conn, cursor = await basevariables.access_db_on_interaction(interaction)
        query = 'DELETE from "public".messages WHERE message_id=%s'
        values = (self.message_id,)
        cursor.execute(query, values)
        conn.commit()
        conn.close()
        await interaction.response.send_message('Ответ удалён', ephemeral=True)

    @discord.ui.button(label='Не, не буду удалять', custom_id='dont_delete_the_reply', style=discord.ButtonStyle.danger,
                       emoji='\U0001F64C')
    async def dont_delete_the_reply(self, interaction: discord.Interaction, button):
        await self.disable_all_items()
        await interaction.response.send_message('Оке, тогда я ничего не меняю', ephemeral=True)


    @discord.ui.button(label='Верни список, сук', custom_id='get_list_back', style=discord.ButtonStyle.success, emoji='\U0001F621')
    async def get_list_back(self, interaction: discord.Interaction, button):
        await self.disable_all_items()
        view = self.multiple_options_view(interaction)
        select = self.multiple_options_select(interaction, view)
        select.options = self.options
        view.add_item(select)
        await interaction.response.send_message(f'Варианта больше одного, выдаём выпадашку',
                                                view=view, ephemeral=True)

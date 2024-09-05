import discord.ui

from src.misc_files import basevariables


class DeleteOneReply(discord.ui.View):
    def __init__(self, interaction, user, message_id) -> None:
        super().__init__(timeout=None)
        self.interaction = interaction
        self.user = user
        self.message_id = message_id

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

import uuid

import discord
import discord.ui
import pytz

from misc_files import basevariables


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


class DeleteReplyMultiple(discord.ui.View):
    def __init__(self, interaction) -> None:
        super().__init__(timeout=None)
        self.interaction = interaction

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        message = await self.interaction.original_response()
        await message.edit(view=self)


class DeleteReplyMultipleSelect(discord.ui.Select):
    def __init__(self, interaction, view) -> None:
        super().__init__(options=[],
                         custom_id='select_replies_to_delete',
                         placeholder='Выбери нужный ответ',
                         max_values=1,
                         disabled=False)
        self.interaction = interaction
        self.info = view

    async def callback(self, interaction: discord.Interaction):
        await DeleteReplyMultiple.disable_all_items(self.info)
        message_id_str = self.values[0]
        message_id = uuid.UUID(message_id_str)
        conn, cursor = await basevariables.access_db_on_interaction(interaction)
        query = 'SELECT request_phrase, respond_phrase, added_by_name, added_at, message_id from "public".messages WHERE message_id=%s'
        values = (message_id,)
        cursor.execute(query, values)
        results = cursor.fetchall()
        for item in results:
            request_phrase = item['request_phrase']
            respond_phrase = item['respond_phrase']
            added_by_name = item['added_by_name']
            added_at_base = item['added_at']
            added_at = added_at_base.astimezone(pytz.timezone('EUROPE/MOSCOW')).strftime('%Y-%m-%d %H:%M:%S %Z%z')
            view = DeleteOneReply(interaction, interaction.user, message_id)
            embed = discord.Embed(title=f'Выбранный тобой ответ')
            embed.add_field(name='Триггер:', value=request_phrase)
            embed.add_field(name='Ответ:', value=respond_phrase, inline=False)
            embed.add_field(name='Кто добавил:', value=added_by_name)
            embed.add_field(name='Когда добавил (МСК время):', value=added_at)
            await interaction.response.send_message(view=view, embed=embed, ephemeral=True)

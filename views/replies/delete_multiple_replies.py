import uuid

import discord
import discord.ui
import pytz

from misc_files import basevariables
from views.replies.delete_one_reply import DeleteOneReply


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

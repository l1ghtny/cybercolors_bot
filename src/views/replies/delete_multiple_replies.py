import uuid

import discord
import discord.ui
import pytz
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import engine
from src.db.models import Triggers, Replies, GlobalUser
from src.views.replies.delete_one_reply import DeleteOneReply


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
        await self.info.disable_all_items()
        trigger_id_str = self.values[0]
        trigger_id = uuid.UUID(trigger_id_str)
        
        async with AsyncSession(engine) as session:
            # Join Triggers and Replies
            statement = select(Triggers, Replies).join(Replies).where(Triggers.id == trigger_id)
            result = await session.exec(statement)
            row = result.first()
            
            if row:
                trigger, reply = row
                # Get creator info from GlobalUser
                creator = await session.get(GlobalUser, reply.created_by_id)
                creator_name = creator.username if creator else "Unknown"
                
                added_at_base = reply.created_at
                added_at = added_at_base.astimezone(pytz.timezone('EUROPE/MOSCOW')).strftime('%Y-%m-%d %H:%M:%S %Z%z')
                
                view = DeleteOneReply(interaction, interaction.user, trigger_id, False, DeleteReplyMultiple, DeleteReplyMultipleSelect, self.options)
                embed = discord.Embed(title=f'Выбранный тобой триггер', color=discord.Color.blue())
                embed.add_field(name='Триггер:', value=trigger.message)
                embed.add_field(name='Ответ:', value=reply.bot_reply, inline=False)
                embed.add_field(name='Кто добавил:', value=creator_name)
                embed.add_field(name='Когда добавил (МСК время):', value=added_at)
                await interaction.response.send_message(view=view, embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message("Триггер не найден.", ephemeral=True)

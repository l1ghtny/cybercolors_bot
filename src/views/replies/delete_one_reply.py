import discord.ui
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import engine
from src.db.models import Triggers, Replies


class DeleteOneReply(discord.ui.View):
    def __init__(self, interaction, user, trigger_id, options_disabled: bool, multiple_options_view=None, multiple_options_select=None, options=None) -> None:
        super().__init__(timeout=None)
        self.interaction = interaction
        self.user = user
        self.trigger_id = trigger_id
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
        async with AsyncSession(engine) as session:
            # 1. Get the trigger
            trigger = await session.get(Triggers, self.trigger_id)
            if trigger:
                reply_id = trigger.reply_id
                # 2. Delete the trigger
                await session.delete(trigger)
                await session.flush()
                
                # 3. Check if any other triggers point to this reply
                other_triggers_statement = select(Triggers).where(Triggers.reply_id == reply_id)
                other_triggers_result = await session.exec(other_triggers_statement)
                if not other_triggers_result.first():
                    # No more triggers for this reply, delete it too
                    reply = await session.get(Replies, reply_id)
                    if reply:
                        await session.delete(reply)
                
                await session.commit()
                await interaction.response.send_message('Триггер удалён', ephemeral=True)
            else:
                await interaction.response.send_message('Триггер уже был удалён или не существует', ephemeral=True)

    @discord.ui.button(label='Не, не буду удалять', custom_id='dont_delete_the_reply', style=discord.ButtonStyle.danger,
                       emoji='\U0001F64C')
    async def dont_delete_the_reply(self, interaction: discord.Interaction, button):
        await self.disable_all_items()
        await interaction.response.send_message('Оке, тогда я ничего не меняю', ephemeral=True)


    @discord.ui.button(label='Верни список', custom_id='get_list_back', style=discord.ButtonStyle.success, emoji='\U0001F621')
    async def get_list_back(self, interaction: discord.Interaction, button):
        await self.disable_all_items()
        view = self.multiple_options_view(interaction)
        select_module = self.multiple_options_select(interaction, view)
        select_module.options = self.options
        view.add_item(select_module)
        await interaction.response.send_message(f'Варианта больше одного, выдаём выпадашку',
                                                view=view, ephemeral=True)

import discord.ui


class Roles2(discord.ui.RoleSelect):
    def __init__(self, command_user):
        super().__init__(custom_id='roles_new', placeholder='Выбери роли', min_values=1, max_values=5, disabled=False)
        self.user = command_user

    async def callback(self, interaction: discord.Interaction):
        if self.user == interaction.user:
            await DropDownRoles.disable_all_items(self.info)
            await interaction.response.defer(thinking=True)
            selected_roles = self.values
            already_assigned = []
            new_roles = []
            forbidden = []
            selected_roles.sort()
            for item in selected_roles:
                if item.position > interaction.user.top_role.position:
                    forbidden.append(item.name)
                else:
                    if item in interaction.user.roles:
                        already_assigned.append(item.name)
                    if item not in interaction.user.roles:
                        await interaction.user.add_roles(item, reason='Roles added by command')
                        new_roles.append(item.name)
            if not forbidden:
                if not already_assigned:
                    await interaction.followup.send(f'Были добавлены роли:{new_roles}')
                if already_assigned != [] and new_roles != []:
                    await interaction.followup.send(
                        f'Были добавлены роли:{new_roles}, а эти роли у тебя уже есть:{already_assigned}')
                if already_assigned != [] and new_roles == []:
                    await interaction.followup.send(f'У тебя уже есть {already_assigned}')
            if forbidden:
                if already_assigned == [] and new_roles != []:
                    await interaction.followup.send(
                        f'Были добавлены роли:{new_roles}. Роли {forbidden} тебе не доступны.')
                if already_assigned != [] and new_roles != []:
                    await interaction.followup.send(
                        f'Были добавлены роли:{new_roles}, а эти роли у тебя уже есть:{already_assigned}. Роли {forbidden} тебе не доступны.')
                if already_assigned != [] and new_roles == []:
                    await interaction.followup.send(
                        f'У тебя уже есть {already_assigned}. Роли {forbidden} тебе не доступны.')
                if already_assigned == [] and new_roles == []:
                    await interaction.followup.send(f'Роли {forbidden} тебе не доступны')
        else:
            await interaction.response.send_message('Это не твоя менюшка', ephemeral=True)


class DropDownRoles(discord.ui.View):
    def __init__(self, user) -> None:
        super().__init__(timeout=None)
        roles = Roles2(user)
        roles.info = self
        self.add_item(roles)

    async def disable_all_items(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

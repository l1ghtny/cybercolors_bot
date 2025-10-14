import discord
from discord import app_commands

from src.db.database import get_session
from src.db.models import ModerationAction, ActionType
from src.modules.moderation.moderation import check_if_user_exists


@app_commands.command(name='warn', description='Warns a user and logs the action.')
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    """Warns a user and logs the action."""
    await interaction.response.defer(ephemeral=False)

    # 1. Perform the Discord action (e.g., send a DM to the user)
    try:
        await user.send(f"You have been warned in {interaction.guild.name} for the following reason: {reason}")
    except discord.Forbidden:
        await interaction.followup.send("Could not DM the user, but the warning is logged.")
    user_ready_for_warn = await check_if_user_exists(user, interaction.guild)
    if user_ready_for_warn:
        # 2. Log the action to your database
        async with get_session() as session:
            new_warning = ModerationAction(
                action_type=ActionType.WARN,
                server_id=interaction.guild.id,
                target_user_id=user.id,
                moderator_user_id=interaction.user.id,
                reason=reason,
                is_active=True  # Warnings are always "active"
            )
            session.add(new_warning)
            await session.commit()
    else:
        await interaction.followup.send(f'Что-то пошло не так, не получилось добавить пользователя в базу сервера', ephemeral=True)

    await interaction.followup.send(f"Successfully warned {user.mention} and logged the action.", ephemeral=False)

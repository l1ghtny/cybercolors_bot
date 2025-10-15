import os
from datetime import datetime
import discord
from discord import app_commands
import httpx


@app_commands.command(name='warn', description='Warns a user and logs the action.')
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    """Handles the /warn command, sends a DM, and calls the internal API to log the warning."""
    await interaction.response.defer(ephemeral=True)

    # 1. Perform Discord-specific actions
    try:
        dm_message = f"You have been warned in **{interaction.guild.name}** for the following reason:\n> {reason}"
        await user.send(dm_message)
    except discord.Forbidden:
        # Inform the moderator but continue with logging the action
        await interaction.followup.send("Could not send a DM to the user, but the warning will still be logged.", ephemeral=True)

    # 2. Prepare data for the API POST request
    # Ensure you have BOT_API_URL in your environment variables (e.g., http://127.0.0.1:8000)
    api_url = f"{os.getenv('BOT_API_URL')}/moderation/"
    payload = {
        "action_type": "warn",
        "moderator_user_id": interaction.user.id,
        "reason": reason,
        "target_user_id": user.id,
        "target_user_name": user.name,
        "target_user_joined_at": user.joined_at.isoformat(),
        "target_user_server_nickname": user.nick,
        "server_id": interaction.guild.id,
        "server_name": interaction.guild.name,
    }

    # 3. Make the POST request to the internal API
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()  # Raises an exception for 4xx or 5xx status codes

        await interaction.followup.send(f"Successfully warned {user.mention} and logged the action.", ephemeral=False)

    except httpx.RequestError as e:
        await interaction.followup.send(f"An error occurred while communicating with the API: {e}", ephemeral=True)
        print(f"API Request Error: {e}") # For debugging
    except httpx.HTTPStatusError as e:
        await interaction.followup.send(f"The API responded with an error: {e.response.status_code} - {e.response.text}", ephemeral=True)
        print(f"API Status Error: {e.response.text}") # For debugging

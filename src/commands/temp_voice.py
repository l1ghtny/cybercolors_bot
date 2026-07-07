import discord
from discord import app_commands
from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import ServerTempVoiceSettings, TempVoiceLog, VoiceChannel
from src.modules.on_voice_state_processing.create_voice_channel import temp_voice_owner_has_allowed_role


async def _active_owned_temp_channel(
    interaction: discord.Interaction,
) -> tuple[discord.VoiceChannel, ServerTempVoiceSettings, VoiceChannel] | None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
        return None
    voice_state = interaction.user.voice
    if voice_state is None or voice_state.channel is None:
        await interaction.followup.send("Join your temporary voice channel first.", ephemeral=True)
        return None
    if not isinstance(voice_state.channel, discord.VoiceChannel):
        await interaction.followup.send("This command only works in temporary voice channels.", ephemeral=True)
        return None

    async with get_async_session() as session:
        settings = await session.get(ServerTempVoiceSettings, interaction.guild.id)
        active_channel = await session.get(VoiceChannel, (interaction.guild.id, voice_state.channel.id))

    if settings is None or not settings.enabled:
        await interaction.followup.send("Temporary voice channels are not enabled here.", ephemeral=True)
        return None
    if active_channel is None or active_channel.owner_user_id != interaction.user.id:
        await interaction.followup.send("Only the creator of this temporary channel can use this control.", ephemeral=True)
        return None
    if not temp_voice_owner_has_allowed_role(interaction.user, settings):
        await interaction.followup.send("Your roles do not allow temporary channel owner controls here.", ephemeral=True)
        return None
    return voice_state.channel, settings, active_channel


@app_commands.command(name="rename", description="Rename your temporary voice channel.")
async def temp_voice_rename(interaction: discord.Interaction, name: app_commands.Range[str, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    resolved = await _active_owned_temp_channel(interaction)
    if resolved is None:
        return
    channel, settings, active_channel = resolved
    if not settings.owner_rename_enabled:
        await interaction.followup.send("Temporary channel rename control is disabled here.", ephemeral=True)
        return

    cleaned_name = " ".join(str(name).strip().split())[:100]
    if not cleaned_name:
        await interaction.followup.send("Channel name cannot be blank.", ephemeral=True)
        return

    try:
        await channel.edit(
            name=cleaned_name,
            reason=f"Temporary voice owner rename by {interaction.user} ({interaction.user.id})",
        )
    except (discord.Forbidden, discord.HTTPException) as error:
        await interaction.followup.send(f"Could not rename the channel: {error}", ephemeral=True)
        return

    async with get_async_session() as session:
        stored_channel = await session.get(VoiceChannel, (interaction.guild.id, active_channel.channel_id))
        if stored_channel is not None:
            stored_channel.channel_name = cleaned_name
            session.add(stored_channel)
        active_log = (
            await session.exec(
                select(TempVoiceLog).where(
                    TempVoiceLog.server_id == interaction.guild.id,
                    TempVoiceLog.channel_id == active_channel.channel_id,
                    TempVoiceLog.deleted_at.is_(None),
                )
            )
        ).first()
        if active_log is not None:
            active_log.channel_name = cleaned_name
            session.add(active_log)
        await session.commit()

    await interaction.followup.send(f"Temporary channel renamed to `{cleaned_name}`.", ephemeral=True)


@app_commands.command(name="limit", description="Set the user limit for your temporary voice channel.")
async def temp_voice_limit(interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]):
    await interaction.response.defer(ephemeral=True)
    resolved = await _active_owned_temp_channel(interaction)
    if resolved is None:
        return
    channel, settings, _active_channel = resolved
    if not settings.owner_user_limit_enabled:
        await interaction.followup.send("Temporary channel user-limit control is disabled here.", ephemeral=True)
        return

    try:
        await channel.edit(
            user_limit=int(limit),
            reason=f"Temporary voice owner limit by {interaction.user} ({interaction.user.id})",
        )
    except (discord.Forbidden, discord.HTTPException) as error:
        await interaction.followup.send(f"Could not update the user limit: {error}", ephemeral=True)
        return

    label = "unlimited" if int(limit) == 0 else str(int(limit))
    await interaction.followup.send(f"Temporary channel user limit set to `{label}`.", ephemeral=True)
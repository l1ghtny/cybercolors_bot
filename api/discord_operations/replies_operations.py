import aiohttp

from api.services.discord_profiles import get_profile, profile_key_for_server_id, runtime_bot_profile_key


async def get_user_by_id(user_id: int, *, server_id: int | None = None):
    profile_key = profile_key_for_server_id(server_id) if server_id is not None else runtime_bot_profile_key()
    bot_token = get_profile(profile_key).bot_token
    if not bot_token:
        raise RuntimeError("DISCORD_TOKEN is not set")

    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bot {bot_token}"
        }
        user_info = await session.get(f"https://discord.com/api/v10/users/{user_id}", headers=headers)
        payload = await user_info.json()
        if user_info.status >= 400:
            raise RuntimeError(f"Discord API error {user_info.status}: {payload}")
        return payload

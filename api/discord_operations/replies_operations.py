import aiohttp

from api.routers.auth import bot_token


async def get_user_by_id(user_id: int):
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

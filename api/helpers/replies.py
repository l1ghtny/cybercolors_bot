from api.discord_operations.replies_operations import get_user_by_id


async def enrich_user_data(user_id):
    user_info = await get_user_by_id(user_id)
    user_data = {
        "avatar_url": f"https://cdn.discordapp.com/avatars/{user_info['id']}/{user_info['avatar']}.png",
        "global_name": user_info["global_name"]
    }
    return user_data

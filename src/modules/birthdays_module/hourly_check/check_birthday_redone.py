import datetime
import random

import aiohttp
import discord
import requests
from sqlmodel import select
from sqlalchemy.orm import selectinload
from jinja2 import Template


from src.db.database import get_session
from src.db.models import Birthday, Congratulation, User, Server, GlobalUser


from src.misc_files import basevariables
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def check_birthday_new(client: discord.Client):
    """
    Checks for user birthdays based on their timezone and sends a greeting.
    """
    key = basevariables.t_key  # Assuming t_key is still needed for the API
    timezones_response = await get_all_timezones(key)

    if timezones_response.get('status') != 'OK':
        logger.error("TimezoneDB API returned a non-OK status.")
        return

    zones = timezones_response.get('zones', [])

    async with get_session() as session:
        # Efficient query for all birthdays and preload related memberships and server data
        statement = select(Birthday).options(
            selectinload(Birthday.global_user)
                .selectinload(GlobalUser.memberships)
                .selectinload(User.server)
        )
        result = await session.exec(statement)
        all_birthdays = result.all()

        for birthday in all_birthdays:
            gu = birthday.global_user
            if not birthday.timezone:
                logger.info(f"User {gu.discord_id} has not set a timezone.")
                continue

            # Iterate through each server membership for this global user
            for membership in gu.memberships:
                server = membership.server  # Access the server through the membership relationship
                # TODO: create a mechanism for managing the fact that the bot was deleted from a server
                guild = await client.fetch_guild(server.server_id)
                if not guild or not server.birthday_role_id:
                    logger.warning(f"Guild or birthday role not found for server ID: {server.server_id}")
                    continue

                member = await guild.fetch_member(membership.user_id)
                if not member:
                    logger.info(f"User {membership.user_id} is no longer a member of guild {guild.name}")
                    continue

                # --- Date and Time Logic ---
                user_timestamp = await get_user_time(birthday.timezone, zones)
                if user_timestamp is None:
                    continue

                user_current_time = datetime.datetime.fromtimestamp(user_timestamp, datetime.timezone.utc)
                birthday_date = datetime.datetime(user_current_time.year, int(birthday.month), birthday.day, hour=0, minute=0)

                logger.info(
                    f"Checking {member.name}: Birthday is {birthday_date.date()}, user's current time is {user_current_time}")

                # --- Birthday Check ---
                if user_current_time.date() == birthday_date.date() and user_current_time.hour == birthday_date.hour or user_current_time.date() == birthday_date.date() and birthday.role_added_at is None:
                    logger.info(f"It's {member.name}'s birthday! 🎉")

                    # 2. Query for congratulation messages for the specific server
                    congrats_statement = select(Congratulation).where(Congratulation.server_id == server.server_id)
                    congrats_result = await session.exec(congrats_statement)
                    greetings = congrats_result.all()

                    if not greetings:
                        logger.warning(f"No congratulations messages found for server {server.server_name}")
                        continue

                    # --- Send Birthday Message ---
                    greeting = random.choice(greetings)
                    template = Template(greeting.bot_message)
                    embed_description = template.render(user_mention=member.mention)

                    embed = discord.Embed(colour=discord.Colour.dark_gold(), description=embed_description)

                    channel = await client.fetch_channel(server.birthday_channel_id)
                    if channel:
                        await channel.send(embed=embed)

                    # --- Add Role and Update Database ---
                    birthday_role = guild.get_role(server.birthday_role_id)
                    if birthday_role:
                        await member.add_roles(birthday_role)
                        # 3. Update the database record using the model object
                        birthday.role_added_at = datetime.datetime.now(datetime.timezone.utc)
                        await session.merge(birthday)
                        await session.commit()
                        await session.refresh(birthday)
                        logger.info(
                            f"Birthday role added to {member.name} and timestamp updated to {birthday.role_added_at}"
                        )
                        logger.info(f"Added birthday role to {member.name} and updated timestamp.")
                    else:
                        logger.warning(
                            f"Could not find birthday role with ID {server.birthday_role_id} in guild {guild.name}")

    logger.info("Finished birthday check.")


async def get_all_timezones(key):
    request_url = f'http://api.timezonedb.com/v2.1/list-time-zone?key={key}&format=json'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(request_url) as response:
                response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
                return await response.json()
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching timezones: {e}")
        return {}


async def get_user_time(timezone, zones):
    for item in zones:
        if item.get('zoneName') == timezone:
            return item.get('timestamp')
    return None

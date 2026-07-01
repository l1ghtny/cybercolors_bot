import datetime
import random
import re

import discord
import pytz
from sqlalchemy.orm import selectinload
from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import Birthday, Congratulation, GlobalUser, User, utcnow_utc_tz
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")

JINJA_STYLE_MENTION_PLACEHOLDER = re.compile(r"\{\{\s*user_mention\s*\}\}")
RAW_MENTION_PLACEHOLDER = re.compile(r"(?<!\w)user_mention(?!\w)")


def render_celebration_message(template_text: str, user_mention: str) -> str:
    """
    Render celebration text by replacing allowed mention placeholders
    without evaluating template expressions.
    """
    rendered = JINJA_STYLE_MENTION_PLACEHOLDER.sub(user_mention, template_text)
    rendered = rendered.replace("{user_mention}", user_mention)
    rendered = rendered.replace("$user_mention", user_mention)
    rendered = RAW_MENTION_PLACEHOLDER.sub(user_mention, rendered)
    return rendered


async def check_birthday_new(client: discord.Client):
    """
    Checks for user birthdays based on their timezone and sends a greeting.
    """
    async with get_async_session() as session:
        statement = select(Birthday).options(
            selectinload(Birthday.global_user).selectinload(GlobalUser.memberships).selectinload(User.server)
        )
        result = await session.exec(statement)
        all_birthdays = result.all()

        for birthday in all_birthdays:
            gu = birthday.global_user
            if not birthday.timezone:
                logger.info(f"User {gu.discord_id} has not set a timezone.")
                continue

            for membership in gu.memberships:
                server = membership.server
                guild = await client.fetch_guild(server.server_id)
                if not guild or not server.birthday_role_id:
                    logger.warning(f"Guild or birthday role not found for server ID: {server.server_id}")
                    continue

                member = await guild.fetch_member(membership.user_id)
                if not member:
                    logger.info(f"User {membership.user_id} is no longer a member of guild {guild.name}")
                    continue

                user_current_time = get_user_current_time(birthday.timezone)
                if user_current_time is None:
                    continue

                birthday_date = datetime.date(user_current_time.year, int(birthday.month), birthday.day)

                logger.info(
                    f"Checking {member.name}: Birthday is {birthday_date}, user's current time is {user_current_time}"
                )

                is_birthday_day = user_current_time.date() == birthday_date
                is_midnight_user_tz = user_current_time.hour == 0
                role_not_assigned_yet = birthday.role_added_at is None
                should_celebrate = is_birthday_day and (is_midnight_user_tz or role_not_assigned_yet)

                if should_celebrate:
                    logger.info(f"It's {member.name}'s birthday! 🎉")

                    congrats_statement = select(Congratulation).where(Congratulation.server_id == server.server_id)
                    congrats_result = await session.exec(congrats_statement)
                    greetings = congrats_result.all()

                    if not greetings:
                        logger.warning(f"No congratulations messages found for server {server.server_name}")
                        continue

                    greeting = random.choice(greetings)
                    embed_description = render_celebration_message(greeting.bot_message, member.mention)
                    embed = discord.Embed(colour=discord.Colour.dark_gold(), description=embed_description)

                    channel = await client.fetch_channel(server.birthday_channel_id)
                    if channel:
                        await channel.send(embed=embed)

                    birthday_role = guild.get_role(server.birthday_role_id)
                    if birthday_role:
                        await member.add_roles(birthday_role)
                        birthday.role_added_at = utcnow_utc_tz()
                        await session.merge(birthday)
                        await session.commit()
                        await session.refresh(birthday)
                        logger.info(
                            f"Birthday role added to {member.name} and timestamp updated to {birthday.role_added_at}"
                        )
                    else:
                        logger.warning(
                            f"Could not find birthday role with ID {server.birthday_role_id} in guild {guild.name}"
                        )

    logger.info("Finished birthday check.")


def get_user_current_time(timezone_name: str) -> datetime.datetime | None:
    try:
        user_timezone = pytz.timezone(timezone_name)
    except pytz.UnknownTimeZoneError:
        logger.warning("Skipping birthday check with invalid timezone: %s", timezone_name)
        return None
    return datetime.datetime.now(tz=user_timezone)

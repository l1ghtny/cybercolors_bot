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


async def mark_birthday_processed(session, birthday: Birthday) -> None:
    birthday.role_added_at = utcnow_utc_tz()
    await session.merge(birthday)
    await session.commit()
    await session.refresh(birthday)


async def send_birthday_greeting(client: discord.Client, server, embed: discord.Embed) -> bool:
    if not server.birthday_channel_id:
        logger.warning("Birthday channel is not configured for server ID: %s", server.server_id)
        return False

    try:
        channel = await client.fetch_channel(server.birthday_channel_id)
        await channel.send(embed=embed)
        return True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
        logger.warning(
            "Could not send birthday greeting for server ID %s in channel ID %s: %s",
            server.server_id,
            server.birthday_channel_id,
            error,
        )
        return False


async def add_birthday_role(member, birthday_role, server_id: int) -> bool:
    try:
        await member.add_roles(birthday_role)
        return True
    except (discord.Forbidden, discord.HTTPException) as error:
        logger.warning(
            "Could not add birthday role ID %s to user ID %s in server ID %s: %s",
            birthday_role.id,
            member.id,
            server_id,
            error,
        )
        return False


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
                try:
                    guild = await client.fetch_guild(server.server_id)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
                    logger.warning("Could not fetch guild ID %s: %s", server.server_id, error)
                    continue

                if not guild or not server.birthday_role_id:
                    logger.warning(f"Guild or birthday role not found for server ID: {server.server_id}")
                    continue

                try:
                    member = await guild.fetch_member(membership.user_id)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
                    logger.warning(
                        "Could not fetch member ID %s in guild ID %s: %s",
                        membership.user_id,
                        server.server_id,
                        error,
                    )
                    continue

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

                    greeting_sent = await send_birthday_greeting(client, server, embed)
                    if greeting_sent:
                        await mark_birthday_processed(session, birthday)

                    birthday_role = guild.get_role(server.birthday_role_id)
                    if birthday_role:
                        role_added = await add_birthday_role(member, birthday_role, server.server_id)
                        if role_added:
                            if not greeting_sent:
                                await mark_birthday_processed(session, birthday)
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

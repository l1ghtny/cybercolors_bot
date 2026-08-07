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


async def persist_birthday_membership_state(
    session,
    membership: User,
    *,
    greeted: bool,
    role_added: bool,
) -> None:
    processed_at = utcnow_utc_tz()
    if greeted:
        membership.birthday_greeted_at = processed_at
    if role_added:
        membership.birthday_role_added_at = processed_at
    await session.merge(membership)
    await session.commit()
    await session.refresh(membership)


def birthday_greeting_was_sent_today(
    greeted_at: datetime.datetime | None,
    current_time: datetime.datetime,
) -> bool:
    if greeted_at is None:
        return False
    if greeted_at.tzinfo is None:
        greeted_at = greeted_at.replace(tzinfo=datetime.timezone.utc)
    return greeted_at.astimezone(current_time.tzinfo).date() == current_time.date()


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


async def check_birthday_new(
    client: discord.Client,
    *,
    guild_ids: set[int] | None = None,
):
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
                if guild_ids is not None and int(server.server_id) not in guild_ids:
                    continue
                try:
                    guild = await client.fetch_guild(server.server_id)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
                    logger.warning("Could not fetch guild ID %s: %s", server.server_id, error)
                    continue

                if not guild:
                    logger.warning(f"Guild not found for server ID: {server.server_id}")
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
                greeting_already_sent = birthday_greeting_was_sent_today(
                    membership.birthday_greeted_at,
                    user_current_time,
                )
                should_send_greeting = is_birthday_day and not greeting_already_sent
                should_add_role = (
                    is_birthday_day
                    and server.birthday_role_id is not None
                    and membership.birthday_role_added_at is None
                )

                if should_send_greeting or should_add_role:
                    logger.info(f"It's {member.name}'s birthday! 🎉")

                greeting_sent = False
                if should_send_greeting:
                    congrats_statement = select(Congratulation).where(Congratulation.server_id == server.server_id)
                    congrats_result = await session.exec(congrats_statement)
                    greetings = congrats_result.all()

                    if not greetings:
                        logger.warning(f"No congratulations messages found for server {server.server_name}")
                    else:
                        greeting = random.choice(greetings)
                        embed_description = render_celebration_message(greeting.bot_message, member.mention)
                        embed = discord.Embed(colour=discord.Colour.dark_gold(), description=embed_description)
                        greeting_sent = await send_birthday_greeting(client, server, embed)

                role_added = False
                if should_add_role:
                    birthday_role = guild.get_role(server.birthday_role_id)
                    if birthday_role:
                        role_added = await add_birthday_role(member, birthday_role, server.server_id)
                        if role_added:
                            logger.info(
                                "Birthday role added to %s in server ID %s",
                                member.name,
                                server.server_id,
                            )
                    else:
                        logger.warning(
                            f"Could not find birthday role with ID {server.birthday_role_id} in guild {guild.name}"
                        )

                if greeting_sent or role_added:
                    await persist_birthday_membership_state(
                        session,
                        membership,
                        greeted=greeting_sent,
                        role_added=role_added,
                    )

    logger.info("Finished birthday check.")


def get_user_current_time(timezone_name: str) -> datetime.datetime | None:
    try:
        user_timezone = pytz.timezone(timezone_name)
    except pytz.UnknownTimeZoneError:
        logger.warning("Skipping birthday check with invalid timezone: %s", timezone_name)
        return None
    return datetime.datetime.now(tz=user_timezone)

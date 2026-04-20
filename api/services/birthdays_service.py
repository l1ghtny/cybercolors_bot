from fastapi import HTTPException, status
from sqlalchemy import and_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.birthdays import BirthdayReadModel, BirthdayWriteModel, ServerBirthdayUserModel
from api.models.birthday_settings import BirthdayActorModel, BirthdaySettingsModel, CelebrationMessageReadModel
from api.services.discord_guilds import fetch_guild_roles
from src.db.models import Birthday, Congratulation, GlobalUser, Server, User

MENTION_PLACEHOLDER = "user_mention"


def display_name(user: User, global_user: GlobalUser) -> str:
    if user.server_nickname:
        return user.server_nickname
    if global_user.username:
        return global_user.username
    return str(user.user_id)


def to_birthday_read(user: User, global_user: GlobalUser, birthday: Birthday) -> BirthdayReadModel:
    return BirthdayReadModel(
        user_id=str(user.user_id),
        username=global_user.username,
        server_nickname=user.server_nickname,
        display_name=display_name(user, global_user),
        avatar_hash=global_user.avatar_hash,
        day=birthday.day,
        month=birthday.month,
        timezone=birthday.timezone,
        role_added_at=birthday.role_added_at,
    )


def to_settings_model(server: Server, birthday_role_name: str | None = None) -> BirthdaySettingsModel:
    return BirthdaySettingsModel(
        server_id=str(server.server_id),
        server_name=server.server_name,
        birthday_channel_id=str(server.birthday_channel_id) if server.birthday_channel_id else None,
        birthday_channel_name=server.birthday_channel_name,
        birthday_role_id=str(server.birthday_role_id) if server.birthday_role_id else None,
        birthday_role_name=birthday_role_name,
    )


def to_celebration_message_read(
    message: Congratulation,
    global_user: GlobalUser | None,
    membership: User | None,
) -> CelebrationMessageReadModel:
    username = global_user.username if global_user else None
    resolved_display_name = membership.server_nickname if membership and membership.server_nickname else username
    if not resolved_display_name:
        resolved_display_name = str(message.added_by_user_id)

    return CelebrationMessageReadModel(
        id=str(message.id),
        server_id=str(message.server_id),
        message=message.bot_message,
        added_at=message.added_at,
        added_by_user_id=str(message.added_by_user_id),
        added_by_username=username,
        added_by=BirthdayActorModel(
            user_id=str(message.added_by_user_id),
            username=username,
            server_nickname=membership.server_nickname if membership else None,
            display_name=resolved_display_name,
            avatar_hash=global_user.avatar_hash if global_user else None,
        ),
    )


def validate_placeholder(template: str):
    if MENTION_PLACEHOLDER not in template:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Celebration message must contain the placeholder variable "
                "`{{ user_mention }}`"
            ),
        )


async def get_member_or_404(server_id: int, user_id: int, session: AsyncSession) -> tuple[User, GlobalUser]:
    statement = (
        select(User, GlobalUser)
        .join(GlobalUser, GlobalUser.discord_id == User.user_id)
        .where(
            User.server_id == server_id,
            User.user_id == user_id,
            User.is_member.is_(True),
        )
    )
    member_row = (await session.exec(statement)).first()
    if not member_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not an active member of this server",
        )
    return member_row


async def get_or_create_server(server_id: int, session: AsyncSession, server_name: str | None = None) -> Server:
    server = await session.get(Server, server_id)
    if server:
        if server_name:
            server.server_name = server_name
            session.add(server)
        return server

    server = Server(server_id=server_id, server_name=server_name)
    session.add(server)
    await session.flush()
    return server


async def resolve_birthday_role_name(server_id: int, role_id: int | None) -> str | None:
    if not role_id:
        return None
    try:
        roles = await fetch_guild_roles(server_id)
    except Exception:
        return None

    for role in roles:
        raw_id = role.get("id")
        if raw_id is not None and int(raw_id) == role_id:
            return role.get("name")
    return None


async def list_birthdays(session: AsyncSession, server_id: int) -> list[BirthdayReadModel]:
    statement = (
        select(User, GlobalUser, Birthday)
        .join(GlobalUser, GlobalUser.discord_id == User.user_id)
        .join(Birthday, Birthday.user_id == User.user_id)
        .where(User.server_id == server_id, User.is_member.is_(True))
        .order_by(Birthday.month, Birthday.day, User.server_nickname, GlobalUser.username)
    )
    rows = (await session.exec(statement)).all()
    return [to_birthday_read(user, global_user, birthday) for user, global_user, birthday in rows]


async def list_server_birthday_users(session: AsyncSession, server_id: int) -> list[ServerBirthdayUserModel]:
    statement = (
        select(User, GlobalUser, Birthday)
        .join(GlobalUser, GlobalUser.discord_id == User.user_id)
        .outerjoin(Birthday, Birthday.user_id == User.user_id)
        .where(User.server_id == server_id, User.is_member.is_(True))
        .order_by(User.server_nickname, GlobalUser.username)
    )
    rows = (await session.exec(statement)).all()

    users: list[ServerBirthdayUserModel] = []
    for user, global_user, birthday in rows:
        users.append(
            ServerBirthdayUserModel(
                user_id=str(user.user_id),
                username=global_user.username,
                server_nickname=user.server_nickname,
                display_name=display_name(user, global_user),
                avatar_hash=global_user.avatar_hash,
                has_birthday=birthday is not None,
                birthday=(
                    BirthdayWriteModel(day=birthday.day, month=birthday.month, timezone=birthday.timezone)
                    if birthday
                    else None
                ),
            )
        )
    return users


async def list_celebration_messages(session: AsyncSession, server_id: int) -> list[CelebrationMessageReadModel]:
    statement = (
        select(Congratulation, GlobalUser, User)
        .outerjoin(GlobalUser, GlobalUser.discord_id == Congratulation.added_by_user_id)
        .outerjoin(
            User,
            and_(
                User.user_id == Congratulation.added_by_user_id,
                User.server_id == Congratulation.server_id,
            ),
        )
        .where(Congratulation.server_id == server_id)
        .order_by(Congratulation.added_at.desc())
    )
    rows = (await session.exec(statement)).all()
    return [to_celebration_message_read(message, global_user, membership) for message, global_user, membership in rows]

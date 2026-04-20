from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.birthdays import (
    BirthdayCreateModel,
    BirthdayReadModel,
    BirthdayWriteModel,
    ServerBirthdayUserModel,
)
from api.models.birthday_settings import (
    BirthdayActorModel,
    BirthdayChannelUpdateModel,
    BirthdayRoleUpdateModel,
    BirthdaySettingsModel,
    CelebrationMessageCreateModel,
    CelebrationMessageReadModel,
    CelebrationMessageUpdateModel,
)
from src.db.database import get_session
from src.db.models import Birthday, Congratulation, GlobalUser, Server, User

birthdays = APIRouter(prefix="/birthdays", tags=["birthdays"])
MENTION_PLACEHOLDER = "user_mention"


def _display_name(user: User, global_user: GlobalUser) -> str:
    if user.server_nickname:
        return user.server_nickname
    if global_user.username:
        return global_user.username
    return str(user.user_id)


def _to_birthday_read(user: User, global_user: GlobalUser, birthday: Birthday) -> BirthdayReadModel:
    return BirthdayReadModel(
        user_id=str(user.user_id),
        username=global_user.username,
        server_nickname=user.server_nickname,
        display_name=_display_name(user, global_user),
        avatar_hash=global_user.avatar_hash,
        day=birthday.day,
        month=birthday.month,
        timezone=birthday.timezone,
        role_added_at=birthday.role_added_at,
    )


def _to_settings_model(server: Server) -> BirthdaySettingsModel:
    return BirthdaySettingsModel(
        server_id=str(server.server_id),
        server_name=server.server_name,
        birthday_channel_id=str(server.birthday_channel_id) if server.birthday_channel_id else None,
        birthday_channel_name=server.birthday_channel_name,
        birthday_role_id=str(server.birthday_role_id) if server.birthday_role_id else None,
    )


def _to_celebration_message_read(
    message: Congratulation,
    global_user: GlobalUser | None,
    membership: User | None,
) -> CelebrationMessageReadModel:
    username = global_user.username if global_user else None
    display_name = membership.server_nickname if membership and membership.server_nickname else username
    if not display_name:
        display_name = str(message.added_by_user_id)

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
            display_name=display_name,
            avatar_hash=global_user.avatar_hash if global_user else None,
        ),
    )


def _validate_placeholder(template: str):
    if MENTION_PLACEHOLDER not in template:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Celebration message must contain the placeholder variable "
                "`{{ user_mention }}`"
            ),
        )


async def _get_member_or_404(server_id: int, user_id: int, session: AsyncSession) -> tuple[User, GlobalUser]:
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


async def _get_or_create_server(server_id: int, session: AsyncSession, server_name: str | None = None) -> Server:
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


@birthdays.get("/{server_id}", response_model=list[BirthdayReadModel])
async def get_birthdays_by_server_id(server_id: int, session: AsyncSession = Depends(get_session)):
    statement = (
        select(User, GlobalUser, Birthday)
        .join(GlobalUser, GlobalUser.discord_id == User.user_id)
        .join(Birthday, Birthday.user_id == User.user_id)
        .where(User.server_id == server_id, User.is_member.is_(True))
        .order_by(Birthday.month, Birthday.day, User.server_nickname, GlobalUser.username)
    )
    result = (await session.exec(statement)).all()
    return [_to_birthday_read(user, global_user, birthday) for user, global_user, birthday in result]


@birthdays.get("/{server_id}/users", response_model=list[ServerBirthdayUserModel])
async def get_server_users_for_birthday_selector(server_id: int, session: AsyncSession = Depends(get_session)):
    statement = (
        select(User, GlobalUser, Birthday)
        .join(GlobalUser, GlobalUser.discord_id == User.user_id)
        .outerjoin(Birthday, Birthday.user_id == User.user_id)
        .where(User.server_id == server_id, User.is_member.is_(True))
        .order_by(User.server_nickname, GlobalUser.username)
    )
    result = (await session.exec(statement)).all()

    users: list[ServerBirthdayUserModel] = []
    for user, global_user, birthday in result:
        users.append(
            ServerBirthdayUserModel(
                user_id=str(user.user_id),
                username=global_user.username,
                server_nickname=user.server_nickname,
                display_name=_display_name(user, global_user),
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


@birthdays.post("/{server_id}", response_model=BirthdayReadModel, status_code=status.HTTP_201_CREATED)
async def add_birthday_for_server(
    server_id: int,
    body: BirthdayCreateModel,
    session: AsyncSession = Depends(get_session),
):
    user_id = int(body.user_id)
    member, global_user = await _get_member_or_404(server_id, user_id, session)

    existing = await session.get(Birthday, user_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Birthday already exists for this user",
        )

    birthday = Birthday(
        user_id=user_id,
        day=body.day,
        month=body.month,
        timezone=body.timezone,
    )
    session.add(birthday)
    await session.flush()
    await session.refresh(birthday)
    return _to_birthday_read(member, global_user, birthday)


@birthdays.put("/{server_id}/{user_id}", response_model=BirthdayReadModel)
async def update_birthday_for_server_user(
    server_id: int,
    user_id: int,
    body: BirthdayWriteModel,
    session: AsyncSession = Depends(get_session),
):
    member, global_user = await _get_member_or_404(server_id, user_id, session)

    birthday = await session.get(Birthday, user_id)
    if not birthday:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Birthday not found for this user")

    birthday.day = body.day
    birthday.month = body.month
    birthday.timezone = body.timezone
    session.add(birthday)
    await session.flush()
    await session.refresh(birthday)
    return _to_birthday_read(member, global_user, birthday)


@birthdays.get("/{server_id}/settings", response_model=BirthdaySettingsModel)
async def get_birthday_settings(server_id: int, session: AsyncSession = Depends(get_session)):
    server = await session.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server settings not found")
    return _to_settings_model(server)


@birthdays.put("/{server_id}/settings/channel", response_model=BirthdaySettingsModel)
async def update_birthday_channel(
    server_id: int,
    body: BirthdayChannelUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    server = await _get_or_create_server(server_id, session, body.server_name)

    server.birthday_channel_id = int(body.channel_id) if body.channel_id else None
    server.birthday_channel_name = body.channel_name
    session.add(server)
    await session.flush()
    await session.refresh(server)
    return _to_settings_model(server)


@birthdays.put("/{server_id}/settings/role", response_model=BirthdaySettingsModel)
async def update_birthday_role(
    server_id: int,
    body: BirthdayRoleUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    server = await _get_or_create_server(server_id, session, body.server_name)
    server.birthday_role_id = int(body.role_id) if body.role_id else None
    session.add(server)
    await session.flush()
    await session.refresh(server)
    return _to_settings_model(server)


@birthdays.get("/{server_id}/settings/messages", response_model=list[CelebrationMessageReadModel])
async def get_celebration_messages(server_id: int, session: AsyncSession = Depends(get_session)):
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
    result = (await session.exec(statement)).all()
    return [
        _to_celebration_message_read(message, global_user, membership)
        for message, global_user, membership in result
    ]


@birthdays.post(
    "/{server_id}/settings/messages",
    response_model=CelebrationMessageReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def create_celebration_message(
    server_id: int,
    body: CelebrationMessageCreateModel,
    session: AsyncSession = Depends(get_session),
):
    _validate_placeholder(body.message)

    added_by_user_id = int(body.added_by_user_id)
    global_user = await session.get(GlobalUser, added_by_user_id)
    if not global_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Author user not found")

    await _get_or_create_server(server_id, session)
    membership = (
        await session.exec(
            select(User).where(
                User.user_id == added_by_user_id,
                User.server_id == server_id,
            )
        )
    ).first()

    message = Congratulation(
        server_id=server_id,
        added_by_user_id=added_by_user_id,
        bot_message=body.message,
    )
    session.add(message)
    await session.flush()
    await session.refresh(message)
    return _to_celebration_message_read(message, global_user, membership)


@birthdays.put("/{server_id}/settings/messages/{message_id}", response_model=CelebrationMessageReadModel)
async def update_celebration_message(
    server_id: int,
    message_id: UUID,
    body: CelebrationMessageUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    _validate_placeholder(body.message)

    message = await session.get(Congratulation, message_id)
    if not message or message.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Celebration message not found")

    global_user = await session.get(GlobalUser, message.added_by_user_id)
    membership = (
        await session.exec(
            select(User).where(
                User.user_id == message.added_by_user_id,
                User.server_id == server_id,
            )
        )
    ).first()
    message.bot_message = body.message
    session.add(message)
    await session.flush()
    await session.refresh(message)
    return _to_celebration_message_read(message, global_user, membership)


@birthdays.delete("/{server_id}/settings/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_celebration_message(
    server_id: int,
    message_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    message = await session.get(Congratulation, message_id)
    if not message or message.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Celebration message not found")

    await session.delete(message)

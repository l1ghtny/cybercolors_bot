from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_optional_current_discord_user_id, resolve_actor_user_id
from api.models.birthdays import (
    BirthdayCreateModel,
    BirthdayReadModel,
    BirthdayWriteModel,
    ServerBirthdayUserModel,
)
from api.models.birthday_settings import (
    BirthdayChannelUpdateModel,
    BirthdayRoleUpdateModel,
    BirthdaySettingsModel,
    CelebrationMessageCreateModel,
    CelebrationMessageReadModel,
    CelebrationMessageUpdateModel,
)
from api.services.birthdays_service import (
    get_member_or_404,
    get_or_create_server,
    list_birthdays,
    list_celebration_messages,
    list_server_birthday_users,
    resolve_birthday_role_name,
    to_birthday_read,
    to_celebration_message_read,
    to_settings_model,
    validate_placeholder,
)
from src.db.database import get_session
from src.db.models import Birthday, Congratulation, GlobalUser, Server, User

birthdays = APIRouter(prefix="/birthdays", tags=["birthdays"])


@birthdays.get("/{server_id}", response_model=list[BirthdayReadModel])
async def get_birthdays_by_server_id(server_id: int, session: AsyncSession = Depends(get_session)):
    return await list_birthdays(session, server_id)


@birthdays.get("/{server_id}/users", response_model=list[ServerBirthdayUserModel])
async def get_server_users_for_birthday_selector(server_id: int, session: AsyncSession = Depends(get_session)):
    return await list_server_birthday_users(session, server_id)


@birthdays.post("/{server_id}", response_model=BirthdayReadModel, status_code=status.HTTP_201_CREATED)
async def add_birthday_for_server(
    server_id: int,
    body: BirthdayCreateModel,
    session: AsyncSession = Depends(get_session),
):
    user_id = int(body.user_id)
    member, global_user = await get_member_or_404(server_id, user_id, session)

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
    return to_birthday_read(member, global_user, birthday)


@birthdays.put("/{server_id}/{user_id}", response_model=BirthdayReadModel)
async def update_birthday_for_server_user(
    server_id: int,
    user_id: int,
    body: BirthdayWriteModel,
    session: AsyncSession = Depends(get_session),
):
    member, global_user = await get_member_or_404(server_id, user_id, session)

    birthday = await session.get(Birthday, user_id)
    if not birthday:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Birthday not found for this user")

    birthday.day = body.day
    birthday.month = body.month
    birthday.timezone = body.timezone
    session.add(birthday)
    await session.flush()
    await session.refresh(birthday)
    return to_birthday_read(member, global_user, birthday)


@birthdays.get("/{server_id}/settings", response_model=BirthdaySettingsModel)
async def get_birthday_settings(server_id: int, session: AsyncSession = Depends(get_session)):
    server = await session.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server settings not found")
    role_name = await resolve_birthday_role_name(server_id, server.birthday_role_id)
    return to_settings_model(server, birthday_role_name=role_name)


@birthdays.put("/{server_id}/settings/channel", response_model=BirthdaySettingsModel)
async def update_birthday_channel(
    server_id: int,
    body: BirthdayChannelUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    server = await get_or_create_server(server_id, session, body.server_name)

    server.birthday_channel_id = int(body.channel_id) if body.channel_id else None
    server.birthday_channel_name = body.channel_name
    session.add(server)
    await session.flush()
    await session.refresh(server)
    role_name = await resolve_birthday_role_name(server_id, server.birthday_role_id)
    return to_settings_model(server, birthday_role_name=role_name)


@birthdays.put("/{server_id}/settings/role", response_model=BirthdaySettingsModel)
async def update_birthday_role(
    server_id: int,
    body: BirthdayRoleUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    server = await get_or_create_server(server_id, session, body.server_name)
    server.birthday_role_id = int(body.role_id) if body.role_id else None
    session.add(server)
    await session.flush()
    await session.refresh(server)
    role_name = body.role_name or await resolve_birthday_role_name(server_id, server.birthday_role_id)
    return to_settings_model(server, birthday_role_name=role_name)


@birthdays.get("/{server_id}/settings/messages", response_model=list[CelebrationMessageReadModel])
async def get_celebration_messages(server_id: int, session: AsyncSession = Depends(get_session)):
    return await list_celebration_messages(session, server_id)


@birthdays.post(
    "/{server_id}/settings/messages",
    response_model=CelebrationMessageReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def create_celebration_message(
    server_id: int,
    body: CelebrationMessageCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    validate_placeholder(body.message)

    added_by_user_id = resolve_actor_user_id(body.added_by_user_id, current_user_id)
    membership, global_user = await get_member_or_404(server_id, added_by_user_id, session)

    await get_or_create_server(server_id, session)

    message = Congratulation(
        server_id=server_id,
        added_by_user_id=added_by_user_id,
        bot_message=body.message,
    )
    session.add(message)
    await session.flush()
    await session.refresh(message)
    return to_celebration_message_read(message, global_user, membership)


@birthdays.put("/{server_id}/settings/messages/{message_id}", response_model=CelebrationMessageReadModel)
async def update_celebration_message(
    server_id: int,
    message_id: UUID,
    body: CelebrationMessageUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    validate_placeholder(body.message)

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
    return to_celebration_message_read(message, global_user, membership)


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

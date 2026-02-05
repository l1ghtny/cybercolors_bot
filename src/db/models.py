import uuid
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime, UTC, timezone

from sqlalchemy import BigInteger, Column, ForeignKey, TIMESTAMP
from sqlmodel import Field, Relationship, SQLModel


def utcnow_utc_tz():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Main Models ---

class Server(SQLModel, table=True):
    __tablename__ = "servers"
    server_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    server_name: Optional[str] = None
    birthday_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    birthday_channel_name: Optional[str] = None
    birthday_role_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    icon : Optional[str] = None

    users: List["User"] = Relationship(back_populates="server")
    messages: List["Message"] = Relationship(back_populates="server")
    congratulations: List["Congratulation"] = Relationship(back_populates="server")


class GlobalUser(SQLModel, table=True):
    __tablename__ = "global_users"

    # Global user (Discord user) — one row per person
    discord_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    username: Optional[str] = None
    joined_discord: Optional[datetime] = Field(default=None, sa_column=Column(TIMESTAMP(timezone=True)))
    avatar_hash: Optional[str] = None

    # Relationships
    memberships: List["User"] = Relationship(back_populates="global_user")
    birthday: Optional["Birthday"] = Relationship(back_populates="global_user")
    congratulations: List["Congratulation"] = Relationship(back_populates="added_by")
    past_nicknames: List["PastNickname"] = Relationship(back_populates="global_user")
    targeted_by_mod_action: List["ModerationAction"] = Relationship(
        back_populates="global_user_target",
        sa_relationship_kwargs={'foreign_keys': '[ModerationAction.target_user_id]'}
    )
    acting_moderator: List["ModerationAction"] = Relationship(
        back_populates='global_user_moderator',
        sa_relationship_kwargs={'foreign_keys': '[ModerationAction.moderator_user_id]'}
    )



class User(SQLModel, table=True):
    __tablename__ = "users"
    # Per-server membership. Composite PK (server_id, user_id)
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), primary_key=True))
    server_nickname: Optional[str] = None
    flagged_absent_at: Optional[datetime] = None
    is_member: bool = True

    # --- Relationships ---
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, primary_key=True))
    server: Server = Relationship(back_populates="users")

    # Link to the global user
    global_user: GlobalUser = Relationship(back_populates="memberships")


class Birthday(SQLModel, table=True):
    __tablename__ = "birthdays"
    # One birthday per global user
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), primary_key=True))
    day: int
    month: int
    timezone: Optional[str] = None
    role_added_at: Optional[datetime] = None

    # --- Relationships ---
    global_user: GlobalUser = Relationship(back_populates="birthday")


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    message_id: UUID = Field(default_factory=uuid4, primary_key=True)
    added_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    request_phrase: str
    respond_phrase: str

    # --- Relationships ---
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False))
    server: Server = Relationship(back_populates="messages")

    added_by_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))


class Congratulation(SQLModel, table=True):
    __tablename__ = "congratulations"
    id: UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    bot_message: str
    added_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    # --- Relationships ---
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False))
    server: Server = Relationship(back_populates="congratulations")

    added_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    added_by: GlobalUser = Relationship(back_populates="congratulations")


class Replies(SQLModel, table=True):
    __tablename__ = "replies"

    id: UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_message: str = Field(nullable=False)
    bot_reply: str = Field(nullable=False, index=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    created_by_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))


class PastNickname(SQLModel, table=True):
    __tablename__ = "past_nicknames"
    id: UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    discord_name: str
    server_name: str

    # --- Relationships ---
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    global_user: GlobalUser = Relationship(back_populates="past_nicknames")


class VoiceChannel(SQLModel, table=True):
    __tablename__ = "voice_channels"
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, primary_key=True))
    channel_id: int = Field(sa_column=Column(BigInteger, nullable=False, primary_key=True))


# --- New Models for Moderation ---

from enum import Enum


class ActionType(str, Enum):
    WARN = "warn"
    MUTE = "mute"
    BAN = "ban"


class ModerationAction(SQLModel, table=True):
    __tablename__ = "moderation_actions"
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    action_type: ActionType

    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id")))
    target_user_id: int = Field(sa_column=Column(BigInteger, (ForeignKey("global_users.discord_id"))))
    moderator_user_id: int = Field(sa_column=Column(BigInteger, (ForeignKey("global_users.discord_id"))))

    reason: str
    created_at: datetime = Field(default_factory= datetime.now)
    expires_at: Optional[datetime] = None  # For temporary mutes/bans
    is_active: bool = True  # To mark if a ban/mute has been cancelled

    global_user_target: GlobalUser = Relationship(
        back_populates="targeted_by_mod_action",
        sa_relationship_kwargs={'foreign_keys': '[ModerationAction.target_user_id]'}
    )
    global_user_moderator: GlobalUser = Relationship(
        back_populates="acting_moderator",
        sa_relationship_kwargs={'foreign_keys': '[ModerationAction.moderator_user_id]'}
    )


class UserActivity(SQLModel, table=True):
    __tablename__ = "user_activity"
    # Composite primary key for uniqueness
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), primary_key=True))
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), primary_key=True))
    channel_id: int = Field(sa_column=Column(BigInteger))

    message_count: int = 0
    last_message_at: datetime = Field(default_factory= datetime.now)


class TempVoiceLog(SQLModel, table=True):
    __tablename__ = "temp_voice_log"
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(foreign_key="servers.server_id")
    channel_id: int = Field(sa_column=Column(BigInteger))
    channel_name: str
    created_at: datetime
    deleted_at: Optional[datetime] = None


class MessageLog(SQLModel, table=True):
    __tablename__ = "message_log"
    message_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    log_id: UUID = Field(foreign_key="temp_voice_log.id")  # Link to the channel log

    user_id: int = Field(foreign_key="global_users.discord_id")
    content: str
    created_at: datetime
    # For replies
    reply_to_message_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))


class AttachmentLog(SQLModel, table=True):
    __tablename__ = "attachment_log"
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    message_id: int = Field(sa_column=Column(BigInteger, ForeignKey("message_log.message_id")))

    # This would store the key or path to the file in your S3-like storage
    storage_key: str
    file_name: str
    content_type: str

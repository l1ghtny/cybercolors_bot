import uuid
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime, UTC

from sqlalchemy import BigInteger, Column, ForeignKey
from sqlmodel import Field, Relationship, SQLModel

# --- Main Models ---

class Server(SQLModel, table=True):
    server_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    server_name: Optional[str] = None
    birthday_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    birthday_channel_name: Optional[str] = None
    birthday_role_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    users: List["User"] = Relationship(back_populates="server")
    messages: List["Message"] = Relationship(back_populates="server")
    congratulations: List["Congratulations"] = Relationship(back_populates="server")


class GlobalUser(SQLModel, table=True):
    __tablename__ = "global_users"

    # Global user (Discord user) — one row per person
    discord_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    username: Optional[str] = None
    joined_discord: Optional[datetime] = None

    # Relationships
    memberships: List["User"] = Relationship(back_populates="global_user")
    birthday: Optional["Birthday"] = Relationship(back_populates="global_user")
    congratulations: List["Congratulations"] = Relationship(back_populates="added_by")
    past_nicknames: List["PastNickname"] = Relationship(back_populates="global_user")


class User(SQLModel, table=True):
    # Per-server membership. Composite PK (server_id, user_id)
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), primary_key=True))
    nickname: str
    server_nickname: Optional[str] = None
    flagged_absent_at: Optional[datetime] = None
    is_member: bool = True

    # --- Relationships ---
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("server.server_id"), nullable=False, primary_key=True))
    server: Server = Relationship(back_populates="users")

    # Link to the global user
    global_user: GlobalUser = Relationship(back_populates="memberships")


class Birthday(SQLModel, table=True):
    # One birthday per global user
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), primary_key=True))
    day: int
    month: int
    timezone: Optional[str] = None
    role_added_at: Optional[datetime] = None

    # --- Relationships ---
    global_user: GlobalUser = Relationship(back_populates="birthday")


class Message(SQLModel, table=True):
    message_id: UUID = Field(default_factory=uuid4, primary_key=True)
    added_at: datetime = Field(default_factory=datetime.now(UTC), nullable=False)
    request_phrase: str
    respond_phrase: str

    # --- Relationships ---
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("server.server_id"), nullable=False))
    server: Server = Relationship(back_populates="messages")

    added_by_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))


class Congratulations(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    bot_message: str
    added_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    # --- Relationships ---
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("server.server_id"), nullable=False))
    server: Server = Relationship(back_populates="congratulations")

    added_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    added_by: GlobalUser = Relationship(back_populates="congratulations")


class PastNickname(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    discord_name: str
    server_name: str

    # --- Relationships ---
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    global_user: GlobalUser = Relationship(back_populates="past_nicknames")


class VoiceChannel(SQLModel, table=True):
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("server.server_id"), nullable=False, primary_key=True))
    channel_id: int = Field(sa_column=Column(BigInteger, nullable=False, primary_key=True))


# --- New Models for Moderation ---

from enum import Enum


class ActionType(str, Enum):
    WARN = "warn"
    MUTE = "mute"
    BAN = "ban"


class ModerationAction(SQLModel, table=True):
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    action_type: ActionType

    server_id: int = Field(sa_column=Column(BigInteger, foreign_key="server.server_id"))
    target_user_id: int = Field(sa_column=Column(BigInteger, foreign_key="global_users.discord_id"))
    moderator_user_id: int = Field(sa_column=Column(BigInteger, foreign_key="global_users.discord_id"))

    reason: str
    created_at: datetime = Field(default_factory=datetime.now(UTC),)
    expires_at: Optional[datetime] = None  # For temporary mutes/bans
    is_active: bool = True  # To mark if a ban/mute has been cancelled


class UserActivity(SQLModel, table=True):
    # Composite primary key for uniqueness
    user_id: int = Field(sa_column=Column(BigInteger, foreign_key="global_users.discord_id", primary_key=True))
    server_id: int = Field(sa_column=Column(BigInteger, foreign_key="server.server_id", primary_key=True))
    channel_id: int = Field(sa_column=Column(BigInteger))

    message_count: int = 0
    last_message_at: datetime = Field(default_factory=datetime.now(UTC))


# In src/db/models.py

class TempVoiceLog(SQLModel, table=True):
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(foreign_key="server.server_id")
    channel_id: int = Field(sa_column=Column(BigInteger))
    channel_name: str
    created_at: datetime
    deleted_at: Optional[datetime] = None


class MessageLog(SQLModel, table=True):
    message_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    log_id: UUID = Field(foreign_key="tempvoicelog.id")  # Link to the channel log

    user_id: int = Field(foreign_key="global_users.discord_id")
    content: str
    created_at: datetime
    # For replies
    reply_to_message_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))


class AttachmentLog(SQLModel, table=True):
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    message_id: int = Field(sa_column=Column(BigInteger, foreign_key="messagelog.message_id"))

    # This would store the key or path to the file in your S3-like storage
    storage_key: str
    file_name: str
    content_type: str



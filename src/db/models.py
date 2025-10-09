from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime

from sqlalchemy import BigInteger, Column, ForeignKey
from sqlmodel import Field, Relationship, SQLModel

# --- Main Models ---

class Server(SQLModel, table=True):
    server_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    server_name: str
    birthday_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    birthday_channel_name: Optional[str] = None
    birthday_role_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    users: List["User"] = Relationship(back_populates="server")
    messages: List["Message"] = Relationship(back_populates="server")
    congratulations: List["Congratulations"] = Relationship(back_populates="server")


class User(SQLModel, table=True):
    user_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    nickname: str
    server_nickname: Optional[str] = None
    flagged_absent_at: Optional[datetime] = None
    is_member: bool = True

    # --- Relationships ---
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("server.server_id")  , nullable=False))
    server: Server = Relationship(back_populates="users")

    # This creates the one-to-one link to the Birthday table
    birthday: Optional["Birthday"] = Relationship(back_populates="user")

    congratulations: List["Congratulations"] = Relationship(back_populates="added_by")
    past_nicknames: List["PastNickname"] = Relationship(back_populates="user")


class Birthday(SQLModel, table=True):
    # The user_id is both the Primary Key and the Foreign Key
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("user.user_id"), primary_key=True))
    day: int
    month: int
    timezone: Optional[str] = None
    role_added_at: Optional[datetime] = None

    # --- Relationships ---
    user: User = Relationship(back_populates="birthday")


class Message(SQLModel, table=True):
    message_id: UUID = Field(default_factory=uuid4, primary_key=True)
    added_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    request_phrase: str
    respond_phrase: str

    # --- Relationships ---
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("server.server_id"), nullable=False))
    server: Server = Relationship(back_populates="messages")

    added_by_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))


class Congratulations(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    bot_message: str
    added_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    # --- Relationships ---
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("server.server_id"), nullable=False))
    server: Server = Relationship(back_populates="congratulations")

    added_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("user.user_id"), nullable=False))
    added_by: User = Relationship(back_populates="congratulations")


class PastNickname(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    discord_name: str
    server_name: str

    # --- Relationships ---
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("user.user_id"), nullable=False))
    user: User = Relationship(back_populates="past_nicknames")

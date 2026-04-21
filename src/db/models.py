import uuid
from typing import List, Optional
from uuid import UUID, uuid4, uuid7
from datetime import datetime, UTC, timezone

from sqlalchemy import BigInteger, Column, ForeignKey, TIMESTAMP, Text, UniqueConstraint
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
    congratulations: List["Congratulation"] = Relationship(back_populates="server")
    replies: List["Replies"] = Relationship(back_populates="server")
    voice_channels: List["VoiceChannel"] = Relationship(back_populates="server")
    temp_voice_logs: List["TempVoiceLog"] = Relationship(back_populates="server")
    moderation_actions: List["ModerationAction"] = Relationship(back_populates="server")
    moderation_cases: List["ModerationCase"] = Relationship(back_populates="server")
    deleted_messages: List["DeletedMessage"] = Relationship(back_populates="server")
    past_nicknames: List["PastNickname"] = Relationship(back_populates="server")
    user_activity: List["UserActivity"] = Relationship(back_populates="server")
    monitored_users: List["MonitoredUser"] = Relationship(back_populates="server")
    dashboard_access_users: List["DashboardAccessUser"] = Relationship(back_populates="server")
    dashboard_access_roles: List["DashboardAccessRole"] = Relationship(back_populates="server")
    security_settings: Optional["ServerSecuritySettings"] = Relationship(
        back_populates="server",
        sa_relationship_kwargs={"uselist": False},
    )


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
    opened_moderation_cases: List["ModerationCase"] = Relationship(
        back_populates="opened_by",
        sa_relationship_kwargs={'foreign_keys': '[ModerationCase.opened_by_user_id]'}
    )
    closed_moderation_cases: List["ModerationCase"] = Relationship(
        back_populates="closed_by",
        sa_relationship_kwargs={'foreign_keys': '[ModerationCase.closed_by_user_id]'}
    )
    moderation_case_notes: List["ModerationCaseNote"] = Relationship(back_populates="author")
    moderation_case_evidence: List["ModerationCaseEvidence"] = Relationship(back_populates="added_by")
    linked_mod_actions: List["ModerationCaseActionLink"] = Relationship(back_populates="linked_by")
    action_deleted_messages: List["ModerationActionDeletedMessageLink"] = Relationship(back_populates="linked_by")
    deleted_messages_authored: List["DeletedMessage"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={'foreign_keys': '[DeletedMessage.author_user_id]'}
    )
    deleted_messages_removed: List["DeletedMessage"] = Relationship(
        back_populates="deleted_by",
        sa_relationship_kwargs={'foreign_keys': '[DeletedMessage.deleted_by_user_id]'}
    )
    monitored_records: List["MonitoredUser"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={'foreign_keys': '[MonitoredUser.user_id]'}
    )
    monitored_records_added: List["MonitoredUser"] = Relationship(
        back_populates="added_by",
        sa_relationship_kwargs={'foreign_keys': '[MonitoredUser.added_by_user_id]'}
    )
    monitored_status_changes: List["MonitoredUserStatusEvent"] = Relationship(
        back_populates="changed_by",
        sa_relationship_kwargs={'foreign_keys': '[MonitoredUserStatusEvent.changed_by_user_id]'}
    )
    monitored_comments_authored: List["MonitoredUserComment"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={'foreign_keys': '[MonitoredUserComment.author_user_id]'}
    )
    dashboard_access_user_targets: List["DashboardAccessUser"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={'foreign_keys': '[DashboardAccessUser.user_id]'}
    )
    dashboard_access_user_added: List["DashboardAccessUser"] = Relationship(
        back_populates="added_by",
        sa_relationship_kwargs={'foreign_keys': '[DashboardAccessUser.added_by_user_id]'}
    )
    dashboard_access_role_added: List["DashboardAccessRole"] = Relationship(
        back_populates="added_by",
        sa_relationship_kwargs={'foreign_keys': '[DashboardAccessRole.added_by_user_id]'}
    )

    replies: List["Replies"] = Relationship(back_populates="created_by")
    user_activity: List["UserActivity"] = Relationship(back_populates="global_user")



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
    bot_reply: str = Field(nullable=False, index=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    created_by_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))

    server: Server = Relationship(back_populates="replies")
    created_by: GlobalUser = Relationship(back_populates="replies")
    triggers: List["Triggers"] = Relationship(back_populates="reply")


class PastNickname(SQLModel, table=True):
    __tablename__ = "past_nicknames"
    id: UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    discord_name: str
    server_name: str
    server_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=True, index=True))
    recorded_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    # --- Relationships ---
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    global_user: GlobalUser = Relationship(back_populates="past_nicknames")
    server: Optional[Server] = Relationship(back_populates="past_nicknames")


class VoiceChannel(SQLModel, table=True):
    __tablename__ = "voice_channels"
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, primary_key=True))
    channel_id: int = Field(sa_column=Column(BigInteger, nullable=False, primary_key=True))

    server: Server = Relationship(back_populates="voice_channels")


class ServerSecuritySettings(SQLModel, table=True):
    __tablename__ = "server_security_settings"

    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), primary_key=True))
    verified_role_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    normal_permissions: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    lockdown_permissions: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    lockdown_enabled: bool = Field(default=False, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="security_settings")


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

    server: Server = Relationship(back_populates="moderation_actions")
    case_links: List["ModerationCaseActionLink"] = Relationship(back_populates="moderation_action")
    deleted_message_links: List["ModerationActionDeletedMessageLink"] = Relationship(back_populates="moderation_action")


class CaseStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    ARCHIVED = "archived"


class EvidenceType(str, Enum):
    SCREENSHOT = "screenshot"
    LINK = "link"
    NOTE = "note"
    FILE = "file"


class CaseUserRole(str, Enum):
    PRIMARY_TARGET = "primary_target"
    TARGET = "target"
    REPORTER = "reporter"
    WITNESS = "witness"
    MODERATOR = "moderator"
    RELATED = "related"


class MonitoredUser(SQLModel, table=True):
    __tablename__ = "monitored_users"
    __table_args__ = (UniqueConstraint("server_id", "user_id", name="uq_monitored_users_server_user"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False, index=True))
    added_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    is_active: bool = Field(default=True, nullable=False, index=True)
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="monitored_users")
    user: GlobalUser = Relationship(
        back_populates="monitored_records",
        sa_relationship_kwargs={'foreign_keys': '[MonitoredUser.user_id]'}
    )
    added_by: GlobalUser = Relationship(
        back_populates="monitored_records_added",
        sa_relationship_kwargs={'foreign_keys': '[MonitoredUser.added_by_user_id]'}
    )
    comments: List["MonitoredUserComment"] = Relationship(back_populates="monitored_user")
    status_events: List["MonitoredUserStatusEvent"] = Relationship(back_populates="monitored_user")


class MonitoredUserComment(SQLModel, table=True):
    __tablename__ = "monitored_user_comments"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    monitored_user_id: UUID = Field(foreign_key="monitored_users.id", nullable=False, index=True)
    author_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    comment: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False, index=True)

    monitored_user: MonitoredUser = Relationship(back_populates="comments")
    author: GlobalUser = Relationship(
        back_populates="monitored_comments_authored",
        sa_relationship_kwargs={'foreign_keys': '[MonitoredUserComment.author_user_id]'}
    )


class MonitoredUserStatusEvent(SQLModel, table=True):
    __tablename__ = "monitored_user_status_events"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    monitored_user_id: UUID = Field(foreign_key="monitored_users.id", nullable=False, index=True)
    changed_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    from_is_active: Optional[bool] = Field(default=None, nullable=True)
    to_is_active: bool = Field(nullable=False)
    changed_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False, index=True)

    monitored_user: MonitoredUser = Relationship(back_populates="status_events")
    changed_by: GlobalUser = Relationship(
        back_populates="monitored_status_changes",
        sa_relationship_kwargs={'foreign_keys': '[MonitoredUserStatusEvent.changed_by_user_id]'}
    )


class DashboardAccessUser(SQLModel, table=True):
    __tablename__ = "dashboard_access_users"
    __table_args__ = (UniqueConstraint("server_id", "user_id", name="uq_dashboard_access_users_server_user"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False, index=True))
    added_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="dashboard_access_users")
    user: GlobalUser = Relationship(
        back_populates="dashboard_access_user_targets",
        sa_relationship_kwargs={'foreign_keys': '[DashboardAccessUser.user_id]'}
    )
    added_by: GlobalUser = Relationship(
        back_populates="dashboard_access_user_added",
        sa_relationship_kwargs={'foreign_keys': '[DashboardAccessUser.added_by_user_id]'}
    )


class DashboardAccessRole(SQLModel, table=True):
    __tablename__ = "dashboard_access_roles"
    __table_args__ = (UniqueConstraint("server_id", "role_id", name="uq_dashboard_access_roles_server_role"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    role_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    added_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="dashboard_access_roles")
    added_by: GlobalUser = Relationship(
        back_populates="dashboard_access_role_added",
        sa_relationship_kwargs={'foreign_keys': '[DashboardAccessRole.added_by_user_id]'}
    )


class ModerationCase(SQLModel, table=True):
    __tablename__ = "moderation_cases"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    target_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False, index=True))
    opened_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    title: str = Field(nullable=False)
    summary: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    status: CaseStatus = Field(default=CaseStatus.OPEN, nullable=False, index=True)
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    closed_at: Optional[datetime] = None
    closed_by_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True))

    server: Server = Relationship(back_populates="moderation_cases")
    target_user: GlobalUser = Relationship(
        sa_relationship_kwargs={'foreign_keys': '[ModerationCase.target_user_id]'}
    )
    opened_by: GlobalUser = Relationship(
        back_populates="opened_moderation_cases",
        sa_relationship_kwargs={'foreign_keys': '[ModerationCase.opened_by_user_id]'}
    )
    closed_by: Optional[GlobalUser] = Relationship(
        back_populates="closed_moderation_cases",
        sa_relationship_kwargs={'foreign_keys': '[ModerationCase.closed_by_user_id]'}
    )
    notes: List["ModerationCaseNote"] = Relationship(back_populates="moderation_case")
    evidence_items: List["ModerationCaseEvidence"] = Relationship(back_populates="moderation_case")
    action_links: List["ModerationCaseActionLink"] = Relationship(back_populates="moderation_case")
    users: List["ModerationCaseUser"] = Relationship(back_populates="moderation_case")


class ModerationCaseUser(SQLModel, table=True):
    __tablename__ = "moderation_case_users"
    __table_args__ = (UniqueConstraint("case_id", "user_id", name="uq_case_user_link"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    case_id: UUID = Field(foreign_key="moderation_cases.id", nullable=False, index=True)
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False, index=True))
    role: CaseUserRole = Field(default=CaseUserRole.RELATED, nullable=False)
    added_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    added_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    moderation_case: ModerationCase = Relationship(back_populates="users")
    user: GlobalUser = Relationship(
        sa_relationship_kwargs={'foreign_keys': '[ModerationCaseUser.user_id]'}
    )
    added_by: GlobalUser = Relationship(
        sa_relationship_kwargs={'foreign_keys': '[ModerationCaseUser.added_by_user_id]'}
    )


class ModerationCaseActionLink(SQLModel, table=True):
    __tablename__ = "moderation_case_action_links"
    __table_args__ = (UniqueConstraint("case_id", "moderation_action_id", name="uq_case_action_link"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    case_id: UUID = Field(foreign_key="moderation_cases.id", nullable=False, index=True)
    moderation_action_id: UUID = Field(foreign_key="moderation_actions.id", nullable=False, index=True)
    linked_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    linked_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    moderation_case: ModerationCase = Relationship(back_populates="action_links")
    moderation_action: ModerationAction = Relationship(back_populates="case_links")
    linked_by: GlobalUser = Relationship(back_populates="linked_mod_actions")


class ModerationCaseNote(SQLModel, table=True):
    __tablename__ = "moderation_case_notes"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    case_id: UUID = Field(foreign_key="moderation_cases.id", nullable=False, index=True)
    author_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    note: str = Field(sa_column=Column(Text, nullable=False))
    is_internal: bool = True
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    moderation_case: ModerationCase = Relationship(back_populates="notes")
    author: GlobalUser = Relationship(back_populates="moderation_case_notes")


class ModerationCaseEvidence(SQLModel, table=True):
    __tablename__ = "moderation_case_evidence"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    case_id: UUID = Field(foreign_key="moderation_cases.id", nullable=False, index=True)
    added_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    evidence_type: EvidenceType = Field(nullable=False)
    url: Optional[str] = None
    text: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    attachment_key: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    moderation_case: ModerationCase = Relationship(back_populates="evidence_items")
    added_by: GlobalUser = Relationship(back_populates="moderation_case_evidence")


class DeletedMessage(SQLModel, table=True):
    __tablename__ = "deleted_messages"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    message_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    channel_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    author_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True))
    content: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    attachments_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    deleted_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    deleted_by_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True))

    server: Server = Relationship(back_populates="deleted_messages")
    author: Optional[GlobalUser] = Relationship(
        back_populates="deleted_messages_authored",
        sa_relationship_kwargs={'foreign_keys': '[DeletedMessage.author_user_id]'}
    )
    deleted_by: Optional[GlobalUser] = Relationship(
        back_populates="deleted_messages_removed",
        sa_relationship_kwargs={'foreign_keys': '[DeletedMessage.deleted_by_user_id]'}
    )
    action_links: List["ModerationActionDeletedMessageLink"] = Relationship(back_populates="deleted_message")


class ModerationActionDeletedMessageLink(SQLModel, table=True):
    __tablename__ = "moderation_action_deleted_message_links"
    __table_args__ = (UniqueConstraint("moderation_action_id", "deleted_message_id", name="uq_action_deleted_message_link"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    moderation_action_id: UUID = Field(foreign_key="moderation_actions.id", nullable=False, index=True)
    deleted_message_id: UUID = Field(foreign_key="deleted_messages.id", nullable=False, index=True)
    linked_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    linked_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    moderation_action: ModerationAction = Relationship(back_populates="deleted_message_links")
    deleted_message: DeletedMessage = Relationship(back_populates="action_links")
    linked_by: GlobalUser = Relationship(back_populates="action_deleted_messages")


class UserActivity(SQLModel, table=True):
    __tablename__ = "user_activity"
    # Composite primary key for uniqueness
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), primary_key=True))
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), primary_key=True))
    channel_id: int = Field(sa_column=Column(BigInteger))

    message_count: int = 0
    last_message_at: datetime = Field(default_factory= datetime.now)

    server: Server = Relationship(back_populates="user_activity")
    global_user: GlobalUser = Relationship(back_populates="user_activity")


class TempVoiceLog(SQLModel, table=True):
    __tablename__ = "temp_voice_log"
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(foreign_key="servers.server_id")
    channel_id: int = Field(sa_column=Column(BigInteger))
    channel_name: str
    created_at: datetime
    deleted_at: Optional[datetime] = None

    server: Server = Relationship(back_populates="temp_voice_logs")


class MessageLog(SQLModel, table=True):
    __tablename__ = "message_log"
    message_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    log_id: Optional[UUID] = Field(default=None, foreign_key="temp_voice_log.id", nullable=True)  # Optional link to channel log
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id")))
    channel_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    content: str
    created_at: datetime
    # For replies
    reply_to_message_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id")))

    attachments: List["AttachmentLog"] = Relationship(back_populates="message")


class AttachmentLog(SQLModel, table=True):
    __tablename__ = "attachment_log"
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    message_id: int = Field(sa_column=Column(BigInteger, ForeignKey("message_log.message_id")))

    # This would store the key or path to the file in your S3-like storage
    storage_key: str
    file_name: str
    content_type: str

    message: MessageLog = Relationship(back_populates="attachments")




class Triggers(SQLModel, table=True):
    __tablename__ = "triggers"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    message: str = Field(nullable=False, index=True)
    reply_id: UUID = Field(nullable=False, foreign_key="replies.id")

    reply: Replies = Relationship(back_populates="triggers")

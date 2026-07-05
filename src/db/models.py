import uuid
from typing import List, Optional
from uuid import UUID, uuid4, uuid7
from datetime import datetime, UTC, timezone

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Column, ForeignKey, JSON, String, TIMESTAMP, Text, UniqueConstraint
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
    bot_active: bool = Field(default=False, nullable=False)
    bot_joined_at: Optional[datetime] = None
    bot_left_at: Optional[datetime] = None
    bot_presence_updated_at: Optional[datetime] = None

    users: List["User"] = Relationship(back_populates="server")
    congratulations: List["Congratulation"] = Relationship(back_populates="server")
    replies: List["Replies"] = Relationship(back_populates="server")
    voice_channels: List["VoiceChannel"] = Relationship(back_populates="server")
    temp_voice_logs: List["TempVoiceLog"] = Relationship(back_populates="server")
    temp_voice_settings: Optional["ServerTempVoiceSettings"] = Relationship(
        back_populates="server",
        sa_relationship_kwargs={"uselist": False},
    )
    moderation_actions: List["ModerationAction"] = Relationship(back_populates="server")
    moderation_cases: List["ModerationCase"] = Relationship(back_populates="server")
    deleted_messages: List["DeletedMessage"] = Relationship(back_populates="server")
    past_nicknames: List["PastNickname"] = Relationship(back_populates="server")
    user_activity: List["UserActivity"] = Relationship(back_populates="server")
    monitored_users: List["MonitoredUser"] = Relationship(back_populates="server")
    dashboard_access_users: List["DashboardAccessUser"] = Relationship(back_populates="server")
    dashboard_access_roles: List["DashboardAccessRole"] = Relationship(back_populates="server")
    rbac_assignments: List["ServerRbacAssignment"] = Relationship(back_populates="server")
    rbac_audit_events: List["ServerRbacAuditEvent"] = Relationship(back_populates="server")
    moderation_rules: List["ModerationRule"] = Relationship(back_populates="server")
    moderation_settings: Optional["ServerModerationSettings"] = Relationship(
        back_populates="server",
        sa_relationship_kwargs={"uselist": False},
    )
    ai_settings: Optional["ServerAISettings"] = Relationship(
        back_populates="server",
        sa_relationship_kwargs={"uselist": False},
    )
    ai_knowledge_sources: List["AIKnowledgeSource"] = Relationship(back_populates="server")
    ai_knowledge_chunks: List["AIKnowledgeChunk"] = Relationship(back_populates="server")
    ai_knowledge_index_jobs: List["AIKnowledgeIndexJob"] = Relationship(back_populates="server")
    security_settings: Optional["ServerSecuritySettings"] = Relationship(
        back_populates="server",
        sa_relationship_kwargs={"uselist": False},
    )
    localization_settings: Optional["ServerLocalizationSettings"] = Relationship(
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
    rbac_assignments_created: List["ServerRbacAssignment"] = Relationship(
        back_populates="created_by",
        sa_relationship_kwargs={'foreign_keys': '[ServerRbacAssignment.created_by_user_id]'}
    )
    rbac_assignments_updated: List["ServerRbacAssignment"] = Relationship(
        back_populates="updated_by",
        sa_relationship_kwargs={'foreign_keys': '[ServerRbacAssignment.updated_by_user_id]'}
    )
    rbac_audit_events: List["ServerRbacAuditEvent"] = Relationship(
        back_populates="actor",
        sa_relationship_kwargs={'foreign_keys': '[ServerRbacAuditEvent.actor_user_id]'}
    )
    ai_knowledge_sources_created: List["AIKnowledgeSource"] = Relationship(
        back_populates="created_by",
        sa_relationship_kwargs={'foreign_keys': '[AIKnowledgeSource.created_by_user_id]'}
    )

    replies: List["Replies"] = Relationship(back_populates="created_by")
    user_activity: List["UserActivity"] = Relationship(back_populates="global_user")
    moderation_rules_created: List["ModerationRule"] = Relationship(back_populates="created_by")



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
    trigger_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    owner_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True))
    channel_name: Optional[str] = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="voice_channels")


class ServerTempVoiceSettings(SQLModel, table=True):
    __tablename__ = "server_temp_voice_settings"

    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), primary_key=True))
    enabled: bool = Field(default=False, nullable=False)
    trigger_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    archive_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    archive_post_mode: str = Field(default="mod_log_fallback", nullable=False, max_length=30)
    channel_name_template: str = Field(default="{display_name}'s channel", nullable=False, max_length=100)
    owner_manage_channel_enabled: bool = Field(default=True, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="temp_voice_settings")


class ServerSecuritySettings(SQLModel, table=True):
    __tablename__ = "server_security_settings"

    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), primary_key=True))
    verified_role_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    newcomer_role_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    newcomer_restriction_enabled: bool = Field(default=False, nullable=False)
    newcomer_auto_release_minutes: Optional[int] = Field(default=None, nullable=True)
    normal_permissions: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    lockdown_permissions: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    lockdown_enabled: bool = Field(default=False, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="security_settings")


class ServerModerationSettings(SQLModel, table=True):
    __tablename__ = "server_moderation_settings"

    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), primary_key=True))
    mute_role_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    default_mute_minutes: int = Field(default=60, nullable=False)
    max_mute_minutes: int = Field(default=10080, nullable=False)
    auto_reconnect_voice_on_mute: bool = Field(default=True, nullable=False)
    mod_log_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    activity_excluded_channel_ids: list[str] = Field(
        default_factory=list,
        sa_column=Column(sa.JSON, nullable=False),
    )
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="moderation_settings")


class ServerAISettings(SQLModel, table=True):
    __tablename__ = "server_ai_settings"

    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), primary_key=True))
    answer_channel_mode: str = Field(default="none", nullable=False, max_length=20)
    answer_allowed_channel_ids: list[str] = Field(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    answer_allowed_role_ids: list[str] = Field(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    moderation_enabled: bool = Field(default=False, nullable=False)
    moderation_channel_mode: str = Field(default="all", nullable=False, max_length=20)
    moderation_included_channel_ids: list[str] = Field(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    moderation_excluded_channel_ids: list[str] = Field(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    moderation_monitor_attachments: bool = Field(default=False, nullable=False)
    moderation_monitor_bots: bool = Field(default=False, nullable=False)
    moderation_strictness: str = Field(default="standard", nullable=False, max_length=20)
    moderation_action_mode: str = Field(default="review_only", nullable=False, max_length=30)
    moderation_review_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    log_ai_decisions: bool = Field(default=True, nullable=False)
    moderation_kill_switch_enabled: bool = Field(default=False, nullable=False)
    moderation_daily_token_limit: Optional[int] = Field(default=None, nullable=True)
    moderation_provider_timeout_seconds: int = Field(default=20, nullable=False)
    answer_persona: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    server_brief: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="ai_settings")


class AIModerationDecision(SQLModel, table=True):
    __tablename__ = "ai_moderation_decisions"
    __table_args__ = (UniqueConstraint("server_id", "message_id", name="uq_ai_moderation_decisions_server_message"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    channel_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    message_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    author_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False, index=True))
    message_content: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    attachments_json: list[dict] = Field(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    provider: Optional[str] = Field(default=None, nullable=True)
    model: Optional[str] = Field(default=None, nullable=True)
    total_tokens: int = Field(default=0, nullable=False)
    strictness: str = Field(default="standard", nullable=False, max_length=20)
    flagged: bool = Field(default=False, nullable=False, index=True)
    severity: str = Field(default="none", nullable=False, max_length=20)
    categories: list[str] = Field(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    suggested_action: str = Field(default="none", nullable=False, max_length=30)
    selected_action: Optional[str] = Field(default=None, nullable=True, max_length=30)
    action_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    action_override: bool = Field(default=False, nullable=False)
    rule_ids: list[str] = Field(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    raw_response: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    parse_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    status: str = Field(default="pending_review", nullable=False, max_length=30, index=True)
    review_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    review_message_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    archive_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    archive_message_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    reviewed_by_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True))
    reviewed_at: Optional[datetime] = None
    linked_case_id: Optional[UUID] = Field(default=None, foreign_key="moderation_cases.id")
    linked_action_id: Optional[UUID] = Field(default=None, foreign_key="moderation_actions.id")
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)


class AIAnswerLog(SQLModel, table=True):
    __tablename__ = "ai_answer_logs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    server_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True, index=True))
    channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True, index=True))
    message_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True, index=True))
    author_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True, index=True))
    status: str = Field(sa_column=Column(String(length=30), nullable=False, index=True))
    provider: Optional[str] = Field(default=None, sa_column=Column(String(length=50), nullable=True))
    model: Optional[str] = Field(default=None, sa_column=Column(String(length=120), nullable=True))
    response_id: Optional[str] = Field(default=None, sa_column=Column(String(length=120), nullable=True))
    total_tokens: int = Field(default=0, nullable=False)
    tool_call_count: int = Field(default=0, nullable=False)
    visual_input_count: int = Field(default=0, nullable=False)
    conversation_message_count: int = Field(default=0, nullable=False)
    request_content: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    response_content: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    error_type: Optional[str] = Field(default=None, sa_column=Column(String(length=120), nullable=True))
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    duration_ms: Optional[int] = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)


class AIKnowledgeSource(SQLModel, table=True):
    __tablename__ = "ai_knowledge_sources"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    source_type: str = Field(sa_column=Column(String(length=30), nullable=False, index=True))
    subject_type: str = Field(default="server", sa_column=Column(String(length=30), nullable=False, index=True))
    subject_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True, index=True),
    )
    status: str = Field(default="draft", sa_column=Column(String(length=30), nullable=False, index=True))
    visibility: str = Field(default="public_answer", sa_column=Column(String(length=30), nullable=False, index=True))
    title: Optional[str] = Field(default=None, sa_column=Column(String(length=255), nullable=True))
    content_text: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    source_url: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    storage_key: Optional[str] = Field(default=None, sa_column=Column(String(length=512), nullable=True))
    mime_type: Optional[str] = Field(default=None, sa_column=Column(String(length=120), nullable=True))
    size_bytes: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    sha256: Optional[str] = Field(default=None, sa_column=Column(String(length=64), nullable=True, index=True))
    metadata_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_by_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True, index=True),
    )
    error_code: Optional[str] = Field(default=None, sa_column=Column(String(length=80), nullable=True))
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    indexed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = Field(default=None, nullable=True, index=True)

    server: Server = Relationship(back_populates="ai_knowledge_sources")
    created_by: Optional[GlobalUser] = Relationship(
        back_populates="ai_knowledge_sources_created",
        sa_relationship_kwargs={'foreign_keys': '[AIKnowledgeSource.created_by_user_id]'}
    )
    chunks: List["AIKnowledgeChunk"] = Relationship(back_populates="source")
    index_jobs: List["AIKnowledgeIndexJob"] = Relationship(back_populates="source")


class AIKnowledgeChunk(SQLModel, table=True):
    __tablename__ = "ai_knowledge_chunks"
    __table_args__ = (UniqueConstraint("source_id", "chunk_ordinal", name="uq_ai_knowledge_chunks_source_ordinal"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    source_id: UUID = Field(foreign_key="ai_knowledge_sources.id", nullable=False, index=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    chunk_ordinal: int = Field(nullable=False)
    chunk_text: str = Field(sa_column=Column(Text, nullable=False))
    text_hash: str = Field(sa_column=Column(String(length=64), nullable=False, index=True))
    token_count: int = Field(default=0, nullable=False)
    embedding: Optional[list[float]] = Field(default=None, sa_column=Column(Vector(1024), nullable=True))
    embedding_provider: Optional[str] = Field(default=None, sa_column=Column(String(length=50), nullable=True))
    embedding_model: Optional[str] = Field(default=None, sa_column=Column(String(length=120), nullable=True))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="ai_knowledge_chunks")
    source: AIKnowledgeSource = Relationship(back_populates="chunks")


class AIKnowledgeIndexJob(SQLModel, table=True):
    __tablename__ = "ai_knowledge_index_jobs"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    source_id: Optional[UUID] = Field(default=None, foreign_key="ai_knowledge_sources.id", nullable=True, index=True)
    job_type: str = Field(default="index_source", sa_column=Column(String(length=40), nullable=False, index=True))
    status: str = Field(default="pending", sa_column=Column(String(length=30), nullable=False, index=True))
    dedupe_key: str = Field(sa_column=Column(String(length=255), nullable=False, index=True))
    attempt_count: int = Field(default=0, nullable=False)
    run_after: datetime = Field(default_factory=utcnow_utc_tz, nullable=False, index=True)
    locked_at: Optional[datetime] = Field(default=None, nullable=True)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="ai_knowledge_index_jobs")
    source: Optional[AIKnowledgeSource] = Relationship(back_populates="index_jobs")


class ServerLocalizationSettings(SQLModel, table=True):
    __tablename__ = "server_localization_settings"

    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), primary_key=True))
    locale_code: str = Field(default="en", nullable=False, max_length=10)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="localization_settings")


# --- New Models for Moderation ---

from enum import Enum


class ActionType(str, Enum):
    WARN = "warn"
    MUTE = "mute"
    BAN = "ban"
    KICK = "kick"


class ModerationImportSource(str, Enum):
    DISCORD = "discord"
    JUNIPER = "juniper"
    DYNO = "dyno"
    CARL_BOT = "carl_bot"
    MEE6 = "mee6"
    YAGPDB = "yagpdb"
    MANUAL = "manual"


class ModerationImportRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ModerationImportItemStatus(str, Enum):
    PENDING = "pending"
    IMPORTED = "imported"
    SKIPPED = "skipped"
    FAILED = "failed"


class ModerationImportConfidence(str, Enum):
    EXACT = "exact"
    PARSED = "parsed"
    INFERRED = "inferred"
    MANUAL_REVIEW = "manual_review"

class ModerationRule(SQLModel, table=True):
    __tablename__ = "moderation_rules"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    code: Optional[str] = Field(default=None, nullable=True, index=True)
    title: str = Field(nullable=False)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    sort_order: int = Field(default=0, nullable=False)
    source_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    source_message_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    source_marker: Optional[str] = Field(default=None, nullable=True)
    is_active: bool = Field(default=True, nullable=False, index=True)
    created_by_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True),
    )
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="moderation_rules")
    created_by: Optional[GlobalUser] = Relationship(back_populates="moderation_rules_created")
    moderation_actions: List["ModerationAction"] = Relationship(back_populates="rule")
    action_citations: List["ModerationActionRuleCitation"] = Relationship(back_populates="rule")
    case_citations: List["ModerationCaseRuleCitation"] = Relationship(back_populates="rule")


class ModerationAction(SQLModel, table=True):
    __tablename__ = "moderation_actions"
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    action_type: ActionType

    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id")))
    target_user_id: int = Field(sa_column=Column(BigInteger, (ForeignKey("global_users.discord_id"))))
    moderator_user_id: int = Field(sa_column=Column(BigInteger, (ForeignKey("global_users.discord_id"))))
    rule_id: Optional[UUID] = Field(default=None, foreign_key="moderation_rules.id")
    case_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("moderation_cases.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )

    reason: str
    commentary: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
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
    rule: Optional[ModerationRule] = Relationship(back_populates="moderation_actions")
    case: Optional["ModerationCase"] = Relationship(
        back_populates="primary_actions",
        sa_relationship_kwargs={"foreign_keys": "[ModerationAction.case_id]"},
    )
    case_links: List["ModerationCaseActionLink"] = Relationship(back_populates="moderation_action")
    deleted_message_links: List["ModerationActionDeletedMessageLink"] = Relationship(back_populates="moderation_action")
    rule_citations: List["ModerationActionRuleCitation"] = Relationship(back_populates="action")
    import_source_items: List["ModerationImportSourceItem"] = Relationship(back_populates="moderation_action")



class ModerationImportRun(SQLModel, table=True):
    __tablename__ = "moderation_import_runs"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    source: ModerationImportSource = Field(sa_column=Column(sa.String(length=50), nullable=False, index=True))
    status: ModerationImportRunStatus = Field(
        default=ModerationImportRunStatus.PENDING,
        sa_column=Column(sa.String(length=50), nullable=False, index=True),
    )
    dry_run: bool = Field(default=False, nullable=False)
    started_by_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True),
    )
    started_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    completed_at: Optional[datetime] = None
    summary_json: Optional[dict] = Field(default=None, sa_column=Column(sa.JSON, nullable=True))
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))


class ModerationImportSourceItem(SQLModel, table=True):
    __tablename__ = "moderation_import_source_items"
    __table_args__ = (
        UniqueConstraint("server_id", "source", "source_hash", name="uq_moderation_import_source_item"),
    )

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    import_run_id: UUID = Field(foreign_key="moderation_import_runs.id", nullable=False, index=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    source: ModerationImportSource = Field(sa_column=Column(sa.String(length=50), nullable=False, index=True))
    source_item_type: str = Field(sa_column=Column(sa.String(length=100), nullable=False, index=True))
    source_item_id: Optional[str] = Field(default=None, sa_column=Column(sa.String(length=255), nullable=True))
    source_hash: str = Field(sa_column=Column(sa.String(length=64), nullable=False, index=True))
    raw_payload_json: Optional[dict] = Field(default=None, sa_column=Column(sa.JSON, nullable=True))
    normalized_payload_json: Optional[dict] = Field(default=None, sa_column=Column(sa.JSON, nullable=True))
    confidence: ModerationImportConfidence = Field(
        default=ModerationImportConfidence.EXACT,
        sa_column=Column(sa.String(length=50), nullable=False),
    )
    status: ModerationImportItemStatus = Field(
        default=ModerationImportItemStatus.PENDING,
        sa_column=Column(sa.String(length=50), nullable=False, index=True),
    )
    moderation_action_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(sa.Uuid(), ForeignKey("moderation_actions.id", ondelete="SET NULL"), nullable=True, index=True),
    )
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    moderation_action: Optional[ModerationAction] = Relationship(back_populates="import_source_items")
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
    source: str = Field(default="manual", sa_column=Column(String(length=30), nullable=False, index=True))
    release_due_at: Optional[datetime] = Field(default=None, nullable=True, index=True)
    released_at: Optional[datetime] = Field(default=None, nullable=True)
    release_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
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


class ServerRbacAssignment(SQLModel, table=True):
    __tablename__ = "server_rbac_assignments"
    __table_args__ = (
        UniqueConstraint("server_id", "subject_type", "subject_id", name="uq_server_rbac_assignments_subject"),
    )

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    subject_type: str = Field(sa_column=Column(String(length=20), nullable=False, index=True))
    subject_id: str = Field(sa_column=Column(String(length=64), nullable=False, index=True))
    preset: Optional[str] = Field(default=None, sa_column=Column(String(length=50), nullable=True))
    permission_keys: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    updated_by_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    server: Server = Relationship(back_populates="rbac_assignments")
    created_by: GlobalUser = Relationship(
        back_populates="rbac_assignments_created",
        sa_relationship_kwargs={'foreign_keys': '[ServerRbacAssignment.created_by_user_id]'}
    )
    updated_by: GlobalUser = Relationship(
        back_populates="rbac_assignments_updated",
        sa_relationship_kwargs={'foreign_keys': '[ServerRbacAssignment.updated_by_user_id]'}
    )


class ServerRbacAuditEvent(SQLModel, table=True):
    __tablename__ = "server_rbac_audit_events"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    actor_user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=False, index=True))
    subject_type: str = Field(sa_column=Column(String(length=20), nullable=False, index=True))
    subject_id: str = Field(sa_column=Column(String(length=64), nullable=False, index=True))
    before_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    after_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False, index=True)

    server: Server = Relationship(back_populates="rbac_audit_events")
    actor: GlobalUser = Relationship(
        back_populates="rbac_audit_events",
        sa_relationship_kwargs={'foreign_keys': '[ServerRbacAuditEvent.actor_user_id]'}
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
    primary_actions: List["ModerationAction"] = Relationship(
        back_populates="case",
        sa_relationship_kwargs={"foreign_keys": "[ModerationAction.case_id]"},
    )
    action_links: List["ModerationCaseActionLink"] = Relationship(back_populates="moderation_case")
    users: List["ModerationCaseUser"] = Relationship(back_populates="moderation_case")
    rule_citations: List["ModerationCaseRuleCitation"] = Relationship(back_populates="moderation_case")


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


class ModerationActionRuleCitation(SQLModel, table=True):
    __tablename__ = "moderation_action_rules"
    __table_args__ = (UniqueConstraint("action_id", "rule_id", name="uq_action_rule_citation"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    action_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("moderation_actions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    rule_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("moderation_rules.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    rule_code_snapshot: Optional[str] = Field(default=None, nullable=True)
    rule_title_snapshot: str = Field(nullable=False)
    cited_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    rule_deleted_at: Optional[datetime] = Field(default=None, nullable=True)

    action: ModerationAction = Relationship(back_populates="rule_citations")
    rule: Optional[ModerationRule] = Relationship(back_populates="action_citations")


class ModerationCaseRuleCitation(SQLModel, table=True):
    __tablename__ = "moderation_case_rules"
    __table_args__ = (UniqueConstraint("case_id", "rule_id", name="uq_case_rule_citation"),)

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    case_id: UUID = Field(
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("moderation_cases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    rule_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("moderation_rules.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False, index=True))
    rule_code_snapshot: Optional[str] = Field(default=None, nullable=True)
    rule_title_snapshot: str = Field(nullable=False)
    cited_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    rule_deleted_at: Optional[datetime] = Field(default=None, nullable=True)

    moderation_case: ModerationCase = Relationship(back_populates="rule_citations")
    rule: Optional[ModerationRule] = Relationship(back_populates="case_citations")


class ModerationCaseNote(SQLModel, table=True):
    __tablename__ = "moderation_case_notes"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    case_id: UUID = Field(foreign_key="moderation_cases.id", nullable=False, index=True)
    author_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True),
    )
    note: str = Field(sa_column=Column(Text, nullable=False))
    is_internal: bool = True
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

    moderation_case: ModerationCase = Relationship(back_populates="notes")
    author: Optional[GlobalUser] = Relationship(back_populates="moderation_case_notes")


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
    server_id: int = Field(sa_column=Column(BigInteger, ForeignKey("servers.server_id"), nullable=False))
    channel_id: int = Field(sa_column=Column(BigInteger))
    trigger_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    owner_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("global_users.discord_id"), nullable=True))
    channel_name: str
    created_at: datetime
    deleted_at: Optional[datetime] = None
    archive_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    archive_message_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

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

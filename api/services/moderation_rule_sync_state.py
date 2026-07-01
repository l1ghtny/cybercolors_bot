from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from src.db.models import utcnow_utc_tz


class ModerationRuleSyncStatus(str, Enum):
    SYNCED = "synced"
    MANUAL = "manual"
    CONFLICT = "conflict"


class ModerationRuleSyncState(SQLModel, table=True):
    __tablename__ = "moderation_rule_sync_states"

    rule_id: UUID = Field(primary_key=True, foreign_key="moderation_rules.id")
    sync_status: str = Field(default=ModerationRuleSyncStatus.SYNCED.value, nullable=False, index=True)
    source_content_hash: str | None = Field(default=None, nullable=True, max_length=64)
    source_segment_hash: str | None = Field(default=None, nullable=True, max_length=64)
    sync_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow_utc_tz, nullable=False)

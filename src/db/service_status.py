from datetime import datetime

from sqlalchemy import Column, JSON, String, TIMESTAMP
from sqlmodel import Field, SQLModel


class BotRuntimeStatus(SQLModel, table=True):
    __tablename__ = "bot_runtime_status"

    profile: str = Field(sa_column=Column(String(32), primary_key=True))
    process_id: str = Field(sa_column=Column(String(36), nullable=False))
    started_at: datetime = Field(sa_column=Column(TIMESTAMP(timezone=True), nullable=False))
    observed_at: datetime = Field(sa_column=Column(TIMESTAMP(timezone=True), nullable=False))
    payload: dict = Field(sa_column=Column(JSON, nullable=False))


class ExternalServiceStatus(SQLModel, table=True):
    __tablename__ = "external_service_status"

    service: str = Field(sa_column=Column(String(32), primary_key=True))
    attempted_at: datetime | None = Field(default=None, sa_column=Column(TIMESTAMP(timezone=True)))
    observed_at: datetime | None = Field(default=None, sa_column=Column(TIMESTAMP(timezone=True)))
    incidents: list[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))

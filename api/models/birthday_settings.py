from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class BirthdaySettingsModel(BaseModel):
    server_id: str
    server_name: str | None = None
    birthday_channel_id: str | None = None
    birthday_channel_name: str | None = None
    birthday_role_id: str | None = None
    birthday_role_name: str | None = None


class BirthdayChannelUpdateModel(BaseModel):
    channel_id: str | None = Field(default=None, pattern=r"^\d+$")
    channel_name: str | None = None
    server_name: str | None = None

    @field_validator("channel_name")
    @classmethod
    def normalize_channel_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("server_name")
    @classmethod
    def normalize_server_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class BirthdayRoleUpdateModel(BaseModel):
    role_id: str | None = Field(default=None, pattern=r"^\d+$")
    role_name: str | None = None
    server_name: str | None = None

    @field_validator("role_name")
    @classmethod
    def normalize_role_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("server_name")
    @classmethod
    def normalize_server_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CelebrationMessageCreateModel(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    added_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        return value.strip()

    @field_validator("added_by_user_id")
    @classmethod
    def normalize_added_by_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CelebrationMessageUpdateModel(BaseModel):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        return value.strip()


class BirthdayActorModel(BaseModel):
    user_id: str
    username: str | None = None
    server_nickname: str | None = None
    display_name: str
    avatar_hash: str | None = None


class CelebrationMessageReadModel(BaseModel):
    id: str
    server_id: str
    message: str
    added_at: datetime
    added_by_user_id: str
    added_by_username: str | None = None
    added_by: BirthdayActorModel

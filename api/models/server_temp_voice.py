from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TempVoiceChannelRefModel(BaseModel):
    id: str
    name: str | None = None
    mention: str


class ServerTempVoicePermissionsModel(BaseModel):
    can_edit: bool = False


class ServerTempVoiceSettingsReadModel(BaseModel):
    server_id: str
    enabled: bool
    trigger_channel_id: str | None = None
    trigger_channel_name: str | None = None
    archive_channel_id: str | None = None
    archive_channel_name: str | None = None
    channel_name_template: str
    owner_manage_channel_enabled: bool
    updated_at: datetime
    permissions: ServerTempVoicePermissionsModel = Field(default_factory=ServerTempVoicePermissionsModel)


class ServerTempVoiceSettingsUpdateModel(BaseModel):
    enabled: bool | None = None
    trigger_channel_id: str | None = Field(default=None, pattern=r"^\d*$")
    archive_channel_id: str | None = Field(default=None, pattern=r"^\d*$")
    channel_name_template: str | None = Field(default=None, min_length=1, max_length=100)
    owner_manage_channel_enabled: bool | None = None

    @field_validator("channel_name_template")
    @classmethod
    def validate_channel_name_template(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("channel_name_template cannot be blank")
        if "{display_name}" not in cleaned and "{username}" not in cleaned:
            raise ValueError("channel_name_template must include {display_name} or {username}")
        return cleaned


class ServerTempVoiceCreateTriggerChannelModel(BaseModel):
    name: str = Field(default="CREATE", min_length=1, max_length=100)
    category_id: str | None = Field(default=None, pattern=r"^\d*$")
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be blank")
        return cleaned

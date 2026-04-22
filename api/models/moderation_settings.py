from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class ServerModerationSettingsReadModel(BaseModel):
    server_id: str
    mute_role_id: str | None = None
    mute_role_name: str | None = None
    default_mute_minutes: int
    max_mute_minutes: int
    auto_reconnect_voice_on_mute: bool
    mod_log_channel_id: str | None = None
    updated_at: datetime


class ServerModerationSettingsUpdateModel(BaseModel):
    mute_role_id: str | None = Field(default=None, pattern=r"^\d*$")
    default_mute_minutes: int | None = Field(default=None, ge=1, le=43200)
    max_mute_minutes: int | None = Field(default=None, ge=1, le=43200)
    auto_reconnect_voice_on_mute: bool | None = None
    mod_log_channel_id: str | None = Field(default=None, pattern=r"^\d*$")

    @model_validator(mode="after")
    def validate_durations(self):
        if (
            self.default_mute_minutes is not None
            and self.max_mute_minutes is not None
            and self.default_mute_minutes > self.max_mute_minutes
        ):
            raise ValueError("default_mute_minutes cannot be greater than max_mute_minutes")
        return self


class ServerModerationCreateMuteRoleModel(BaseModel):
    role_name: str = Field(default="Muted", min_length=1, max_length=100)

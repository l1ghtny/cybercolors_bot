from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class ServerModerationSettingsReadModel(BaseModel):
    server_id: str
    mute_role_id: str | None = None
    mute_role_name: str | None = None
    default_mute_minutes: int
    max_mute_minutes: int
    auto_reconnect_voice_on_mute: bool
    mod_log_channel_id: str | None = None
    activity_excluded_channel_ids: list[str] = Field(default_factory=list)
    updated_at: datetime


class ServerModerationSettingsUpdateModel(BaseModel):
    mute_role_id: str | None = Field(default=None, pattern=r"^\d*$")
    default_mute_minutes: int | None = Field(default=None, ge=1, le=43200)
    max_mute_minutes: int | None = Field(default=None, ge=1, le=43200)
    auto_reconnect_voice_on_mute: bool | None = None
    mod_log_channel_id: str | None = Field(default=None, pattern=r"^\d*$")
    activity_excluded_channel_ids: list[str] | None = None

    @field_validator("activity_excluded_channel_ids")
    @classmethod
    def validate_activity_excluded_channel_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        invalid: list[str] = []
        for raw_channel_id in value:
            channel_id = str(raw_channel_id).strip()
            if not channel_id.isdigit():
                invalid.append(str(raw_channel_id))
                continue
            if channel_id not in seen:
                seen.add(channel_id)
                normalized.append(channel_id)
        if invalid:
            sample = ", ".join(invalid[:5])
            raise ValueError(f"activity_excluded_channel_ids must contain only Discord numeric IDs. Invalid values: {sample}")
        return normalized

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


class ServerModerationSettingsTestResultModel(BaseModel):
    ok: bool
    error: str | None = None

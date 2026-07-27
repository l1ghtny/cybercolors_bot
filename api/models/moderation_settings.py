from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class ServerModerationSettingsReadModel(BaseModel):
    server_id: str
    mute_role_id: str | None = None
    mute_role_name: str | None = None
    default_mute_minutes: int
    max_mute_minutes: int
    mute_duration_presets: list[int]
    default_ban_minutes: int
    ban_duration_presets: list[int]
    auto_reconnect_voice_on_mute: bool
    mod_log_channel_id: str | None = None
    activity_excluded_channel_ids: list[str] = Field(default_factory=list)
    updated_at: datetime


class ServerModerationSettingsUpdateModel(BaseModel):
    mute_role_id: str | None = Field(default=None, pattern=r"^\d*$")
    default_mute_minutes: int | None = Field(default=None, ge=1, le=43200)
    max_mute_minutes: int | None = Field(default=None, ge=1, le=43200)
    mute_duration_presets: list[int] | None = None
    default_ban_minutes: int | None = Field(default=None, ge=1, le=43200)
    ban_duration_presets: list[int] | None = None
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

    @field_validator("mute_duration_presets", "ban_duration_presets")
    @classmethod
    def validate_duration_presets(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        normalized = sorted(set(value))
        if not normalized:
            raise ValueError("At least one duration preset is required")
        if len(normalized) > 23:
            raise ValueError("At most 23 duration presets are allowed")
        if any(minutes < 1 or minutes > 43200 for minutes in normalized):
            raise ValueError("Duration presets must be between 1 and 43200 minutes")
        return normalized

    @model_validator(mode="after")
    def validate_durations(self):
        if (
            self.default_mute_minutes is not None
            and self.max_mute_minutes is not None
            and self.default_mute_minutes > self.max_mute_minutes
        ):
            raise ValueError("default_mute_minutes cannot be greater than max_mute_minutes")
        if (
            self.mute_duration_presets is not None
            and self.max_mute_minutes is not None
            and any(minutes > self.max_mute_minutes for minutes in self.mute_duration_presets)
        ):
            raise ValueError("mute_duration_presets cannot exceed max_mute_minutes")
        return self


class ServerModerationCreateMuteRoleModel(BaseModel):
    role_name: str = Field(default="Muted", min_length=1, max_length=100)


class ServerModerationSettingsTestResultModel(BaseModel):
    ok: bool
    error: str | None = None

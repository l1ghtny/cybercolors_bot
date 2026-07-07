from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

TEMP_VOICE_ARCHIVE_POST_MODES = {"mod_log_fallback", "archive_channel", "off"}


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
    archive_post_mode: str
    channel_name_template: str
    owner_manage_channel_enabled: bool
    owner_rename_enabled: bool
    owner_user_limit_enabled: bool
    owner_control_allowed_role_ids: list[str] = Field(default_factory=list)
    updated_at: datetime
    permissions: ServerTempVoicePermissionsModel = Field(default_factory=ServerTempVoicePermissionsModel)


class ServerTempVoiceSettingsUpdateModel(BaseModel):
    enabled: bool | None = None
    trigger_channel_id: str | None = Field(default=None, pattern=r"^\d*$")
    archive_channel_id: str | None = Field(default=None, pattern=r"^\d*$")
    archive_post_mode: str | None = None
    channel_name_template: str | None = Field(default=None, min_length=1, max_length=100)
    owner_manage_channel_enabled: bool | None = None
    owner_rename_enabled: bool | None = None
    owner_user_limit_enabled: bool | None = None
    owner_control_allowed_role_ids: list[str] | None = None

    @field_validator("owner_control_allowed_role_ids")
    @classmethod
    def validate_owner_control_allowed_role_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            role_id = str(item).strip()
            if not role_id:
                continue
            if not role_id.isdigit():
                raise ValueError("owner_control_allowed_role_ids must contain Discord role IDs")
            if role_id not in seen:
                cleaned.append(role_id)
                seen.add(role_id)
        return cleaned

    @field_validator("archive_post_mode")
    @classmethod
    def validate_archive_post_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned not in TEMP_VOICE_ARCHIVE_POST_MODES:
            allowed = ", ".join(sorted(TEMP_VOICE_ARCHIVE_POST_MODES))
            raise ValueError(f"archive_post_mode must be one of: {allowed}")
        return cleaned

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


class TempVoiceArchiveAttachmentModel(BaseModel):
    storage_key: str | None = None
    file_name: str | None = None
    content_type: str | None = None
    deleted: bool = False


class TempVoiceArchiveMessageModel(BaseModel):
    id: str
    message_id: str
    user_id: str | None = None
    content: str | None = None
    created_at: datetime
    deleted_at: datetime | None = None
    deleted: bool = False
    reply_to_message_id: str | None = None
    attachments: list[TempVoiceArchiveAttachmentModel] = Field(default_factory=list)


class TempVoiceArchiveSummaryModel(BaseModel):
    id: UUID
    server_id: str
    channel_id: str
    channel_name: str
    trigger_channel_id: str | None = None
    owner_user_id: str | None = None
    created_at: datetime
    deleted_at: datetime | None = None
    archive_channel_id: str | None = None
    archive_message_id: str | None = None
    archive_jump_url: str | None = None
    message_count: int
    deleted_message_count: int
    attachment_count: int
    deleted_attachment_count: int


class TempVoiceArchiveDetailModel(TempVoiceArchiveSummaryModel):
    messages: list[TempVoiceArchiveMessageModel] = Field(default_factory=list)

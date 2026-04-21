from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.db.models import CaseStatus, CaseUserRole, EvidenceType


class ModerationActorModel(BaseModel):
    user_id: str
    username: str | None = None
    server_nickname: str | None = None
    display_name: str
    avatar_hash: str | None = None


class ModerationCaseCreateModel(BaseModel):
    target_user_id: str = Field(pattern=r"^\d+$")
    opened_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")
    title: str = Field(min_length=1, max_length=300)
    summary: str | None = Field(default=None, max_length=5000)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ModerationCaseStatusUpdateModel(BaseModel):
    status: CaseStatus
    closed_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class ModerationCaseReadModel(BaseModel):
    id: str
    server_id: str
    title: str
    summary: str | None = None
    status: CaseStatus
    created_at: datetime
    closed_at: datetime | None = None
    target_user: ModerationActorModel
    opened_by: ModerationActorModel
    closed_by: ModerationActorModel | None = None
    users: list["ModerationCaseUserReadModel"] = Field(default_factory=list)
    linked_action_ids: list[str] = Field(default_factory=list)


class ModerationCaseNoteCreateModel(BaseModel):
    author_user_id: str | None = Field(default=None, pattern=r"^\d*$")
    note: str = Field(min_length=1, max_length=10000)
    is_internal: bool = True

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str) -> str:
        return value.strip()


class ModerationCaseNoteReadModel(BaseModel):
    id: str
    case_id: str
    note: str
    is_internal: bool
    created_at: datetime
    author: ModerationActorModel


class ModerationCaseEvidenceCreateModel(BaseModel):
    added_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")
    evidence_type: EvidenceType
    url: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=10000)
    attachment_key: str | None = Field(default=None, max_length=512)

    @field_validator("url", "text", "attachment_key")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ModerationCaseEvidenceReadModel(BaseModel):
    id: str
    case_id: str
    evidence_type: EvidenceType
    url: str | None = None
    text: str | None = None
    attachment_key: str | None = None
    created_at: datetime
    added_by: ModerationActorModel


class ModerationEvidenceUploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=128)

    @field_validator("filename", "content_type")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ModerationEvidenceUploadUrlResponse(BaseModel):
    upload_url: str
    key: str
    method: str = "PUT"


class ModerationCaseActionLinkCreateModel(BaseModel):
    moderation_action_id: str
    linked_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class ModerationCaseUserAddModel(BaseModel):
    user_id: str = Field(pattern=r"^\d+$")
    role: CaseUserRole = CaseUserRole.RELATED
    added_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class ModerationCaseUserReadModel(BaseModel):
    id: str
    role: CaseUserRole
    added_at: datetime
    added_by: ModerationActorModel
    user: ModerationActorModel


class DeletedMessageCreateModel(BaseModel):
    linked_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")
    message_id: str = Field(pattern=r"^\d+$")
    channel_id: str = Field(pattern=r"^\d+$")
    author_user_id: str | None = Field(default=None, pattern=r"^\d*$")
    content: str | None = Field(default=None, max_length=12000)
    attachments_json: str | None = Field(default=None, max_length=20000)
    deleted_at: datetime | None = None
    deleted_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")

    @field_validator("content", "attachments_json")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class DeletedMessageAttachmentModel(BaseModel):
    storage_key: str | None = None
    file_name: str | None = None
    content_type: str | None = None


class DeletedMessageReadModel(BaseModel):
    id: str
    server_id: str
    message_id: str
    channel_id: str
    channel_name: str | None = None
    content: str | None = None
    attachments_json: str | None = None
    attachments: list[DeletedMessageAttachmentModel] = Field(default_factory=list)
    deleted_at: datetime
    author: ModerationActorModel | None = None
    deleted_by: ModerationActorModel | None = None


class DeletedMessageLinkModel(BaseModel):
    linked_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class ModerationCaseDetailsModel(BaseModel):
    case: ModerationCaseReadModel
    notes: list[ModerationCaseNoteReadModel]
    evidence: list[ModerationCaseEvidenceReadModel]
    linked_actions: list[str]


ModerationCaseReadModel.model_rebuild()

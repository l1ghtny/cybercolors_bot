from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from src.modules.ai.youtube_urls import YouTubeUrlError, normalize_youtube_video_url

AIKnowledgeSourceType = Literal[
    "text",
    "admin_note",
    "server_note",
    "file",
    "youtube",
    "discord_message",
    "message_collection",
]
AIKnowledgeSubjectType = Literal["server", "admin"]
AIKnowledgeVisibility = Literal["public_answer", "admin_answer", "moderation"]
AIKnowledgeSourceStatus = Literal["draft", "queued", "processing", "ready", "failed", "disabled", "deleted"]
AIKnowledgeJobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class AIKnowledgeSourceCreateModel(BaseModel):
    source_type: AIKnowledgeSourceType = "text"
    subject_type: AIKnowledgeSubjectType = "server"
    subject_user_id: int | None = None
    visibility: AIKnowledgeVisibility = "public_answer"
    title: str = Field(min_length=1, max_length=255)
    content_text: str | None = Field(default=None, max_length=500_000)
    source_url: str | None = Field(default=None, max_length=4000)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    queue_index: bool = True

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()

    @field_validator("content_text", "source_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @model_validator(mode="after")
    def normalize_subject_and_type(self):
        if self.source_type == "admin_note":
            self.source_type = "text"
            self.subject_type = "admin"
        elif self.source_type == "server_note":
            self.source_type = "text"
            self.subject_type = "server"

        if self.subject_type == "admin" and self.subject_user_id is None:
            raise ValueError("subject_user_id is required when subject_type is admin")
        if self.subject_type == "server":
            self.subject_user_id = None
        if self.source_type == "youtube":
            if not self.source_url:
                raise PydanticCustomError("youtube_url_missing", "A YouTube video URL is required.")
            try:
                self.source_url = normalize_youtube_video_url(self.source_url).canonical_url
            except YouTubeUrlError as exc:
                raise PydanticCustomError(exc.code, str(exc)) from exc
        return self


class AIKnowledgeSourceUpdateModel(BaseModel):
    source_type: AIKnowledgeSourceType | None = None
    subject_type: AIKnowledgeSubjectType | None = None
    subject_user_id: int | None = None
    visibility: AIKnowledgeVisibility | None = None
    status: AIKnowledgeSourceStatus | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content_text: str | None = Field(default=None, max_length=500_000)
    source_url: str | None = Field(default=None, max_length=4000)
    metadata_json: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("content_text", "source_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @model_validator(mode="after")
    def normalize_subject_and_type(self):
        if self.source_type == "admin_note":
            self.source_type = "text"
            self.subject_type = "admin"
        elif self.source_type == "server_note":
            self.source_type = "text"
            self.subject_type = "server"

        if self.subject_type == "server":
            self.subject_user_id = None
        if self.subject_type == "admin" and "subject_user_id" in self.model_fields_set and self.subject_user_id is None:
            raise ValueError("subject_user_id is required when subject_type is admin")
        return self


class AIKnowledgeSourceReadModel(BaseModel):
    id: str
    server_id: str
    source_type: str
    subject_type: str
    subject_user_id: str | None = None
    status: str
    visibility: str
    title: str | None = None
    content_text: str | None = None
    source_url: str | None = None
    storage_key: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_by_user_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None = None
    deleted_at: datetime | None = None


class AIKnowledgeSourceListModel(BaseModel):
    items: list[AIKnowledgeSourceReadModel] = Field(default_factory=list)


class AIKnowledgeJobReadModel(BaseModel):
    id: str
    server_id: str
    source_id: str | None = None
    job_type: str
    status: str
    dedupe_key: str
    attempt_count: int
    run_after: datetime
    locked_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    source_title: str | None = None
    source_type: str | None = None
    subject_type: str | None = None
    subject_user_id: str | None = None
    visibility: str | None = None
    created_at: datetime
    updated_at: datetime


class AIKnowledgeJobListModel(BaseModel):
    items: list[AIKnowledgeJobReadModel] = Field(default_factory=list)


class AIKnowledgeSearchRequestModel(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    visibility: AIKnowledgeVisibility = "public_answer"
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return value.strip()


class AIKnowledgeSearchResultModel(BaseModel):
    source_id: str
    source_type: str
    subject_type: str
    subject_user_id: str | None = None
    title: str | None = None
    visibility: str
    chunk_id: str
    chunk_ordinal: int
    text: str
    score: float
    distance: float
    source_url: str | None = None
    indexed_at: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None


class AIKnowledgeSearchResponseModel(BaseModel):
    items: list[AIKnowledgeSearchResultModel] = Field(default_factory=list)


class AIKnowledgeProcessOneResponseModel(BaseModel):
    processed: bool

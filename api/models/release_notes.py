from datetime import datetime

from pydantic import BaseModel, Field


class LocalizedReleaseTextModel(BaseModel):
    en: str
    ru: str


class ReleaseNoteReadModel(BaseModel):
    id: str
    published_at: datetime
    title: LocalizedReleaseTextModel
    summary: LocalizedReleaseTextModel
    changes: list[LocalizedReleaseTextModel] = Field(default_factory=list)


class ReleaseNotesManifestModel(BaseModel):
    releases: list[ReleaseNoteReadModel] = Field(default_factory=list)

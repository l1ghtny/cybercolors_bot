from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LocalizedReleaseTextModel(BaseModel):
    en: str
    ru: str


class ReleaseNoteActionModel(BaseModel):
    label: LocalizedReleaseTextModel
    path: str


class ReleaseNoteReadModel(BaseModel):
    id: str
    published_at: datetime
    title: LocalizedReleaseTextModel
    summary: LocalizedReleaseTextModel
    change_type: Literal["added", "fixed", "improved"]
    surface: Literal["dashboard", "bot", "both"]
    feature: LocalizedReleaseTextModel
    action: ReleaseNoteActionModel | None = None
    changes: list[LocalizedReleaseTextModel] = Field(default_factory=list)


class ReleaseNotesManifestModel(BaseModel):
    releases: list[ReleaseNoteReadModel] = Field(default_factory=list)


class PublicProductUpdateActionModel(BaseModel):
    label: LocalizedReleaseTextModel
    url: str


class PublicProductUpdateReadModel(BaseModel):
    id: str
    slug: str
    published_at: datetime
    title: LocalizedReleaseTextModel
    summary: LocalizedReleaseTextModel
    change_type: Literal["added", "fixed", "improved"]
    surface: Literal["dashboard", "bot", "both"]
    feature: LocalizedReleaseTextModel
    action: PublicProductUpdateActionModel | None = None
    image_url: str | None = None


class PublicProductUpdatesManifestModel(BaseModel):
    updates: list[PublicProductUpdateReadModel] = Field(default_factory=list)

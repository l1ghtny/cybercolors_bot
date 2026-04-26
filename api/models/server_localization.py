from datetime import datetime

from pydantic import BaseModel, Field


class ServerLocalizationSettingsReadModel(BaseModel):
    server_id: str
    locale_code: str
    supported_locales: list[str]
    updated_at: datetime


class ServerLocalizationSettingsUpdateModel(BaseModel):
    locale_code: str = Field(min_length=2, max_length=10)

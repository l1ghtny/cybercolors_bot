import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


MAX_OVERVIEW_ROLE_COUNT = 6


class ServerOverviewSettingsReadModel(BaseModel):
    server_id: str
    role_ids: list[str] = Field(default_factory=list)
    updated_at: datetime


class ServerOverviewSettingsUpdateModel(BaseModel):
    role_ids: list[str] = Field(default_factory=list)

    @field_validator("role_ids", mode="before")
    @classmethod
    def normalize_role_ids(cls, raw_role_ids):
        if not isinstance(raw_role_ids, list):
            return raw_role_ids

        normalized: list[str] = []
        seen: set[str] = set()
        for raw_role_id in raw_role_ids:
            role_id = str(raw_role_id).strip()
            if not re.fullmatch(r"[0-9]{1,20}", role_id):
                raise ValueError("Role IDs must be Discord snowflakes")
            if role_id not in seen:
                normalized.append(role_id)
                seen.add(role_id)

        if len(normalized) > MAX_OVERVIEW_ROLE_COUNT:
            raise ValueError(f"At most {MAX_OVERVIEW_ROLE_COUNT} roles can be shown")
        return normalized

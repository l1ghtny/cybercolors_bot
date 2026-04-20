from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


MAX_DAYS_BY_MONTH = {
    1: 31,
    2: 28,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}


class BirthdayWriteModel(BaseModel):
    day: int = Field(ge=1, le=31)
    month: int = Field(ge=1, le=12)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def normalize_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_day_for_month(self):
        max_day = MAX_DAYS_BY_MONTH[self.month]
        if self.day > max_day:
            raise ValueError(f"Invalid day {self.day} for month {self.month}")
        return self


class BirthdayCreateModel(BirthdayWriteModel):
    user_id: str = Field(min_length=1, pattern=r"^\d+$")


class BirthdayReadModel(BaseModel):
    user_id: str
    username: str | None = None
    server_nickname: str | None = None
    display_name: str
    avatar_hash: str | None = None
    day: int
    month: int
    timezone: str | None = None
    role_added_at: datetime | None = None


class ServerBirthdayUserModel(BaseModel):
    user_id: str
    username: str | None = None
    server_nickname: str | None = None
    display_name: str
    avatar_hash: str | None = None
    has_birthday: bool
    birthday: BirthdayWriteModel | None = None

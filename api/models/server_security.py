from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ServerSecuritySettingsReadModel(BaseModel):
    server_id: str
    verified_role_id: str | None = None
    verified_role_name: str | None = None
    newcomer_role_id: str | None = None
    newcomer_role_name: str | None = None
    newcomer_restriction_enabled: bool = False
    newcomer_auto_release_minutes: int | None = None
    normal_permissions: str | None = None
    lockdown_permissions: str | None = None
    lockdown_enabled: bool
    updated_at: datetime


class ServerSecurityVerifiedRoleUpdateModel(BaseModel):
    role_id: str | None = Field(default=None, pattern=r"^\d*$")


class ServerSecurityPermissionsUpdateModel(BaseModel):
    normal_permissions: str | None = Field(default=None, pattern=r"^\d*$")
    lockdown_permissions: str | None = Field(default=None, pattern=r"^\d*$")


class ServerSecurityNewcomerRoleUpdateModel(BaseModel):
    role_id: str | None = Field(default=None, pattern=r"^\d*$")
    enabled: bool | None = None
    auto_release_minutes: int | None = Field(default=None, ge=0, le=43200)


class ServerSecurityRoleSuggestionModel(BaseModel):
    purpose: str
    role_name: str
    permissions: str
    mentionable: bool
    hoist: bool
    color: int | None = None
    reason: str


class ServerSecurityCreateNewcomerRoleModel(BaseModel):
    role_name: str = Field(default="Newcomer", min_length=1, max_length=100)
    permissions: str = Field(default="0", pattern=r"^\d+$")
    mentionable: bool = False
    hoist: bool = False
    color: int | None = Field(default=None, ge=0, le=0xFFFFFF)
    enabled: bool = True
    auto_release_minutes: int | None = Field(default=None, ge=0, le=43200)

    @field_validator("role_name")
    @classmethod
    def validate_role_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("role_name cannot be blank")
        return normalized


class ServerSecurityLockdownUpdateModel(BaseModel):
    enabled: bool

from datetime import datetime

from pydantic import BaseModel, Field


class ServerSecuritySettingsReadModel(BaseModel):
    server_id: str
    verified_role_id: str | None = None
    verified_role_name: str | None = None
    normal_permissions: str | None = None
    lockdown_permissions: str | None = None
    lockdown_enabled: bool
    updated_at: datetime


class ServerSecurityVerifiedRoleUpdateModel(BaseModel):
    role_id: str | None = Field(default=None, pattern=r"^\d*$")


class ServerSecurityPermissionsUpdateModel(BaseModel):
    normal_permissions: str | None = Field(default=None, pattern=r"^\d*$")
    lockdown_permissions: str | None = Field(default=None, pattern=r"^\d*$")


class ServerSecurityLockdownUpdateModel(BaseModel):
    enabled: bool

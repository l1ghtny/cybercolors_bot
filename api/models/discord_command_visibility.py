from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SNOWFLAKE_PATTERN = r"^\d+$"


class DiscordCommandPermissionOverwriteModel(BaseModel):
    id: str
    type: Literal["role", "user", "channel"]
    permission: bool

    @field_validator("id")
    @classmethod
    def validate_snowflake(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("Discord permission subject IDs must be numeric snowflakes")
        return value


class DiscordCommandVisibilityChildModel(BaseModel):
    qualified_name: str
    description: str | None = None
    native_target_id: str
    independently_configurable: bool = False
    required_rbac_permissions: list[str] = Field(default_factory=list)


class DiscordCommandVisibilityCommandModel(BaseModel):
    command_id: str
    name: str
    discord_type: str
    source: Literal["global", "guild"]
    description: str | None = None
    default_member_permissions: str | None = None
    inherits_application_permissions: bool
    permissions: list[DiscordCommandPermissionOverwriteModel] = Field(default_factory=list)
    children: list[DiscordCommandVisibilityChildModel] = Field(default_factory=list)
    uncatalogued: bool = False


class DiscordCommandVisibilityReadModel(BaseModel):
    application_id: str
    server_id: str
    snapshot_id: str
    fetched_at: datetime
    oauth_scope_granted: bool
    native_permissions_sufficient: bool
    application_permissions: list[DiscordCommandPermissionOverwriteModel] = Field(default_factory=list)
    commands: list[DiscordCommandVisibilityCommandModel] = Field(default_factory=list)
    max_overwrites_per_target: int = 100


class DiscordCommandVisibilityTargetUpdateModel(BaseModel):
    target_id: str
    target_kind: Literal["application", "command"]
    permissions: list[DiscordCommandPermissionOverwriteModel]

    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("Discord command target IDs must be numeric snowflakes")
        return value

    @model_validator(mode="after")
    def validate_permissions(self):
        if len(self.permissions) > 100:
            raise ValueError("Discord supports at most 100 permission overwrites per target")
        subjects = [(item.type, item.id) for item in self.permissions]
        if len(subjects) != len(set(subjects)):
            raise ValueError("Duplicate Discord permission subjects are not allowed")
        return self


class DiscordCommandVisibilityWriteModel(BaseModel):
    # Optional during the rolling frontend/backend deployment. The redesigned
    # dashboard always sends it; older deployed clients can still save until
    # the frontend rollout finishes.
    snapshot_id: str | None = Field(default=None, min_length=1)
    updates: list[DiscordCommandVisibilityTargetUpdateModel] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_targets(self):
        targets = [(item.target_kind, item.target_id) for item in self.updates]
        if len(targets) != len(set(targets)):
            raise ValueError("Duplicate Discord command visibility targets are not allowed")
        return self


class DiscordCommandVisibilityApplyResultModel(BaseModel):
    target_id: str
    ok: bool
    permissions: list[DiscordCommandPermissionOverwriteModel] = Field(default_factory=list)
    status: int | None = None
    error_code: str | None = None
    detail: str | None = None


class DiscordCommandVisibilityWriteResponseModel(BaseModel):
    complete: bool
    results: list[DiscordCommandVisibilityApplyResultModel]

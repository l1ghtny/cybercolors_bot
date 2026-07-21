from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


SUPPORTED_RBAC_SUBJECT_TYPES = {"user", "role"}


class RbacPermissionModel(BaseModel):
    key: str
    group: str
    label: str
    description: str
    risk_level: Literal["read_only", "change", "high_impact", "administration"]
    surfaces: list[Literal["dashboard", "discord"]]
    related_command_ids: list[str] = Field(default_factory=list)


class RbacPresetModel(BaseModel):
    key: str
    label: str
    description: str
    permission_keys: list[str]


class RbacCatalogModel(BaseModel):
    permissions: list[RbacPermissionModel]
    presets: list[RbacPresetModel]


class RbacAssignmentWriteModel(BaseModel):
    preset: str | None = None
    permission_keys: list[str] = Field(default_factory=list)

    @field_validator("preset")
    @classmethod
    def normalize_preset(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("permission_keys")
    @classmethod
    def normalize_permission_keys(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            permission_key = item.strip()
            if permission_key and permission_key not in seen:
                normalized.append(permission_key)
                seen.add(permission_key)
        return normalized


class RbacAssignmentReadModel(BaseModel):
    id: UUID
    server_id: str
    subject_type: str
    subject_id: str
    preset: str | None = None
    permission_keys: list[str]
    effective_permission_keys: list[str]
    created_by_user_id: str
    updated_by_user_id: str
    created_at: datetime
    updated_at: datetime


class RbacAssignmentsReadModel(BaseModel):
    server_id: str
    assignments: list[RbacAssignmentReadModel]


class RbacEffectivePermissionsModel(BaseModel):
    server_id: str
    user_id: str
    permission_keys: list[str]
    matched_role_ids: list[str] = Field(default_factory=list)
    direct_assignment: RbacAssignmentReadModel | None = None
    role_assignments: list[RbacAssignmentReadModel] = Field(default_factory=list)
    owner_fallback_applied: bool = False
    admin_fallback_applied: bool = False


class RbacCheckRequestModel(BaseModel):
    permission_keys: list[str] = Field(min_length=1, max_length=100)

    @field_validator("permission_keys")
    @classmethod
    def normalize_permission_keys(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            permission_key = item.strip()
            if permission_key and permission_key not in seen:
                normalized.append(permission_key)
                seen.add(permission_key)
        return normalized


class RbacCheckResponseModel(BaseModel):
    server_id: str
    user_id: str
    results: dict[str, bool]
    permission_keys: list[str]


def validate_subject_path(subject_type: str, subject_id: str) -> tuple[str, str]:
    normalized_type = subject_type.strip().lower()
    normalized_id = subject_id.strip()
    if normalized_type not in SUPPORTED_RBAC_SUBJECT_TYPES:
        raise ValueError("RBAC subject type must be user or role")
    if not normalized_id.isdigit():
        raise ValueError("RBAC user and role subject IDs must be Discord numeric IDs")
    return normalized_type, normalized_id

from datetime import datetime

from pydantic import BaseModel, Field

from api.models.moderation_cases import ModerationActorModel


class DashboardAccessAddUserModel(BaseModel):
    user_id: str = Field(pattern=r"^\d+$")


class DashboardAccessAddRoleModel(BaseModel):
    role_id: str = Field(pattern=r"^\d+$")


class DashboardAccessRoleReadModel(BaseModel):
    role_id: str
    role_name: str | None = None
    created_at: datetime
    added_by: ModerationActorModel | None = None


class DashboardAccessUserReadModel(BaseModel):
    user: ModerationActorModel
    created_at: datetime
    added_by: ModerationActorModel | None = None


class DashboardAccessReadModel(BaseModel):
    server_id: str
    users: list[DashboardAccessUserReadModel]
    roles: list[DashboardAccessRoleReadModel]

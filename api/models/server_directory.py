from pydantic import BaseModel, Field


class ServerChannelModel(BaseModel):
    id: str
    name: str
    type: int
    position: int = 0
    parent_id: str | None = None
    parent_name: str | None = None


class ServerRoleModel(BaseModel):
    id: str
    name: str
    color: int
    position: int
    managed: bool


class ServerUserModel(BaseModel):
    user_id: str
    display_name: str
    username: str | None = None
    avatar_hash: str | None = None
    is_member: bool


class ServerUsersLookupRequest(BaseModel):
    user_ids: list[str] = Field(default_factory=list, max_length=500)


class ServerMetadataModel(BaseModel):
    server_id: str
    name: str | None = None
    icon: str | None = None
    member_count: int | None = None
    owner_id: str | None = None
    features: list[str] = Field(default_factory=list)
    birthday_channel_id: str | None = None
    birthday_channel_name: str | None = None
    birthday_role_id: str | None = None
    birthday_role_name: str | None = None

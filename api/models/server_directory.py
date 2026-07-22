from pydantic import BaseModel, Field


class ServerChannelModel(BaseModel):
    id: str
    name: str
    type: int
    position: int = 0
    parent_id: str | None = None
    parent_name: str | None = None
    rate_limit_per_user: int = 0


class ServerRoleModel(BaseModel):
    id: str
    name: str
    color: int
    position: int
    managed: bool
    permissions: str = "0"


class ServerEmojiModel(BaseModel):
    id: str
    name: str
    animated: bool = False
    available: bool = True
    managed: bool = False


class ServerUserModel(BaseModel):
    user_id: str
    display_name: str
    username: str | None = None
    server_nickname: str | None = None
    avatar_hash: str | None = None
    is_member: bool
    role_ids: list[str] = Field(default_factory=list)
    joined_at: str | None = None
    is_bot: bool = False
    is_owner: bool = False
    priority_role_id: str | None = None


class ServerMemberPageModel(BaseModel):
    items: list[ServerUserModel] = Field(default_factory=list)
    total: int
    offset: int
    limit: int


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

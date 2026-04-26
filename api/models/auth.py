from pydantic import BaseModel, ConfigDict, Field


class AuthLoginRequestModel(BaseModel):
    code: str = Field(min_length=1, description="Discord OAuth2 authorization code.")
    redirect_uri: str | None = Field(
        default=None,
        description="Optional redirect URI override sent by frontend.",
    )


class AuthUserModel(BaseModel):
    discord_id: str
    username: str | None = None
    avatar_hash: str | None = None


class AuthLoginResponseModel(BaseModel):
    message: str
    user: AuthUserModel
    access_token: str
    token_type: str


class AuthGuildModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    icon: str | None = None
    owner: bool = False
    permissions: str = "0"
    bot_present: bool = True
    dashboard_access: bool = True

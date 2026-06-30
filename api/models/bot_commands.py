from pydantic import BaseModel, Field


class BotCommandChoiceModel(BaseModel):
    name: str
    value: str


class BotCommandParameterModel(BaseModel):
    name: str
    type: str
    required: bool = True
    description: str
    default: str | None = None
    choices: list[BotCommandChoiceModel] = Field(default_factory=list)
    autocomplete: bool = False


class BotCommandComponentModel(BaseModel):
    type: str
    label: str
    description: str


class BotCommandDocModel(BaseModel):
    id: str
    name: str
    qualified_name: str
    invoke: str
    category: str
    discord_type: str = "slash_command"
    summary: str
    required_permissions: list[str] = Field(default_factory=list)
    required_rbac_permissions: list[str] = Field(default_factory=list)
    parameters: list[BotCommandParameterModel] = Field(default_factory=list)
    components: list[BotCommandComponentModel] = Field(default_factory=list)
    workflow: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BotCommandDocsResponseModel(BaseModel):
    version: str
    locale: str
    available_locales: list[str]
    commands: list[BotCommandDocModel]

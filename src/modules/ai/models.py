from dataclasses import dataclass, field
from typing import Any, Literal


AITask = Literal["moderation", "assistant"]
AIMessageRole = Literal["system", "user", "assistant", "tool"]
AIImageSource = Literal["attachment", "custom_emoji"]
ModerationSeverity = Literal["none", "low", "medium", "high"]
ModerationAction = Literal["none", "watch", "warn", "mute", "kick", "ban", "manual_review"]


DEFAULT_AI_MODEL = "gpt-5.4-nano"


@dataclass(slots=True)
class AIImageInput:
    url: str
    source: AIImageSource
    label: str | None = None
    content_type: str | None = None
    size: int | None = None
    detail: Literal["low", "high", "auto"] = "low"


@dataclass(slots=True)
class AIMessage:
    role: AIMessageRole
    content: str
    name: str | None = None
    images: list[AIImageInput] = field(default_factory=list)


@dataclass(slots=True)
class AIToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class AIToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AIToolResult:
    call_id: str
    output: dict[str, Any] | list[dict[str, Any]] | str


@dataclass(slots=True)
class AIRequest:
    task: AITask
    system_prompt: str
    messages: list[AIMessage]
    model: str = DEFAULT_AI_MODEL
    temperature: float | None = None
    max_output_tokens: int | None = 1024
    metadata: dict[str, Any] = field(default_factory=dict)
    tools: list[AIToolSpec] = field(default_factory=list)
    tool_results: list[AIToolResult] = field(default_factory=list)
    max_tool_calls: int | None = None
    previous_response_id: str | None = None


@dataclass(slots=True)
class AIResponse:
    content: str | None
    model: str
    provider: str
    total_tokens: int = 0
    tool_call_count: int = 0
    raw: Any | None = None
    tool_calls: list[AIToolCall] = field(default_factory=list)
    id: str | None = None


@dataclass(slots=True)
class ModerationVerdict:
    flagged: bool
    severity: ModerationSeverity = "none"
    categories: list[str] = field(default_factory=list)
    reason: str = ""
    suggested_action: ModerationAction = "none"
    rule_ids: list[str] = field(default_factory=list)
    raw_response: AIResponse | None = None


@dataclass(slots=True)
class MessageModerationInput:
    content: str
    server_id: int | None = None
    author_user_id: int | None = None
    channel_id: int | None = None
    message_id: int | None = None
    author_display_name: str | None = None
    author_is_bot: bool = False
    server_locale: str | None = None
    bot_user_id: int | None = None
    mentioned_users: list[dict[str, Any]] = field(default_factory=list)
    current_bot_mentioned: bool = False
    answer_flow_invocation: bool = False
    images: list[AIImageInput] = field(default_factory=list)


@dataclass(slots=True)
class AssistantInput:
    content: str
    server_id: int | None = None
    author_user_id: int | None = None
    channel_id: int | None = None
    conversation: list[AIMessage] = field(default_factory=list)
    images: list[AIImageInput] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AIContext:
    server_id: int | None = None
    user_id: int | None = None
    channel_id: int | None = None
    server_name: str | None = None
    channel: dict[str, Any] | None = None
    active_rules: list[dict[str, Any]] = field(default_factory=list)
    member_profile: dict[str, Any] | None = None
    server_notes: list[dict[str, Any]] = field(default_factory=list)
    admin_notes: list[dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (
                self.server_name,
                self.channel,
                self.active_rules,
                self.member_profile,
                self.server_notes,
                self.admin_notes,
            )
        )

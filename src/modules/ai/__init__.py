from importlib import import_module
from typing import Any


_AI_MAIN_EXPORTS = {"AIMain", "ai_main_class"}
_MODEL_EXPORTS = {
    "AIContext",
    "AIMessage",
    "AIRequest",
    "AIResponse",
    "AIResponseFormat",
    "AssistantInput",
    "MessageModerationInput",
    "ModerationVerdict",
}

__all__ = [
    "AIContext",
    "AIMessage",
    "AIMain",
    "AIRequest",
    "AIResponse",
    "AIResponseFormat",
    "AssistantInput",
    "MessageModerationInput",
    "ModerationVerdict",
    "ai_main_class",
]


def __getattr__(name: str) -> Any:
    if name in _AI_MAIN_EXPORTS:
        module = import_module("src.modules.ai.ai_main")
    elif name in _MODEL_EXPORTS:
        module = import_module("src.modules.ai.models")
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(module, name)
    globals()[name] = value
    return value

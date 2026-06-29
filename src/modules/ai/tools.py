from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from src.modules.ai.context import get_active_rules_context, get_member_profile_context

AIToolHandler = Callable[..., Awaitable[dict[str, Any] | list[dict[str, Any]]]]


@dataclass(slots=True)
class AITool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: AIToolHandler
    requires_admin_context: bool = False


@dataclass(slots=True)
class AIToolRegistry:
    tools: dict[str, AITool] = field(default_factory=dict)

    def register(self, tool: AITool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> AITool | None:
        return self.tools.get(name)

    def as_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "requires_admin_context": tool.requires_admin_context,
            }
            for tool in self.tools.values()
        ]


async def _active_rules_tool(*, session: AsyncSession, server_id: int) -> list[dict[str, Any]]:
    return await get_active_rules_context(session=session, server_id=server_id)


async def _member_profile_tool(
    *,
    session: AsyncSession,
    server_id: int,
    user_id: int,
) -> dict[str, Any]:
    return await get_member_profile_context(session=session, server_id=server_id, user_id=user_id)


def build_default_tool_registry() -> AIToolRegistry:
    registry = AIToolRegistry()
    registry.register(
        AITool(
            name="get_active_rules",
            description="Fetch active moderation rules for one Discord server.",
            parameters={
                "type": "object",
                "properties": {"server_id": {"type": "integer"}},
                "required": ["server_id"],
            },
            handler=_active_rules_tool,
            requires_admin_context=False,
        )
    )
    registry.register(
        AITool(
            name="get_member_profile",
            description="Fetch bounded member context, including birthday, moderation history, cases, and activity summary.",
            parameters={
                "type": "object",
                "properties": {
                    "server_id": {"type": "integer"},
                    "user_id": {"type": "integer"},
                },
                "required": ["server_id", "user_id"],
            },
            handler=_member_profile_tool,
            requires_admin_context=True,
        )
    )
    return registry

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from src.modules.ai.context import get_active_rules_context, get_member_profile_context
from src.modules.ai.knowledge import search_server_knowledge
from src.modules.ai.models import AIToolSpec

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

    def specs(self, *, include_admin_tools: bool = False) -> list[AIToolSpec]:
        return [
            AIToolSpec(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in self.tools.values()
            if include_admin_tools or not tool.requires_admin_context
        ]

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
    return await get_member_profile_context(
        session=session,
        server_id=server_id,
        user_id=user_id,
        visibility="public_answer",
    )


async def _server_knowledge_tool(
    *,
    session: AsyncSession,
    server_id: int,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    return await search_server_knowledge(
        session=session,
        server_id=server_id,
        query=query,
        visibility="public_answer",
        limit=min(max(int(limit), 1), 8),
    )


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
            description=(
                "Fetch public-safe member context for user-facing answers, including profile basics, "
                "nickname history, activity summary, avatar hash, joined Discord date, public moderation "
                "actions taken against the member, and rule violation summaries. Does not return cases, "
                "notes, monitoring status, or internal moderation workspace data."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "server_id": {"type": "integer"},
                    "user_id": {"type": "integer"},
                },
                "required": ["server_id", "user_id"],
                "additionalProperties": False,
            },
            handler=_member_profile_tool,
            requires_admin_context=False,
        )
    )
    registry.register(
        AITool(
            name="search_server_knowledge",
            description=(
                "Search approved public server/admin knowledge chunks for answering server-specific questions. "
                "Use this before answering questions about server staff, server policies, events, channels, "
                "resources, imported files, or other admin-authored facts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "server_id": {"type": "integer"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["server_id", "query"],
                "additionalProperties": False,
            },
            handler=_server_knowledge_tool,
            requires_admin_context=False,
        )
    )
    return registry

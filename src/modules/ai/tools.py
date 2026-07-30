from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import Response
from sqlmodel.ext.asyncio.session import AsyncSession

from api.routers.activity import get_server_activity_leaderboard
from api.services.bot_command_catalog import list_bot_commands
from api.services.discord_guilds import fetch_guild_channels
from api.services.newcomer_probation import (
    can_use_public_member_commands,
    required_public_member_role_id,
)
from api.services.rbac_service import resolve_effective_permissions_for_member_context
from src.modules.ai.context import get_active_rules_context, get_member_profile_context
from src.modules.ai.knowledge import search_server_knowledge
from src.modules.ai.models import AIToolSpec
from src.modules.ai.youtube_channel_catalog import search_youtube_channel_catalog
from src.db.models import ServerSecuritySettings

AIToolHandler = Callable[..., Awaitable[dict[str, Any] | list[dict[str, Any]]]]


@dataclass(slots=True)
class AITool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: AIToolHandler
    requires_admin_context: bool = False
    requires_requester_context: bool = False


@dataclass(slots=True)
class AIToolRegistry:
    tools: dict[str, AITool] = field(default_factory=dict)

    def register(self, tool: AITool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> AITool | None:
        return self.tools.get(name)

    def specs(
        self,
        *,
        include_admin_tools: bool = False,
        enabled_names: set[str] | None = None,
    ) -> list[AIToolSpec]:
        return [
            AIToolSpec(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in self.tools.values()
            if (include_admin_tools or not tool.requires_admin_context)
            and (enabled_names is None or tool.name in enabled_names)
        ]

    def as_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "requires_admin_context": tool.requires_admin_context,
                "requires_requester_context": tool.requires_requester_context,
            }
            for tool in self.tools.values()
        ]


async def _active_rules_tool(*, session: AsyncSession, server_id: int) -> list[dict[str, Any]]:
    return await get_active_rules_context(session=session, server_id=server_id)


async def _available_commands_tool(
    *,
    session: AsyncSession,
    server_id: int,
    requester_user_id: int,
    requester_role_ids: list[int],
    requester_permission_names: list[str],
    requester_is_owner: bool,
    requester_is_administrator: bool,
    requester_locale: str | None,
    guidance_mode: str,
    query: str | None = None,
    category: str | None = None,
    details: bool = False,
) -> dict[str, Any]:
    role_ids = {int(role_id) for role_id in requester_role_ids}
    permission_names = {str(name) for name in requester_permission_names}
    privileged = requester_is_owner or requester_is_administrator or "administrator" in permission_names
    security_settings = await session.get(ServerSecuritySettings, server_id)
    required_member_role_id = required_public_member_role_id(security_settings)
    has_public_member_access = can_use_public_member_commands(
        security_settings,
        role_ids=role_ids,
        privileged=privileged,
    )

    effective_permission_keys: set[str] = set()
    if guidance_mode == "personalized":
        effective = await resolve_effective_permissions_for_member_context(
            session=session,
            server_id=server_id,
            user_id=requester_user_id,
            role_ids=role_ids,
            owner_fallback=requester_is_owner,
            admin_fallback=requester_is_administrator,
        )
        effective_permission_keys = set(effective.permission_keys)

    available = []
    for command in list_bot_commands(locale=requester_locale or "en"):
        if command.audience == "public_member":
            if not has_public_member_access:
                continue
        else:
            if guidance_mode != "personalized":
                continue
            required_rbac = set(command.required_rbac_permissions)
            required_native = set(command.required_permissions)
            if not required_rbac and not required_native:
                continue
            if required_rbac and not required_rbac.issubset(effective_permission_keys):
                continue
            if required_native and not privileged and not required_native.issubset(permission_names):
                continue
        available.append(command)

    total_available = len(available)
    normalized_category = (category or "").strip().lower()
    if normalized_category:
        available = [command for command in available if command.category.lower() == normalized_category]
    normalized_query = (query or "").strip().lower().lstrip("/")
    if normalized_query:
        available = [
            command
            for command in available
            if normalized_query
            in " ".join(
                (
                    command.id,
                    command.qualified_name,
                    command.invoke,
                    command.category,
                    command.summary,
                )
            ).lower()
        ]

    commands: list[dict[str, Any]] = []
    for command in available:
        item: dict[str, Any] = {
            "id": command.id,
            "invoke": command.invoke,
            "category": command.category,
            "summary": command.summary,
        }
        if details:
            item["parameters"] = [parameter.model_dump(mode="json") for parameter in command.parameters]
            item["workflow"] = list(command.workflow)
            item["notes"] = list(command.notes)
        commands.append(item)

    return {
        "guidance_mode": guidance_mode,
        "member_role_required": required_member_role_id is not None,
        "total_available": total_available,
        "returned_count": len(commands),
        "commands": commands,
    }


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
    source_id: str | None = None,
) -> list[dict[str, Any]]:
    normalized_source_id = str(UUID(source_id)) if source_id else None
    return await search_server_knowledge(
        session=session,
        server_id=server_id,
        query=query,
        visibility="public_answer",
        limit=min(max(int(limit), 1), 8),
        source_id=normalized_source_id,
    )


def _activity_date(value: str | None, field_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date in YYYY-MM-DD format") from exc


def _activity_ids(values: list[int] | None) -> list[str] | None:
    if not values:
        return None
    return [str(int(value)) for value in values]


async def _server_activity_tool(
    *,
    session: AsyncSession,
    server_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
    include_user_ids: list[int] | None = None,
    exclude_user_ids: list[int] | None = None,
    include_role_ids: list[int] | None = None,
    exclude_role_ids: list[int] | None = None,
    include_channel_ids: list[int] | None = None,
    exclude_channel_ids: list[int] | None = None,
    limit: int = 10,
    channels_limit: int = 5,
) -> dict[str, Any]:
    parsed_date_from = _activity_date(date_from, "date_from")
    parsed_date_to = _activity_date(date_to, "date_to")
    response = Response()
    rows = await get_server_activity_leaderboard(
        server_id=server_id,
        response=response,
        limit=min(max(int(limit), 1), 25),
        all_users=False,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        channels_limit=min(max(int(channels_limit), 1), 10),
        include_user_ids=_activity_ids(include_user_ids),
        exclude_user_ids=_activity_ids(exclude_user_ids),
        include_role_ids=_activity_ids(include_role_ids),
        exclude_role_ids=_activity_ids(exclude_role_ids),
        include_channel_ids=_activity_ids(include_channel_ids),
        exclude_channel_ids=_activity_ids(exclude_channel_ids),
        ignore_server_excludes=False,
        refresh_member_roles=False,
        refresh_channels=False,
        session=session,
    )

    channel_names: dict[str, str] = {}
    try:
        channel_names = {
            str(channel["id"]): str(channel.get("name") or channel["id"])
            for channel in await fetch_guild_channels(server_id)
            if channel.get("id") is not None
        }
    except Exception:
        channel_names = {}

    members = []
    for row in rows:
        members.append(
            {
                "user_id": row.user_id,
                "username": row.username,
                "server_nickname": row.server_nickname,
                "display_name": row.display_name,
                "message_count": row.message_count,
                "last_message_at": row.last_message_at.isoformat(),
                "channels": [
                    {
                        "channel_id": channel.channel_id,
                        "channel_name": channel_names.get(channel.channel_id),
                        "message_count": channel.message_count,
                    }
                    for channel in row.channels
                ],
            }
        )

    return {
        "date_from": parsed_date_from.isoformat() if parsed_date_from else None,
        "date_to": parsed_date_to.isoformat() if parsed_date_to else None,
        "server_channel_exclusions_applied": (
            response.headers.get("X-Activity-Server-Excludes-Applied") == "true"
        ),
        "returned_member_count": len(members),
        "members": members,
    }


async def _youtube_channel_catalog_tool(
    *,
    session: AsyncSession,
    server_id: int,
    channel_query: str | None = None,
    video_query: str | None = None,
    content_query: str | None = None,
    mode: str = "channel_info",
    limit: int = 10,
) -> dict[str, Any]:
    return await search_youtube_channel_catalog(
        session=session,
        server_id=server_id,
        channel_query=channel_query,
        video_query=video_query,
        content_query=content_query,
        mode=mode,
        limit=min(max(int(limit), 1), 20),
    )


def build_default_tool_registry() -> AIToolRegistry:
    registry = AIToolRegistry()
    registry.register(
        AITool(
            name="get_available_commands",
            description=(
                "List only the Discord bot commands the current requester is allowed to use. "
                "Use without query for a concise command list. For instructions about one command, "
                "pass its name in query and set details=true. The requester identity and permissions "
                "are supplied by the bot and cannot be selected by the model."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "server_id": {"type": "integer"},
                    "query": {
                        "type": "string",
                        "description": "Optional command name or topic, such as birthday, replies, or mod warn.",
                    },
                    "category": {"type": "string"},
                    "details": {"type": "boolean"},
                },
                "required": ["server_id"],
                "additionalProperties": False,
            },
            handler=_available_commands_tool,
            requires_requester_context=True,
        )
    )
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
                "nickname history, activity summary, avatar hash, Discord account creation time, server join time, "
                "public moderation actions taken against the member, and rule violation summaries. Does not return cases, "
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
            name="get_server_activity",
            description=(
                "Fetch public-safe Discord server message activity on demand using the same date, user, role, "
                "and channel include/exclude filters as the dashboard leaderboard. Returns member message counts, "
                "last-message timestamps, and per-channel counts without moderation warnings or private monitoring data. "
                "Exclusions win; user and role include filters are combined with OR; configured server channel exclusions "
                "apply unless explicit include_channel_ids are supplied."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "server_id": {"type": "integer"},
                    "date_from": {
                        "type": "string",
                        "description": "Optional inclusive UTC start date in YYYY-MM-DD format.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Optional inclusive UTC end date in YYYY-MM-DD format.",
                    },
                    "include_user_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "maxItems": 50,
                    },
                    "exclude_user_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "maxItems": 50,
                    },
                    "include_role_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "maxItems": 50,
                    },
                    "exclude_role_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "maxItems": 50,
                    },
                    "include_channel_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "maxItems": 50,
                    },
                    "exclude_channel_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "maxItems": 50,
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                    "channels_limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["server_id"],
                "additionalProperties": False,
            },
            handler=_server_activity_tool,
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
                    "source_id": {
                        "type": "string",
                        "description": (
                            "Optional knowledge source ID returned by another tool. Use it to search only one "
                            "linked transcript or document."
                        ),
                    },
                },
                "required": ["server_id", "query"],
                "additionalProperties": False,
            },
            handler=_server_knowledge_tool,
            requires_admin_context=False,
        )
    )
    registry.register(
        AITool(
            name="search_youtube_channel_catalog",
            description=(
                "Query followed YouTube channel knowledge for this Discord server. The tool resolves names, "
                "handles, abbreviations, aliases, and grammatical variants; returns public channel metadata or "
                "structured video dates; and can semantically search all linked indexed video transcripts. "
                "Every video and transcript match includes its actual channel name. If "
                "needs_channel_clarification is true, do not choose or combine channels; ask the user which returned "
                "channel they mean. "
                "Choose list_channels for channel names only, channel_info for a profile, latest_videos for recent "
                "uploads, search_videos for title/description matching, or search_transcripts for video contents."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "server_id": {"type": "integer"},
                    "channel_query": {"type": "string"},
                    "video_query": {"type": "string"},
                    "content_query": {
                        "type": "string",
                        "description": "Natural-language topic to search across linked indexed transcripts.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": [
                            "list_channels",
                            "channel_info",
                            "latest_videos",
                            "search_videos",
                            "search_transcripts",
                        ],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["server_id", "mode"],
                "additionalProperties": False,
            },
            handler=_youtube_channel_catalog_tool,
            requires_admin_context=False,
        )
    )
    return registry

import asyncio

import src.modules.ai.ai_main as ai_main_module
from src.modules.ai.ai_main import AIMain
from src.modules.ai.context import moderation_member_profile, public_member_profile
from src.modules.ai.models import AIImageInput, AIRequest, AIResponse, AIToolCall, AssistantInput, MessageModerationInput
from src.modules.ai.tools import AITool, AIToolRegistry, build_default_tool_registry
from src.modules.chat_bot.create_response import _expand_message_mentions


class FakeProvider:
    provider_name = "fake"

    def __init__(self, content: str):
        self.content = content
        self.last_request: AIRequest | None = None

    async def complete(self, request: AIRequest) -> AIResponse:
        self.last_request = request
        return AIResponse(
            content=self.content,
            model=request.model,
            provider=self.provider_name,
            total_tokens=12,
        )


class SequenceProvider:
    provider_name = "fake"

    def __init__(self, responses: list[AIResponse]):
        self.responses = responses
        self.requests: list[AIRequest] = []

    async def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        response.model = request.model
        response.provider = self.provider_name
        return response


async def fake_channel_fetcher(server_id: int, channel_id: int) -> dict:
    return {
        "id": str(channel_id),
        "name": "general",
        "type": 0,
        "position": 2,
        "parent_id": "555",
        "topic": "Main chat",
        "nsfw": False,
        "rate_limit_per_user": 3,
        "permission_overwrites": [{"id": "private-noise"}],
    }


def _full_profile() -> dict:
    return {
        "user_id": "456",
        "username": "target",
        "server_nickname": "target-nick",
        "display_name": "Target",
        "avatar_hash": "avatar",
        "joined_discord": "2026-01-01T00:00:00",
        "is_member": True,
        "flagged_absent_at": "2026-02-01T00:00:00",
        "activity": {"message_count": 25},
        "nickname_history": [{"nickname": "old"}],
        "moderation_actions_count": 2,
        "open_cases_count": 1,
        "recent_actions": [
            {
                "id": "action-1",
                "action_type": "warn",
                "reason": "Rule 1",
                "created_at": "2026-03-01T00:00:00",
                "moderator_user_id": "999",
                "moderator_username": "mod",
            }
        ],
        "recent_cases": [{"id": "case-1", "title": "Internal case"}],
        "monitored": True,
        "monitored_summary": {"reason": "internal note", "comment_count": 3},
        "top_rules_violated": [{"title": "No spam", "usage_count": 2}],
    }


def test_public_member_profile_filters_internal_moderation_data():
    public_profile = public_member_profile(_full_profile())

    assert public_profile["visibility"] == "public_answer"
    assert public_profile["avatar_hash"] == "avatar"
    assert public_profile["joined_discord"] == "2026-01-01T00:00:00"
    assert public_profile["activity"] == {"message_count": 25}
    assert public_profile["nickname_history"] == [{"nickname": "old"}]
    assert public_profile["moderation_actions_count"] == 2
    assert public_profile["recent_actions"] == [
        {
            "id": "action-1",
            "action_type": "warn",
            "reason": "Rule 1",
            "created_at": "2026-03-01T00:00:00",
        }
    ]
    assert public_profile["top_rules_violated"] == [{"title": "No spam", "usage_count": 2}]
    assert "recent_cases" not in public_profile
    assert "monitored" not in public_profile
    assert "monitored_summary" not in public_profile
    assert "moderator_user_id" not in public_profile["recent_actions"][0]


def test_moderation_member_profile_keeps_full_profile():
    full_profile = _full_profile()
    moderation_profile = moderation_member_profile(full_profile)

    assert moderation_profile["visibility"] == "moderation"
    assert moderation_profile["recent_cases"] == full_profile["recent_cases"]
    assert moderation_profile["monitored"] is True
    assert moderation_profile["monitored_summary"] == full_profile["monitored_summary"]
    assert moderation_profile["activity"] == full_profile["activity"]


def test_check_message_builds_moderation_request_and_parses_verdict():
    provider = FakeProvider(
        '{"flagged": true, "severity": "medium", "categories": ["spam"], '
        '"reason": "Repeated invite spam.", "suggested_action": "warn", "rule_ids": ["rule-1"]}'
    )
    ai = AIMain(provider=provider, model="test-model", channel_fetcher=fake_channel_fetcher)

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(
                content="join this server now",
                server_id=123,
                author_user_id=456,
                channel_id=789,
                message_id=101112,
                author_display_name="spammer",
                server_locale="ru",
                bot_user_id=999,
                mentioned_users=[
                    {
                        "user_id": "999",
                        "display_name": "CyberColors",
                        "username": "bot",
                        "is_bot": True,
                        "is_current_bot": True,
                    }
                ],
                current_bot_mentioned=True,
                answer_flow_invocation=True,
            ),
            include_member_profile=False,
        )
    )

    assert verdict.flagged is True
    assert verdict.severity == "medium"
    assert verdict.categories == ["spam"]
    assert verdict.suggested_action == "warn"
    assert verdict.rule_ids == ["rule-1"]
    assert provider.last_request is not None
    assert provider.last_request.task == "moderation"
    assert provider.last_request.model == "test-model"
    assert "Return JSON only" in provider.last_request.system_prompt
    prompt = provider.last_request.messages[0].content
    assert "join this server now" in prompt
    assert '"server_id": "123"' in prompt
    assert '"channel_id": "789"' in prompt
    assert '"server_locale": "ru"' in prompt
    assert '"current_bot_mentioned": true' in prompt
    assert '"answer_flow_invocation": true' in prompt
    assert '"name": "general"' in prompt
    assert '"topic": "Main chat"' in prompt
    assert "permission_overwrites" not in prompt


def test_check_message_invalid_json_falls_back_to_manual_review():
    provider = FakeProvider("not json")
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(ai.check_message("hello"))

    assert verdict.flagged is True
    assert verdict.severity == "low"
    assert verdict.categories == ["parse_error"]
    assert verdict.suggested_action == "manual_review"


def test_answer_uses_assistant_task_and_context_block():
    provider = FakeProvider("I do not have enough server data.")
    ai = AIMain(provider=provider, model="test-model")

    response = asyncio.run(ai.answer("Who are the admins?"))

    assert response.content == "I do not have enough server data."
    assert provider.last_request is not None
    assert provider.last_request.task == "assistant"
    assert "Who are the admins?" in provider.last_request.messages[-1].content
    assert "No database context was provided" in provider.last_request.messages[-1].content
    assert "Do not reveal internal moderation cases" in provider.last_request.system_prompt
    assert "activity traces" not in provider.last_request.system_prompt
    assert "nickname history" not in provider.last_request.system_prompt


def test_answer_includes_visual_inputs():
    provider = FakeProvider("That image looks like a badge.")
    ai = AIMain(provider=provider, model="test-model")
    image = AIImageInput(
        url="https://cdn.discordapp.com/emojis/123456789012345678.png",
        source="custom_emoji",
        label=":badge:",
        content_type="image/png",
    )

    response = asyncio.run(
        ai.answer(
            AssistantInput(
                content="What is this emoji?",
                images=[image],
            )
        )
    )

    assert response.content == "That image looks like a badge."
    assert provider.last_request is not None
    prompt_message = provider.last_request.messages[-1]
    assert prompt_message.images == [image]
    assert "Visual inputs:" in prompt_message.content
    assert "label=:badge:" in prompt_message.content


def test_check_message_includes_visual_inputs_and_metadata_count():
    provider = FakeProvider(
        '{"flagged": false, "severity": "none", "categories": [], '
        '"reason": "Visual is harmless.", "suggested_action": "none", "rule_ids": []}'
    )
    ai = AIMain(provider=provider, model="test-model")
    image = AIImageInput(
        url="https://cdn.discordapp.com/attachments/1/2/proof.png",
        source="attachment",
        label="proof.png",
        content_type="image/png",
        size=1024,
    )

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="look at this", images=[image]),
            include_member_profile=False,
        )
    )

    assert verdict.flagged is False
    assert provider.last_request is not None
    prompt_message = provider.last_request.messages[-1]
    assert prompt_message.images == [image]
    assert "Visual inputs:" in prompt_message.content
    assert '"visual_input_count": 1' in prompt_message.content


def test_answer_preloads_relevant_indexed_knowledge(monkeypatch):
    async def fake_search_server_knowledge(*, session, server_id, query, visibility, limit):
        assert session == "session"
        assert server_id == 123
        assert query == "What do you know about lightny?"
        assert visibility == "public_answer"
        assert limit == 5
        return [
            {
                "source_id": "source-1",
                "source_type": "text",
                "subject_type": "admin",
                "title": "Information about lightny",
                "text": "lightny is the server admin and creator of this bot.",
                "score": 0.91,
            }
        ]

    async def fake_subject_user_knowledge(*, session, server_id, user_ids, limit_per_user):
        assert session == "session"
        assert server_id == 123
        assert user_ids == [456]
        assert limit_per_user == 3
        return [
            {
                "source_id": "source-2",
                "source_type": "text",
                "subject_type": "admin",
                "subject_user_id": "456",
                "title": "About the asker",
                "text": "The asker helps maintain the community archive.",
                "chunk_id": "chunk-2",
            }
        ]

    monkeypatch.setattr(ai_main_module, "search_server_knowledge", fake_search_server_knowledge)
    monkeypatch.setattr(ai_main_module, "get_public_knowledge_for_subject_users", fake_subject_user_knowledge)
    provider = FakeProvider("lightny is the server admin and creator of this bot.")
    ai = AIMain(provider=provider, model="test-model")

    response = asyncio.run(
        ai.answer(
            AssistantInput(content="What do you know about lightny?", server_id=123, author_user_id=456),
            session="session",
        )
    )

    assert response.content == "lightny is the server admin and creator of this bot."
    assert provider.last_request is not None
    prompt = provider.last_request.messages[-1].content
    assert "Priority server memory facts" in prompt
    assert "lightny is the server admin" in prompt
    assert "The asker helps maintain the community archive." in prompt
    assert '"about": "the user asking"' in prompt
    assert "admin note" not in prompt.lower()
    assert "Other server context" in prompt


def test_clean_knowledge_fact_removes_indexing_title_prefix():
    assert (
        AIMain._clean_knowledge_fact(
            "Title: Информация о lightny Он администратор сервера и создатель этого бота.",
            title="Информация о lightny",
        )
        == "Он администратор сервера и создатель этого бота."
    )


def test_chat_response_expands_discord_mentions_for_ai_search_text():
    class FakeUser:
        id = 456
        display_name = "йопта"
        name = "lightny"

    class FakeBot:
        id = 999

    class FakeClient:
        user = FakeBot()

    class FakeMessage:
        mentions = [FakeBot(), FakeUser()]

    expanded = _expand_message_mentions(
        "что ты знаешь про <@456> ?",
        message=FakeMessage(),
        client=FakeClient(),
    )

    assert "@йопта / lightny (user_id: 456)" in expanded
    assert "<@456>" not in expanded


def test_default_tool_registry_exposes_initial_database_tools():
    registry = build_default_tool_registry()
    specs = {tool["name"]: tool for tool in registry.as_specs()}

    assert "get_active_rules" in specs
    assert "get_member_profile" in specs
    assert specs["get_member_profile"]["requires_admin_context"] is False
    assert "public-safe member context" in specs["get_member_profile"]["description"]


def test_moderation_strictness_is_sent_to_prompt_and_metadata():
    provider = FakeProvider(
        '{"flagged": false, "severity": "none", "categories": [], '
        '"reason": "No issue.", "suggested_action": "none", "rule_ids": []}'
    )
    ai = AIMain(provider=provider, model="test-model")

    asyncio.run(ai.check_message("borderline message", moderation_strictness="high"))

    assert provider.last_request is not None
    assert "Strictness: high" in provider.last_request.system_prompt
    assert provider.last_request.metadata["strictness"] == "high"


def test_answer_runs_user_facing_tool_call_loop():
    async def rules_handler(*, session, server_id):
        assert session == "session"
        assert server_id == 123
        return [{"id": "rule-1", "title": "No spam"}]

    registry = AIToolRegistry()
    registry.register(
        AITool(
            name="get_active_rules",
            description="Fetch active rules.",
            parameters={
                "type": "object",
                "properties": {"server_id": {"type": "integer"}},
                "required": ["server_id"],
                "additionalProperties": False,
            },
            handler=rules_handler,
        )
    )
    provider = SequenceProvider(
        [
            AIResponse(
                content=None,
                model="unused",
                provider="fake",
                total_tokens=5,
                tool_calls=[
                    AIToolCall(
                        id="call-1",
                        name="get_active_rules",
                        arguments={"server_id": 123},
                    )
                ],
                id="resp-1",
            ),
            AIResponse(content="Rule 1 is No spam.", model="unused", provider="fake", total_tokens=7, id="resp-2"),
        ]
    )
    ai = AIMain(provider=provider, model="test-model", tool_registry=registry)

    response = asyncio.run(
        ai.answer(
            AssistantInput(content="What are the rules?", server_id=123, author_user_id=456),
            session="session",
        )
    )

    assert response.content == "Rule 1 is No spam."
    assert response.total_tokens == 12
    assert len(provider.requests) == 2
    assert provider.requests[0].tools[0].name == "get_active_rules"
    assert provider.requests[0].max_tool_calls == 2
    assert provider.requests[1].previous_response_id == "resp-1"
    assert provider.requests[1].tool_results[0].call_id == "call-1"
    assert provider.requests[1].tool_results[0].output == {
        "ok": True,
        "tool": "get_active_rules",
        "data": [{"id": "rule-1", "title": "No spam"}],
    }


def test_answer_rejects_tool_call_outside_current_server_scope():
    async def rules_handler(*, session, server_id):
        raise AssertionError("handler should not be called for cross-server tool requests")

    registry = AIToolRegistry()
    registry.register(
        AITool(
            name="get_active_rules",
            description="Fetch active rules.",
            parameters={
                "type": "object",
                "properties": {"server_id": {"type": "integer"}},
                "required": ["server_id"],
            },
            handler=rules_handler,
        )
    )
    provider = SequenceProvider(
        [
            AIResponse(
                content=None,
                model="unused",
                provider="fake",
                tool_calls=[
                    AIToolCall(
                        id="call-1",
                        name="get_active_rules",
                        arguments={"server_id": 999},
                    )
                ],
                id="resp-1",
            ),
            AIResponse(content="I do not have enough server data.", model="unused", provider="fake", id="resp-2"),
        ]
    )
    ai = AIMain(provider=provider, model="test-model", tool_registry=registry)

    response = asyncio.run(
        ai.answer(
            AssistantInput(content="What are the rules?", server_id=123),
            session="session",
        )
    )

    assert response.content == "I do not have enough server data."
    assert provider.requests[1].tool_results[0].output == {
        "ok": False,
        "error": "Tool call rejected because server_id is outside the current server scope.",
    }

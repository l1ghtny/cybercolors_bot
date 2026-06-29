import asyncio

from src.modules.ai.ai_main import AIMain
from src.modules.ai.context import moderation_member_profile, public_member_profile
from src.modules.ai.models import AIRequest, AIResponse, MessageModerationInput
from src.modules.ai.tools import build_default_tool_registry


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


def test_default_tool_registry_exposes_initial_database_tools():
    registry = build_default_tool_registry()
    specs = {tool["name"]: tool for tool in registry.as_specs()}

    assert "get_active_rules" in specs
    assert "get_member_profile" in specs
    assert specs["get_member_profile"]["requires_admin_context"] is True


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

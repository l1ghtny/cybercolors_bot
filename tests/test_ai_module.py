import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import src.modules.ai.ai_main as ai_main_module
from src.modules.ai.ai_main import AIMain, moderation_system_prompt
from src.modules.ai.context import moderation_member_profile, public_member_profile
from src.modules.ai.models import (
    AIImageInput,
    AIMessage,
    AIRequest,
    AIResponse,
    AIToolCall,
    AssistantInput,
    MessageModerationInput,
)
from src.modules.ai.tools import AITool, AIToolRegistry, build_default_tool_registry
from src.modules.chat_bot.create_response import _expand_message_mentions


class FakeProvider:
    provider_name = "fake"

    def __init__(self, content: str):
        self.content = content
        self.last_request: AIRequest | None = None
        self.call_count = 0

    async def complete(self, request: AIRequest) -> AIResponse:
        self.call_count += 1
        self.last_request = request
        return AIResponse(
            content=self.content,
            model=request.model,
            provider=self.provider_name,
            total_tokens=12,
        )


def _moderation_json(**overrides) -> str:
    legacy_rule_ids = overrides.pop("rule_ids", [])
    categories = overrides.get("categories", [])
    rule_matches = overrides.pop("rule_matches", None)
    if rule_matches is None and categories:
        rule_matches = [
            {"rule_id": rule_id, "category": categories[0]}
            for rule_id in legacy_rule_ids
        ]
    payload = {
        "flagged": False,
        "severity": "none",
        "categories": [],
        "confidence": 1.0,
        "reason": "",
        "suggested_action": "none",
        "rule_matches": rule_matches or [],
        "targeted": False,
        "credible_threat": False,
        "credible_self_harm": False,
        "link_content_inspected": False,
        "is_banter_or_hyperbole": False,
        "requires_context": False,
        "repeated_behavior_evidence": False,
        "evidence_source": "none",
        "context_type": "none",
        "visual_sexual_level": "none",
    }
    payload.update(overrides)
    return json.dumps(payload)


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
        "joined_server_at": "2026-02-01T00:00:00",
        "is_member": True,
        "flagged_absent_at": "2026-02-01T00:00:00",
        "birthday": {"day": 7, "month": 11, "timezone": "Europe/Moscow"},
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
    assert public_profile["discord_account_created_at"] == "2026-01-01T00:00:00"
    assert public_profile["joined_server_at"] == "2026-02-01T00:00:00"
    assert "joined_discord" not in public_profile
    assert public_profile["birthday"] == {"day": 7, "month": 11, "timezone": "Europe/Moscow"}
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
    assert moderation_profile["birthday"] == full_profile["birthday"]
    assert moderation_profile["activity"] == full_profile["activity"]


def test_check_message_builds_moderation_request_and_parses_verdict():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["spam"],
            confidence=0.98,
            reason="Repeated invite spam.",
            suggested_action="warn",
            rule_ids=["rule-1"],
            repeated_behavior_evidence=True,
            evidence_source="text",
        )
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
                reply_to_message_id=202224,
                reply_to_author_user_id=555,
                reply_to_author_display_name="original poster",
                reply_to_content="just quoting this phrase",
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
    assert "Return one verdict matching the supplied JSON schema" in provider.last_request.system_prompt
    assert provider.last_request.response_format is not None
    assert provider.last_request.response_format.strict is True
    assert provider.last_request.response_format.schema["additionalProperties"] is False
    assert "rule_matches" in provider.last_request.response_format.schema["required"]
    assert "rule_ids" not in provider.last_request.response_format.schema["properties"]
    assert provider.last_request.max_output_tokens == ai_main_module.AI_MODERATION_MAX_OUTPUT_TOKENS
    prompt = provider.last_request.messages[0].content
    assert "join this server now" in prompt
    assert '"server_id": "123"' in prompt
    assert '"channel_id": "789"' in prompt
    assert '"server_locale": "ru"' in prompt
    assert '"current_bot_mentioned": true' in prompt
    assert '"answer_flow_invocation": true' in prompt
    assert '"reply_to": {' in prompt
    assert '"message_id": "202224"' in prompt
    assert "Replied-to message context:" in prompt
    assert "just quoting this phrase" in prompt
    assert '"name": "general"' in prompt
    assert '"topic": "Main chat"' in prompt
    assert "permission_overwrites" not in prompt


def test_check_message_converts_unsupported_watch_to_manual_review():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="low",
            categories=["other"],
            confidence=0.95,
            reason="Maybe watch for tone.",
            suggested_action="watch",
            evidence_source="text",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="АХАХАХАХ"),
            include_member_profile=False,
            moderation_strictness="low",
        )
    )

    assert verdict.flagged is True
    assert verdict.severity == "low"
    assert verdict.suggested_action == "manual_review"
    assert any("Watch requires structured evidence" in note for note in verdict.policy_notes)
    assert verdict.reason == "Maybe watch for tone."
    assert provider.last_request is not None
    assert "Do not suggest watch at low strictness" in provider.last_request.system_prompt
    assert "Do not flag ordinary casual profanity" in provider.last_request.system_prompt



def test_check_message_normalizes_unflagged_action_leak():
    provider = FakeProvider(
        '{"flagged": false, "severity": "none", "categories": [], '
        '"reason": "Looks fine but maybe watch.", "suggested_action": "watch", "rule_ids": []}'
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(ai.check_message("https://x.com/i/status/123", include_member_profile=False))

    assert verdict.flagged is False
    assert verdict.severity == "none"
    assert verdict.categories == []
    assert verdict.suggested_action == "none"
    assert verdict.rule_ids == []


def test_check_message_suppresses_trusted_staff_url_distribution_guess():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="high",
            categories=["spam"],
            confidence=0.92,
            reason="The staff resource link looks promotional.",
            suggested_action="warn",
            rule_ids=["rule-1"],
            evidence_source="text",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(
                content="The resource URL changed after the official update: https://example.com/video",
                author_is_admin=True,
                author_is_moderator=True,
                author_roles=[{"id": "1", "name": "Admin", "permissions": ["administrator"]}],
            ),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is False
    assert verdict.severity == "none"
    assert verdict.suggested_action == "none"
    assert any("Trusted staff resource links are not spam" in note for note in verdict.policy_notes)
    prompt = provider.last_request.messages[-1].content
    assert '"author_is_admin": true' in prompt
    assert '"author_is_moderator": true' in prompt
    assert "trusted staff context" in provider.last_request.system_prompt


def test_check_message_keeps_trusted_staff_explicit_link_violation():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="high",
            categories=["scam_or_phishing"],
            confidence=0.99,
            reason="The inspected link is a phishing page for credentials.",
            suggested_action="manual_review",
            rule_ids=["rule-1"],
            link_content_inspected=True,
            evidence_source="link",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(
                content="Use this login link: https://evil.example/login",
                author_is_admin=True,
                author_is_moderator=True,
            ),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is True
    assert verdict.severity == "high"
    assert verdict.suggested_action == "manual_review"


def test_check_message_suppresses_uninspected_link_only_guess():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["sexual_explicit"],
            confidence=0.88,
            reason="The link might contain explicit content, but it was not inspected.",
            suggested_action="manual_review",
            rule_ids=["rule-1"],
            evidence_source="link",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="||https://fxtwitter.com/i/status/123||"),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is False
    assert verdict.severity == "none"
    assert verdict.suggested_action == "none"
    assert any("uninspected link-only message" in note.lower() for note in verdict.policy_notes)


def test_check_message_low_strictness_suppresses_noncredible_profanity():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["harassment"],
            confidence=0.96,
            reason="Profanity could be rude.",
            suggested_action="warn",
            rule_ids=["rule-2"],
            is_banter_or_hyperbole=True,
            evidence_source="text",
            context_type="banter",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="fuck this"),
            include_member_profile=False,
            moderation_strictness="low",
        )
    )

    assert verdict.flagged is False
    assert verdict.severity == "none"
    assert verdict.suggested_action == "none"
    assert "Harassment requires a clear target." in verdict.policy_notes


def test_check_message_keeps_credible_low_strictness_threat_and_structured_fields():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="high",
            categories=["credible_threat"],
            confidence=0.99,
            reason="Concrete threat.",
            suggested_action="manual_review",
            rule_ids=["rule-2"],
            targeted=True,
            credible_threat=True,
            evidence_source="text",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="I will kill you", mentioned_users=[{"user_id": "123"}]),
            include_member_profile=False,
            moderation_strictness="low",
        )
    )

    assert verdict.flagged is True
    assert verdict.severity == "high"
    assert verdict.suggested_action == "manual_review"
    assert verdict.targeted is True
    assert verdict.credible_threat is True
    assert verdict.link_content_inspected is False
    assert verdict.is_banter_or_hyperbole is False
    assert verdict.requires_context is False

def test_check_message_uses_recent_context_to_suppress_game_threat_false_positive():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["credible_threat"],
            confidence=0.91,
            reason="Threat-like wording in a game discussion.",
            suggested_action="warn",
            rule_ids=["rule-2"],
            evidence_source="context",
            context_type="game",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(
                content="И застрелит вас",
                recent_channel_messages=[
                    {
                        "message_id": "1",
                        "author_user_id": "101",
                        "is_target_author": True,
                        "created_at": "2026-07-03T12:32:00",
                        "reply_to_message_id": None,
                        "content": "Мое предсказание Дельтарун",
                    },
                    {
                        "message_id": "2",
                        "author_user_id": "101",
                        "is_target_author": True,
                        "created_at": "2026-07-03T12:32:10",
                        "reply_to_message_id": None,
                        "content": "В конце игра вас убьет",
                    },
                    {
                        "message_id": "3",
                        "author_user_id": "101",
                        "is_target_author": True,
                        "created_at": "2026-07-03T12:32:20",
                        "reply_to_message_id": None,
                        "content": "Из консоли появится дуло пистолета",
                    },
                ],
                recent_author_messages=[
                    {"message_id": "2", "author_user_id": "101", "is_target_author": True, "content": "В конце игра вас убьет"},
                    {"message_id": "3", "author_user_id": "101", "is_target_author": True, "content": "Из консоли появится дуло пистолета"},
                ],
            ),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is False
    assert verdict.suggested_action == "none"
    assert "Threat moderation requires the model to affirm credible intent." in verdict.policy_notes
    prompt = provider.last_request.messages[0].content
    assert "Recent same-channel context" in prompt
    assert "Target message content" in prompt
    assert "И застрелит вас" in prompt


def test_check_message_suppresses_quoted_roleplay_attack_false_positive():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["harassment", "credible_threat"],
            confidence=0.91,
            reason="The quoted phrase sounds like a violent threat toward a character.",
            suggested_action="warn",
            rule_ids=["rule-2"],
            evidence_source="context",
            context_type="roleplay",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(
                content='"\u041e\u043d \u043e\u0431\u044f\u0437\u0430\u043d \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u043f\u0438\u0437\u0434\u044b" @Metal Sonic',
                mentioned_users=[{"user_id": "123", "display_name": "Metal Sonic", "username": "metal"}],
                recent_channel_messages=[
                    {
                        "message_id": "1",
                        "author_user_id": "101",
                        "is_target_author": False,
                        "content": "\u0427\u0442\u043e \u0431\u044b \u043e\u0442\u0432\u0435\u0442\u0438\u043b \u0432\u043e\u043e\u0431\u0440\u0430\u0436\u0430\u0435\u043c\u044b\u0439 \u043f\u0435\u0440\u0441\u043e\u043d\u0430\u0436?",
                    },
                    {
                        "message_id": "2",
                        "author_user_id": "102",
                        "is_target_author": False,
                        "content": "\u042d\u0442\u043e \u0442\u0435\u043e\u0440\u0435\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u043e\u0442\u0432\u0435\u0442 \u043f\u0435\u0440\u0441\u043e\u043d\u0430\u0436\u0430, \u043d\u0435 \u0443\u0433\u0440\u043e\u0437\u0430.",
                    },
                ],
                recent_author_messages=[],
            ),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is False
    assert verdict.suggested_action == "none"
    assert "Harassment requires a clear target." in verdict.policy_notes


def test_check_message_keeps_direct_member_threat_despite_roleplay_context():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["harassment", "credible_threat"],
            confidence=0.97,
            reason="The user directly threatens another member.",
            suggested_action="warn",
            rule_ids=["rule-2"],
            targeted=True,
            credible_threat=True,
            evidence_source="mixed",
            context_type="roleplay",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(
                content='@Metal Sonic \u0442\u044b \u043e\u0431\u044f\u0437\u0430\u043d \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u043f\u0438\u0437\u0434\u044b',
                mentioned_users=[{"user_id": "123", "display_name": "Metal Sonic", "username": "metal"}],
                recent_channel_messages=[
                    {"message_id": "1", "author_user_id": "101", "content": "\u042d\u0442\u043e \u0442\u0435\u043e\u0440\u0435\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u0440\u043e\u043b\u0435\u0432\u043e\u0439 \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442."},
                ],
            ),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is True
    assert verdict.suggested_action == "warn"

def test_moderation_prompt_keeps_standard_and_high_usable_for_normal_chat():
    standard_prompt = moderation_system_prompt("standard")
    high_prompt = moderation_system_prompt("high")

    assert "Return flagged=false for ordinary chat noise" in standard_prompt
    assert "vague insults without a target" in standard_prompt
    assert "not a single odd or rude message" in standard_prompt
    assert "Even at high strictness, return flagged=false for normal server chatter" in high_prompt
    assert "standalone profanity, laughter, caps, memes" in high_prompt


def test_check_message_invalid_json_falls_back_to_manual_review():
    provider = FakeProvider("not json")
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(ai.check_message("hello"))

    assert verdict.flagged is True
    assert verdict.severity == "low"
    assert verdict.categories == ["parse_error"]
    assert verdict.suggested_action == "manual_review"
    assert provider.call_count == ai_main_module.AI_MODERATION_MAX_ATTEMPTS
    assert verdict.raw_response is not None
    assert verdict.raw_response.total_tokens == 12 * ai_main_module.AI_MODERATION_MAX_ATTEMPTS
    assert f"Failed after {ai_main_module.AI_MODERATION_MAX_ATTEMPTS} attempts" in verdict.reason


def test_check_message_retries_incomplete_and_invalid_responses_before_success():
    provider = SequenceProvider(
        [
            AIResponse(
                content='{"flagged": false',
                model="unused",
                provider="fake",
                total_tokens=10,
                input_tokens=7,
                cached_input_tokens=5,
                output_tokens=3,
                reasoning_tokens=1,
                status="incomplete",
                incomplete_reason="max_output_tokens",
            ),
            AIResponse(
                content="not json",
                model="unused",
                provider="fake",
                total_tokens=12,
                input_tokens=8,
                cached_input_tokens=6,
                output_tokens=4,
                reasoning_tokens=2,
                status="completed",
            ),
            AIResponse(
                content=_moderation_json(reason="No violation."),
                model="unused",
                provider="fake",
                total_tokens=14,
                input_tokens=9,
                cached_input_tokens=7,
                output_tokens=5,
                reasoning_tokens=3,
                status="completed",
            ),
        ]
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(ai.check_message("hello"))

    assert verdict.flagged is False
    assert verdict.reason == "No violation."
    assert len(provider.requests) == 3
    assert verdict.raw_response is not None
    assert verdict.raw_response.total_tokens == 36
    assert verdict.raw_response.input_tokens == 24
    assert verdict.raw_response.cached_input_tokens == 18
    assert verdict.raw_response.output_tokens == 12
    assert verdict.raw_response.reasoning_tokens == 6


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
    assert "Do not invent bot commands or command access" in provider.last_request.system_prompt
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


def test_answer_attributes_replied_message_and_loads_original_author_profile(monkeypatch):
    provider = FakeProvider("That message was written by Original Poster.")
    ai = AIMain(provider=provider, model="test-model")

    async def fake_build_context_block(**_kwargs):
        return '{"member_profile": {"user_id": "456"}}'

    async def fake_get_member_profile_context(*, session, server_id, user_id, visibility):
        assert session == "session"
        assert server_id == 123
        assert user_id == 777
        assert visibility == "public_answer"
        return {
            "user_id": "777",
            "display_name": "Original Poster",
            "discord_account_created_at": "2020-01-01T00:00:00+00:00",
            "joined_server_at": "2024-06-15T00:00:00+00:00",
        }

    monkeypatch.setattr(ai, "_build_context_block", fake_build_context_block)
    monkeypatch.setattr(ai_main_module, "get_member_profile_context", fake_get_member_profile_context)

    response = asyncio.run(
        ai.answer(
            AssistantInput(
                content="Who wrote this?",
                server_id=123,
                author_user_id=456,
                reply_to_message_id=222,
                reply_to_author_user_id=777,
                reply_to_author_display_name="Original Poster",
                conversation=[
                    AIMessage(
                        role="user",
                        content="[Discord message author: Original Poster (user_id: 777)]\nHello",
                    )
                ],
            ),
            session="session",
            enable_tools=False,
        )
    )

    assert response.content == "That message was written by Original Poster."
    prompt = provider.last_request.messages[-1].content
    assert '"user_id": "777"' in prompt
    assert '"display_name": "Original Poster"' in prompt
    assert '"discord_account_created_at": "2020-01-01T00:00:00+00:00"' in prompt
    assert '"joined_server_at": "2024-06-15T00:00:00+00:00"' in prompt


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
            MessageModerationInput(
                content="look at this",
                images=[image],
                attachment_metadata=[
                    {
                        "filename": "proof.png",
                        "content_type": "image/png",
                        "size": 1024,
                        "url": "https://cdn.discordapp.com/attachments/1/2/proof.png",
                        "media_status": "available_inline",
                        "media_unavailable": False,
                    }
                ],
            ),
            include_member_profile=False,
        )
    )

    assert verdict.flagged is False
    assert provider.last_request is not None
    prompt_message = provider.last_request.messages[-1]
    assert prompt_message.images == [image]
    assert "Visual inputs:" in prompt_message.content
    assert '"visual_input_count": 1' in prompt_message.content
    assert "type=image/png" in prompt_message.content
    assert '"media_status": "available_inline"' in prompt_message.content
    assert "proof.png" not in prompt_message.content
    assert "https://cdn.discordapp.com/attachments/1/2/proof.png" not in prompt_message.content


def test_answer_prompt_uses_explicit_event_date_and_time_before_follow_up():
    provider = FakeProvider("The proposed time is Sunday at 16:00.")
    ai = AIMain(provider=provider, model="test-model")
    content = (
        'Сбор на тему "Ревью нынешнего состояния"\n\n'
        "Sunday, 19 July 2026 16:00\n\n"
        "👍 - удобно\n"
        "👎 - я хочу предложить другое время"
    )

    response = asyncio.run(ai.answer(AssistantInput(content=content)))

    assert response.content == "The proposed time is Sunday at 16:00."
    assert provider.last_request is not None
    assert content in provider.last_request.messages[-1].content
    assert "If a date or time is already present, use or confirm it" in provider.last_request.system_prompt


def test_check_message_includes_unavailable_media_metadata():
    provider = FakeProvider(
        '{"flagged": false, "severity": "none", "categories": [], '
        '"reason": "Text is harmless.", "suggested_action": "none", "rule_ids": []}'
    )
    ai = AIMain(provider=provider, model="test-model")
    attachment_metadata = [
        {
            "id": "7",
            "filename": "expired.png",
            "media_status": "download_failed",
            "media_unavailable": True,
        }
    ]

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(
                content="caption survives",
                attachment_metadata=attachment_metadata,
                media_unavailable=True,
            ),
            include_member_profile=False,
        )
    )

    assert verdict.flagged is False
    assert provider.last_request is not None
    prompt = provider.last_request.messages[-1].content
    assert '"media_unavailable": true' in prompt
    assert '"media_status": "download_failed"' in prompt
    assert "caption survives" in prompt


def test_check_message_low_strictness_suppresses_ambiguous_visual_nsfw():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["sexual_explicit"],
            confidence=0.96,
            reason="The image may resemble explicit content, but it is ambiguous.",
            suggested_action="manual_review",
            rule_ids=["rule-18"],
            evidence_source="visual",
            visual_sexual_level="uncertain",
        )
    )
    ai = AIMain(provider=provider, model="test-model")
    image = AIImageInput(
        url="https://cdn.discordapp.com/attachments/1/2/meme.png",
        source="attachment",
        label="meme.png",
        content_type="image/png",
        size=1024,
    )

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="sonic meme", images=[image]),
            include_member_profile=False,
            moderation_strictness="low",
        )
    )

    assert verdict.flagged is False
    assert verdict.severity == "none"
    assert verdict.suggested_action == "none"
    assert any("structured visual level to be explicit" in note for note in verdict.policy_notes)
    assert "visual_sexual_level" in provider.last_request.system_prompt


def test_check_message_standard_suppresses_ambiguous_visual_sexual_content():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["sexual_explicit"],
            confidence=0.91,
            reason="The stylized image may be sexualised, but the visual evidence is ambiguous.",
            suggested_action="manual_review",
            rule_ids=["rule-18"],
            evidence_source="visual",
            visual_sexual_level="suggestive",
        )
    )
    ai = AIMain(provider=provider, model="test-model")
    image = AIImageInput(
        url="https://cdn.discordapp.com/attachments/1/2/stylized.png",
        source="attachment",
        label="stylized.png",
        content_type="image/png",
        size=1024,
    )

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="look", images=[image]),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is False
    assert verdict.severity == "none"
    assert verdict.categories == []
    assert verdict.suggested_action == "none"
    assert any("structured visual level to be explicit" in note for note in verdict.policy_notes)


def test_check_message_standard_suppresses_low_confidence_visual_explicit_flag():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="high",
            categories=["sexual_explicit"],
            confidence=0.70,
            reason="The visual may be explicit.",
            suggested_action="manual_review",
            rule_ids=["rule-18"],
            evidence_source="visual",
            visual_sexual_level="explicit",
        )
    )
    ai = AIMain(provider=provider, model="test-model")
    image = AIImageInput(
        url="https://cdn.discordapp.com/attachments/1/2/uncertain.png",
        source="attachment",
        content_type="image/png",
    )

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="look", images=[image]),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is False
    assert verdict.categories == []
    assert any("below the standard threshold 0.75" in note for note in verdict.policy_notes)


def test_check_message_preserves_nonsexual_violation_when_visual_sexual_evidence_is_ambiguous():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["harassment", "sexual_explicit"],
            confidence=0.96,
            reason="The text directly harasses a member; the image may also be suggestive.",
            suggested_action="warn",
            rule_ids=["rule-harassment"],
            targeted=True,
            evidence_source="mixed",
            visual_sexual_level="suggestive",
        )
    )
    ai = AIMain(provider=provider, model="test-model")
    image = AIImageInput(
        url="https://cdn.discordapp.com/attachments/1/2/reaction.png",
        source="attachment",
        content_type="image/png",
    )

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(
                content="@member you are disgusting",
                mentioned_users=[{"user_id": "123"}],
                images=[image],
            ),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is True
    assert verdict.categories == ["harassment"]
    assert verdict.severity == "low"
    assert verdict.suggested_action == "manual_review"
    assert verdict.rule_ids == ["rule-harassment"]
    assert any("structured visual level to be explicit" in note for note in verdict.policy_notes)


def test_check_message_suppresses_other_escape_hatch_after_harassment_rejection():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="medium",
            categories=["harassment", "other"],
            confidence=0.78,
            reason="Profanity is rude, but there is no clear target.",
            suggested_action="warn",
            rule_matches=[
                {"rule_id": "rule-harassment", "category": "harassment"},
                {"rule_id": "rule-conflict", "category": "other"},
            ],
            targeted=False,
            evidence_source="visual",
        )
    )
    ai = AIMain(provider=provider, model="test-model")

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="", server_locale="ru"),
            include_member_profile=False,
            moderation_strictness="standard",
        )
    )

    assert verdict.flagged is False
    assert verdict.severity == "none"
    assert verdict.categories == []
    assert verdict.suggested_action == "none"
    assert verdict.rule_ids == []
    assert verdict.reason == "Profanity is rude, but there is no clear target."
    assert verdict.policy_notes == [
        "The other category is only valid when no canonical category applies.",
        "Harassment requires a clear target.",
    ]


def test_check_message_low_strictness_keeps_explicit_visual_nsfw():
    provider = FakeProvider(
        _moderation_json(
            flagged=True,
            severity="high",
            categories=["sexual_explicit"],
            confidence=0.99,
            reason="The image unmistakably contains explicit nudity.",
            suggested_action="manual_review",
            rule_ids=["rule-18"],
            evidence_source="visual",
            visual_sexual_level="explicit",
        )
    )
    ai = AIMain(provider=provider, model="test-model")
    image = AIImageInput(
        url="https://cdn.discordapp.com/attachments/1/2/nsfw.png",
        source="attachment",
        label="nsfw.png",
        content_type="image/png",
        size=1024,
    )

    verdict = asyncio.run(
        ai.check_message(
            MessageModerationInput(content="", images=[image]),
            include_member_profile=False,
            moderation_strictness="low",
        )
    )

    assert verdict.flagged is True
    assert verdict.severity == "high"
    assert verdict.suggested_action == "manual_review"
    assert verdict.visual_sexual_level == "explicit"


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
    assert "get_available_commands" in specs
    assert "get_member_profile" in specs
    assert "get_server_activity" in specs
    assert specs["get_member_profile"]["requires_admin_context"] is False
    assert specs["get_member_profile"]["requires_requester_context"] is True
    assert "requester-aware member context" in specs["get_member_profile"]["description"]
    assert specs["get_server_activity"]["requires_admin_context"] is False
    assert specs["get_server_activity"]["requires_requester_context"] is True
    assert specs["get_server_activity"]["parameters"]["properties"]["sort"]["enum"] == [
        "most_active",
        "least_active",
    ]
    assert specs["get_server_activity"]["parameters"]["properties"]["rank_user_id"]["type"] == "integer"
    assert specs["get_available_commands"]["requires_requester_context"] is True
    assert "aggregate member message counts" in specs["get_server_activity"]["description"]


def test_tool_registry_specs_can_be_filtered_per_server():
    registry = build_default_tool_registry()

    specs = registry.specs(enabled_names={"get_member_profile", "get_server_activity"})

    assert [tool.name for tool in specs] == ["get_member_profile", "get_server_activity"]


def test_member_profile_activity_is_self_or_activity_view_only(monkeypatch):
    import src.modules.ai.tools as tools_module

    async def fake_profile(**kwargs):
        return {
            "user_id": str(kwargs["user_id"]),
            "activity": {"message_count": 42, "last_message_at": "2026-07-28T20:00:00Z"},
        }

    async def no_staff_permissions(**_kwargs):
        return SimpleNamespace(permission_keys=[])

    monkeypatch.setattr(tools_module, "get_member_profile_context", fake_profile)
    monkeypatch.setattr(
        tools_module,
        "resolve_effective_permissions_for_member_context",
        no_staff_permissions,
    )

    async def run(user_id, *, administrator=False):
        return await tools_module._member_profile_tool(
            session="session",
            server_id=123,
            user_id=user_id,
            requester_user_id=456,
            requester_role_ids=[202],
            requester_permission_names=["administrator"] if administrator else [],
            requester_is_owner=False,
            requester_is_administrator=administrator,
            requester_locale="en",
            guidance_mode="personalized",
            requester_visible_channel_ids=[789],
        )

    self_profile = asyncio.run(run(456))
    other_profile = asyncio.run(run(777))
    staff_profile = asyncio.run(run(777, administrator=True))

    assert self_profile["activity"]["message_count"] == 42
    assert other_profile["activity"] is None
    assert other_profile["activity_visibility"] == "restricted_to_self_or_activity_view"
    assert staff_profile["activity"]["message_count"] == 42


def test_available_commands_tool_filters_public_newcomer_and_staff_access(monkeypatch):
    import src.modules.ai.tools as tools_module
    from src.db.models import ServerSecuritySettings

    settings = ServerSecuritySettings(
        server_id=123,
        newcomer_restriction_enabled=True,
        newcomer_role_id=101,
        newcomer_member_role_id=202,
    )

    class FakeSession:
        async def get(self, model, server_id):
            assert model is ServerSecuritySettings
            assert server_id == 123
            return settings

    async def fake_effective_permissions(*, role_ids, **_kwargs):
        permission_keys = []
        if 303 in role_ids:
            permission_keys = [
                "birthdays.settings.edit",
                "moderation.actions.apply.warn",
                "replies.manage",
                "replies.view",
            ]
        return SimpleNamespace(permission_keys=permission_keys)

    monkeypatch.setattr(
        tools_module,
        "resolve_effective_permissions_for_member_context",
        fake_effective_permissions,
    )

    async def run(role_ids, permission_names=None, *, guidance_mode="personalized", administrator=False):
        return await tools_module._available_commands_tool(
            session=FakeSession(),
            server_id=123,
            requester_user_id=456,
            requester_role_ids=role_ids,
            requester_permission_names=permission_names or [],
            requester_is_owner=False,
            requester_is_administrator=administrator,
            requester_locale="en",
            guidance_mode=guidance_mode,
        )

    member = asyncio.run(run([202]))
    assert {command["id"] for command in member["commands"]} == {
        "bday.add",
        "bday.change",
        "bday.list",
        "cat",
        "profile",
        "warns",
    }

    newcomer = asyncio.run(run([101]))
    assert newcomer["commands"] == []

    staff = asyncio.run(run([202, 303], ["manage_guild", "moderate_members"]))
    staff_ids = {command["id"] for command in staff["commands"]}
    assert {"bday.add", "birthdays_settings", "add_reply", "delete_reply", "show_replies", "mod.warn"}.issubset(
        staff_ids
    )
    assert "force_validation" not in staff_ids

    public_only_admin = asyncio.run(run([], guidance_mode="public_only", administrator=True))
    assert {command["id"] for command in public_only_admin["commands"]} == {
        "bday.add",
        "bday.change",
        "bday.list",
        "cat",
        "profile",
        "warns",
    }


def test_available_commands_tool_returns_details_only_when_requested(monkeypatch):
    import src.modules.ai.tools as tools_module
    from src.db.models import ServerSecuritySettings

    class FakeSession:
        async def get(self, model, server_id):
            assert model is ServerSecuritySettings
            return ServerSecuritySettings(server_id=server_id)

    async def fake_effective_permissions(**_kwargs):
        return SimpleNamespace(permission_keys=["replies.manage"])

    monkeypatch.setattr(
        tools_module,
        "resolve_effective_permissions_for_member_context",
        fake_effective_permissions,
    )

    result = asyncio.run(
        tools_module._available_commands_tool(
            session=FakeSession(),
            server_id=123,
            requester_user_id=456,
            requester_role_ids=[],
            requester_permission_names=["manage_guild"],
            requester_is_owner=False,
            requester_is_administrator=False,
            requester_locale="en",
            guidance_mode="personalized",
            query="add_reply",
            details=True,
        )
    )

    assert [command["id"] for command in result["commands"]] == ["add_reply"]
    assert result["commands"][0]["parameters"]
    assert result["commands"][0]["workflow"]


def test_server_activity_tool_reuses_dashboard_filters_and_omits_moderation_data(monkeypatch):
    import src.modules.ai.tools as tools_module

    captured = {}

    class FakeSession:
        async def get(self, _model, _server_id):
            return None

    async def fake_leaderboard(**kwargs):
        captured.update(kwargs)
        kwargs["response"].headers["X-Activity-Server-Excludes-Applied"] = "true"
        return [
            SimpleNamespace(
                user_id="777",
                username="original",
                server_nickname="OP",
                display_name="Original Poster",
                message_count=42,
                last_message_at=datetime(2026, 7, 28, 20, 0, tzinfo=timezone.utc),
                channels=[SimpleNamespace(channel_id="789", message_count=30)],
                warn_count=3,
                warnings=[SimpleNamespace(reason="must stay private to this tool")],
            )
        ]

    async def fake_fetch_channels(server_id):
        assert server_id == 123
        return [{"id": "789", "name": "general"}]

    async def fake_effective_permissions(**_kwargs):
        return SimpleNamespace(permission_keys=["activity.view"])

    monkeypatch.setattr(tools_module, "get_server_activity_leaderboard", fake_leaderboard)
    monkeypatch.setattr(tools_module, "fetch_guild_channels", fake_fetch_channels)
    monkeypatch.setattr(
        tools_module,
        "resolve_effective_permissions_for_member_context",
        fake_effective_permissions,
    )

    result = asyncio.run(
        tools_module._server_activity_tool(
            session=FakeSession(),
            server_id=123,
            requester_user_id=456,
            requester_role_ids=[303],
            requester_permission_names=[],
            requester_is_owner=False,
            requester_is_administrator=False,
            requester_locale="en",
            guidance_mode="personalized",
            requester_visible_channel_ids=[789],
            date_from="2026-07-01",
            date_to="2026-07-28",
            include_user_ids=[777],
            exclude_role_ids=[888],
            include_channel_ids=[789],
            sort="least_active",
            limit=5,
            channels_limit=3,
        )
    )

    assert isinstance(captured["session"], FakeSession)
    assert captured["date_from"].isoformat() == "2026-07-01"
    assert captured["date_to"].isoformat() == "2026-07-28"
    assert captured["include_user_ids"] == ["777"]
    assert captured["exclude_role_ids"] == ["888"]
    assert captured["include_channel_ids"] == ["789"]
    assert captured["sort"] == "least_active"
    assert captured["ignore_server_excludes"] is False
    assert result["sort"] == "least_active"
    assert result["server_channel_exclusions_applied"] is True
    assert result["members"] == [
        {
            "user_id": "777",
            "username": "original",
            "server_nickname": "OP",
            "display_name": "Original Poster",
            "message_count": 42,
            "last_message_at": "2026-07-28T20:00:00+00:00",
            "channels": [
                {
                    "channel_id": "789",
                    "channel_name": "general",
                    "message_count": 30,
                }
            ],
        }
    ]
    assert "warnings" not in result["members"][0]
    assert "warn_count" not in result["members"][0]


def test_server_activity_tool_rejects_targeted_other_member_for_public_requester(monkeypatch):
    import src.modules.ai.tools as tools_module

    async def fake_effective_permissions(**_kwargs):
        return SimpleNamespace(permission_keys=[])

    async def fail_leaderboard(**_kwargs):
        raise AssertionError("private targeted lookup must be rejected before querying activity")

    monkeypatch.setattr(
        tools_module,
        "resolve_effective_permissions_for_member_context",
        fake_effective_permissions,
    )
    monkeypatch.setattr(tools_module, "get_server_activity_leaderboard", fail_leaderboard)

    result = asyncio.run(
        tools_module._server_activity_tool(
            session="session",
            server_id=123,
            requester_user_id=456,
            requester_role_ids=[202],
            requester_permission_names=[],
            requester_is_owner=False,
            requester_is_administrator=False,
            requester_locale="en",
            guidance_mode="personalized",
            requester_visible_channel_ids=[789],
            include_user_ids=[777],
        )
    )

    assert result["privacy_restricted"] is True
    assert result["activity_detail_access"] == "aggregate_leaderboards_or_self_only"
    assert result["members"] == []


def test_server_activity_tool_uses_backend_rank_without_single_member_filter(monkeypatch):
    import src.modules.ai.tools as tools_module

    captured = {}

    async def fake_leaderboard(**kwargs):
        captured.update(kwargs)
        return [
            SimpleNamespace(
                user_id="456",
                username="member",
                server_nickname=None,
                display_name="Member",
                message_count=68,
                rank=16,
                ranking_member_count=53,
                last_message_at=datetime(2026, 8, 16, 16, 40, tzinfo=timezone.utc),
                channels=[],
            )
        ]

    monkeypatch.setattr(tools_module, "get_server_activity_leaderboard", fake_leaderboard)

    result = asyncio.run(
        tools_module._server_activity_tool(
            session="session",
            server_id=123,
            requester_user_id=456,
            requester_role_ids=[],
            requester_permission_names=[],
            requester_is_owner=False,
            requester_is_administrator=False,
            requester_locale="en",
            guidance_mode="personalized",
            requester_visible_channel_ids=[789],
            date_from="2026-08-10",
            date_to="2026-08-16",
            include_user_ids=[456],
            rank_user_id=456,
        )
    )

    assert captured["rank_user_id"] == 456
    assert captured["include_user_ids"] is None
    assert captured["include_channel_ids"] is None
    assert result["rank_user_id"] == "456"
    assert result["requester_channel_scope_applied"] is False
    assert result["members"] == [
        {
            "user_id": "456",
            "username": "member",
            "server_nickname": None,
            "display_name": "Member",
            "message_count": 68,
            "rank": 16,
            "ranking_member_count": 53,
        }
    ]


def test_server_activity_public_leaderboard_omits_member_detail(monkeypatch):
    import src.modules.ai.tools as tools_module

    captured = {}

    async def fake_effective_permissions(**_kwargs):
        return SimpleNamespace(permission_keys=[])

    async def fake_leaderboard(**kwargs):
        captured.update(kwargs)
        return [
            SimpleNamespace(
                user_id="777",
                username="member",
                server_nickname=None,
                display_name="Member",
                message_count=42,
                last_message_at=datetime(2026, 7, 28, 20, 0, tzinfo=timezone.utc),
                channels=[SimpleNamespace(channel_id="789", message_count=30)],
            )
        ]

    monkeypatch.setattr(
        tools_module,
        "resolve_effective_permissions_for_member_context",
        fake_effective_permissions,
    )
    monkeypatch.setattr(tools_module, "get_server_activity_leaderboard", fake_leaderboard)
    monkeypatch.setattr(tools_module, "fetch_guild_channels", lambda _server_id: None)

    result = asyncio.run(
        tools_module._server_activity_tool(
            session="session",
            server_id=123,
            requester_user_id=456,
            requester_role_ids=[202],
            requester_permission_names=[],
            requester_is_owner=False,
            requester_is_administrator=False,
            requester_locale="en",
            guidance_mode="personalized",
            requester_visible_channel_ids=[789],
        )
    )

    assert captured["include_channel_ids"] is None
    assert result["activity_detail_access"] == "aggregate_only"
    assert result["members"] == [
        {
            "user_id": "777",
            "username": "member",
            "server_nickname": None,
            "display_name": "Member",
            "message_count": 42,
        }
    ]


def test_server_activity_tool_rejects_invisible_channel_scope(monkeypatch):
    import src.modules.ai.tools as tools_module

    class FakeSession:
        async def get(self, _model, _server_id):
            return None

    async def fail_leaderboard(**_kwargs):
        raise AssertionError("invisible channels must be rejected before querying activity")

    monkeypatch.setattr(tools_module, "get_server_activity_leaderboard", fail_leaderboard)

    result = asyncio.run(
        tools_module._server_activity_tool(
            session=FakeSession(),
            server_id=123,
            requester_user_id=456,
            requester_role_ids=[],
            requester_permission_names=["administrator"],
            requester_is_owner=False,
            requester_is_administrator=True,
            requester_locale="en",
            guidance_mode="personalized",
            requester_visible_channel_ids=[789],
            include_user_ids=[777],
            include_channel_ids=[999],
        )
    )

    assert result["privacy_restricted"] is True
    assert result["requester_channel_scope_applied"] is True
    assert result["members"] == []


def test_server_activity_tool_honors_configured_channel_exclusions(monkeypatch):
    import src.modules.ai.tools as tools_module
    from src.db.models import ServerModerationSettings

    class FakeSession:
        async def get(self, model, server_id):
            assert model is ServerModerationSettings
            return ServerModerationSettings(server_id=server_id, activity_excluded_channel_ids=["789"])

    async def fail_leaderboard(**_kwargs):
        raise AssertionError("configured activity exclusions must be applied before querying")

    monkeypatch.setattr(tools_module, "get_server_activity_leaderboard", fail_leaderboard)

    result = asyncio.run(
        tools_module._server_activity_tool(
            session=FakeSession(),
            server_id=123,
            requester_user_id=456,
            requester_role_ids=[],
            requester_permission_names=[],
            requester_is_owner=False,
            requester_is_administrator=False,
            requester_locale="en",
            guidance_mode="personalized",
            requester_visible_channel_ids=[789],
            include_user_ids=[456],
        )
    )

    assert result["server_channel_exclusions_applied"] is True
    assert result["members"] == []


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


def test_answer_runs_user_facing_tool_call_loop(monkeypatch):
    monkeypatch.delenv("AI_REPLY_WEB_SEARCH_ENABLED", raising=False)
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
    assert provider.requests[0].enable_web_search is True
    assert provider.requests[0].reasoning_effort == "low"
    assert provider.requests[0].max_tool_calls == 2
    assert provider.requests[1].previous_response_id == "resp-1"
    assert provider.requests[1].enable_web_search is True
    assert provider.requests[1].reasoning_effort == "low"
    assert provider.requests[1].tool_results[0].call_id == "call-1"
    assert provider.requests[1].tool_results[0].output == {
        "ok": True,
        "tool": "get_active_rules",
        "data": [{"id": "rule-1", "title": "No spam"}],
    }


def test_answer_can_disable_web_search_with_env(monkeypatch):
    monkeypatch.setenv("AI_REPLY_WEB_SEARCH_ENABLED", "false")
    provider = FakeProvider("No search.")
    ai = AIMain(provider=provider, model="test-model")

    response = asyncio.run(ai.answer(AssistantInput(content="hello")))

    assert response.content == "No search."
    assert provider.last_request is not None
    assert provider.last_request.enable_web_search is False
    assert provider.last_request.reasoning_effort == "low"


def test_answer_applies_per_server_tool_allowlist(monkeypatch):
    monkeypatch.delenv("AI_REPLY_WEB_SEARCH_ENABLED", raising=False)
    provider = FakeProvider("Only public profile lookup is available.")
    ai = AIMain(provider=provider, model="test-model")

    response = asyncio.run(
        ai.answer(
            AssistantInput(content="hello", server_id=123),
            session="session",
            enabled_tool_names={"get_member_profile"},
        )
    )

    assert response.content == "Only public profile lookup is available."
    assert provider.last_request is not None
    assert [tool.name for tool in provider.last_request.tools] == ["get_member_profile"]
    assert provider.last_request.enable_web_search is False
    assert provider.last_request.reasoning_effort == "low"
    assert "Use get_server_activity" not in provider.last_request.system_prompt
    assert "followed YouTube channel" not in provider.last_request.system_prompt


def test_answer_rejects_tool_call_disabled_for_server():
    async def rules_handler(*, session, server_id):
        raise AssertionError("disabled tool handler must not run")

    registry = AIToolRegistry()
    registry.register(
        AITool(
            name="get_active_rules",
            description="Fetch active rules.",
            parameters={"type": "object", "properties": {"server_id": {"type": "integer"}}},
            handler=rules_handler,
        )
    )
    ai = AIMain(provider=FakeProvider("unused"), model="test-model", tool_registry=registry)

    result = asyncio.run(
        ai._execute_assistant_tool_call(
            AIToolCall(id="call-1", name="get_active_rules", arguments={"server_id": 123}),
            session="session",
            server_id=123,
            enabled_tool_names=set(),
        )
    )

    assert result.output == {
        "ok": False,
        "error": "Tool is disabled for this server: get_active_rules",
    }


def test_requester_aware_tools_require_trusted_requester_context():
    ai = AIMain(provider=FakeProvider("unused"), model="test-model")

    for tool_name, arguments in (
        ("get_available_commands", {"server_id": 123}),
        ("get_member_profile", {"server_id": 123, "user_id": 777}),
        ("get_server_activity", {"server_id": 123}),
    ):
        result = asyncio.run(
            ai._execute_assistant_tool_call(
                AIToolCall(id="call-1", name=tool_name, arguments=arguments),
                session="session",
                server_id=123,
                enabled_tool_names={tool_name},
            )
        )

        assert result.output == {
            "ok": False,
            "error": "Tool call rejected because requester context is unavailable.",
        }


def test_requester_channel_visibility_cannot_be_supplied_by_model():
    captured = {}

    async def handler(*, session, server_id, **kwargs):
        captured.update(kwargs)
        return {"server_id": server_id, "session": session}

    registry = AIToolRegistry()
    registry.register(
        AITool(
            name="requester_aware",
            description="Test trusted requester context.",
            parameters={"type": "object", "properties": {"server_id": {"type": "integer"}}},
            handler=handler,
            requires_requester_context=True,
        )
    )
    ai = AIMain(provider=FakeProvider("unused"), model="test-model", tool_registry=registry)

    result = asyncio.run(
        ai._execute_assistant_tool_call(
            AIToolCall(
                id="call-1",
                name="requester_aware",
                arguments={
                    "server_id": 123,
                    "requester_user_id": 999,
                    "requester_visible_channel_ids": [999],
                },
            ),
            session="session",
            server_id=123,
            enabled_tool_names={"requester_aware"},
            assistant_input=AssistantInput(
                content="hello",
                server_id=123,
                author_user_id=456,
                author_visible_channel_ids=[789],
            ),
        )
    )

    assert result.output["ok"] is True
    assert captured["requester_user_id"] == 456
    assert captured["requester_visible_channel_ids"] == [789]


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

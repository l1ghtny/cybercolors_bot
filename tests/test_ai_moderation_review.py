import asyncio
from types import SimpleNamespace

from src.db.models import ServerAISettings
from src.modules.ai.models import AIResponse, ModerationVerdict
from src.modules.ai.moderation_review import build_ai_moderation_embed, create_ai_moderation_decision


class FakeSession:
    def __init__(self):
        self.added = None

    def add(self, item):
        self.added = item

    async def flush(self):
        return None

    async def refresh(self, item):
        return None


def _fake_message():
    return SimpleNamespace(
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=456),
        id=789,
        author=SimpleNamespace(id=101, display_name="target"),
        content="bad message",
        attachments=[],
        jump_url="https://discord.com/channels/123/456/789",
    )


def test_create_ai_moderation_decision_maps_verdict_fields():
    session = FakeSession()
    verdict = ModerationVerdict(
        flagged=True,
        severity="high",
        categories=["spam"],
        reason="Spam burst",
        suggested_action="warn",
        rule_ids=["rule-1"],
        raw_response=AIResponse(content="{}", model="test-model", provider="fake", total_tokens=10),
    )
    settings = ServerAISettings(server_id=123, moderation_strictness="high")

    decision = asyncio.run(
        create_ai_moderation_decision(
            session=session,
            message=_fake_message(),
            verdict=verdict,
            settings=settings,
            attachments=[{"filename": "proof.png"}],
        )
    )

    assert session.added is decision
    assert decision.status == "pending_review"
    assert decision.strictness == "high"
    assert decision.provider == "fake"
    assert decision.model == "test-model"
    assert decision.categories == ["spam"]
    assert decision.rule_ids == ["rule-1"]
    assert decision.attachments_json == [{"filename": "proof.png"}]


def test_ai_moderation_embed_contains_review_summary():
    verdict = ModerationVerdict(
        flagged=True,
        severity="medium",
        categories=["harassment"],
        reason="Likely insult",
        suggested_action="manual_review",
        rule_ids=["rule-1"],
    )
    settings = ServerAISettings(server_id=123, moderation_strictness="standard")
    session = FakeSession()
    decision = asyncio.run(
        create_ai_moderation_decision(
            session=session,
            message=_fake_message(),
            verdict=verdict,
            settings=settings,
            attachments=[],
        )
    )

    embed = build_ai_moderation_embed(decision, _fake_message())

    assert embed.title == "AI moderation review"
    assert "Likely insult" in embed.description
    assert any(field.name == "Suggested action" and "manual_review" in field.value for field in embed.fields)
    assert any(field.name == "Possible rules" and "rule-1" in field.value for field in embed.fields)

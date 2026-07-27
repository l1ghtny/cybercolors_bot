import asyncio

import src.modules.ai.context as ai_context
from src.db.models import ModerationRule


def test_ai_moderation_context_excludes_disabled_rules_and_keeps_guidance(monkeypatch):
    rules = [
        ModerationRule(
            server_id=123,
            code="1",
            title="Included",
            ai_moderation_enabled=True,
            ai_guidance="Apply only to repeated unsolicited messages.",
        ),
        ModerationRule(
            server_id=123,
            code="2",
            title="Manual only",
            ai_moderation_enabled=False,
        ),
    ]

    async def fake_list_rules(*, session, server_id, include_inactive):
        assert server_id == 123
        assert include_inactive is False
        return rules

    monkeypatch.setattr(ai_context, "list_rules", fake_list_rules)
    payload = asyncio.run(
        ai_context.get_active_rules_context(
            session=object(),
            server_id=123,
            ai_moderation_only=True,
        )
    )

    assert [item["title"] for item in payload] == ["Included"]
    assert payload[0]["ai_guidance"] == "Apply only to repeated unsolicited messages."


def test_answer_context_keeps_rules_disabled_only_for_moderation(monkeypatch):
    rules = [
        ModerationRule(
            server_id=123,
            title="Manual moderation rule",
            ai_moderation_enabled=False,
        )
    ]

    async def fake_list_rules(*, session, server_id, include_inactive):
        return rules

    monkeypatch.setattr(ai_context, "list_rules", fake_list_rules)
    payload = asyncio.run(ai_context.get_active_rules_context(session=object(), server_id=123))
    assert [item["title"] for item in payload] == ["Manual moderation rule"]

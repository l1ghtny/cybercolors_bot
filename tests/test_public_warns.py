import asyncio
from dataclasses import fields
from datetime import datetime, timezone
from types import SimpleNamespace

from src.commands.warns import WARN_EMBED_COLOR, build_public_warns_embed
from src.modules.moderation.public_warnings import (
    PublicWarning,
    _public_reason,
    _public_rule_labels,
    list_active_public_warnings,
)


def _member(user_id: int, name: str):
    return SimpleNamespace(
        id=user_id,
        name=name,
        display_name=name,
        mention=f"<@{user_id}>",
        display_avatar=SimpleNamespace(url=f"https://cdn.example/{user_id}.png"),
    )


def test_public_warning_contract_cannot_expose_internal_moderation_details():
    assert {field.name for field in fields(PublicWarning)} == {"created_at", "rule_labels", "reason"}


def test_public_warning_projection_uses_citation_snapshots_and_member_facing_reason():
    action = SimpleNamespace(
        rule=None,
        rule_citations=[
            SimpleNamespace(
                id="citation-1",
                cited_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                rule=None,
                rule_code_snapshot="1",
                rule_title_snapshot="Be respectful",
            )
        ],
        reason="Member-facing reason",
        commentary="Private moderator note",
    )

    rule_labels = _public_rule_labels(action, "en")
    assert rule_labels == ("Rule 1️⃣: Be respectful",)
    assert _public_reason(action, rule_labels) == "Member-facing reason"


def test_public_warning_projection_omits_reason_that_duplicates_localized_rule():
    action = SimpleNamespace(
        reason="1 Be respectful",
        commentary=None,
    )

    assert _public_reason(action, ("Правило 1️⃣: Be respectful",)) is None


def test_public_warns_embed_matches_member_card_style_without_private_fields():
    warning = PublicWarning(
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        rule_labels=("Rule 1️⃣: Be respectful",),
        reason="Repeated harassment after a prior reminder",
    )

    embed = build_public_warns_embed(
        target=_member(456, "Target"),
        requester=_member(789, "Requester"),
        warnings=[warning],
        total=1,
        locale="en",
    )

    payload = embed.to_dict()
    serialized = str(payload)
    assert embed.title == "Warning list"
    assert embed.description == "Active warnings for <@456>"
    assert embed.color == WARN_EMBED_COLOR
    assert embed.thumbnail.url == "https://cdn.example/456.png"
    assert "Rule 1️⃣: Be respectful" in embed.fields[0].value
    assert "Repeated harassment after a prior reminder" in embed.fields[0].value
    assert "<t:" in embed.fields[0].value
    assert embed.footer.text == "Requested by Requester"
    assert "commentary" not in serialized.lower()
    assert "moderator" not in serialized.lower()
    assert "dashboard" not in serialized.lower()


def test_public_warns_embed_hides_rule_section_for_legacy_warning():
    warning = PublicWarning(
        created_at=datetime(2023, 2, 19, tzinfo=timezone.utc),
        rule_labels=(),
        reason="Imported rule 3 reference",
    )

    embed = build_public_warns_embed(
        target=_member(456, "Цель"),
        requester=_member(789, "Автор"),
        warnings=[warning],
        total=1,
        locale="ru",
    )

    value = embed.fields[0].value
    assert "**Причина:**\nImported rule 3 reference" in value
    assert "**Правило:**" not in value
    assert "Правило недоступно" not in value


def test_public_warns_embed_localizes_empty_state():
    embed = build_public_warns_embed(
        target=_member(456, "Цель"),
        requester=_member(789, "Автор"),
        warnings=[],
        total=0,
        locale="ru",
    )

    assert embed.title == "Список предупреждений"
    assert embed.description == "Активные предупреждения участника <@456>"
    assert embed.fields[0].name == "Предупреждения"
    assert embed.fields[0].value == "У участника нет активных предупреждений."
    assert embed.footer.text == "Запросил: Автор"


class _Result:
    def __init__(self, *, one=None, all_items=None):
        self._one = one
        self._all_items = all_items or []

    def one(self):
        return self._one

    def all(self):
        return self._all_items


class _Session:
    def __init__(self, action):
        self.action = action
        self.statements = []

    async def exec(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _Result(one=1)
        return _Result(all_items=[self.action])


def test_public_warning_query_returns_only_public_projection():
    action = SimpleNamespace(
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        rule=None,
        rule_citations=[],
        reason="Imported rule 7\nCommentary: Hidden note",
        commentary="Hidden note",
    )
    session = _Session(action)

    warnings, total = asyncio.run(
        list_active_public_warnings(
            session,
            server_id=123,
            user_id=456,
            locale="en",
            limit=10,
        )
    )

    assert total == 1
    assert warnings == [
        PublicWarning(
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            rule_labels=(),
            reason="Imported rule 7",
        )
    ]
    assert len(session.statements) == 2
    query_text = str(session.statements[1]).lower()
    assert "moderation_actions.server_id" in query_text
    assert "moderation_actions.target_user_id" in query_text
    assert "moderation_actions.action_type" in query_text
    assert "moderation_actions.is_active" in query_text

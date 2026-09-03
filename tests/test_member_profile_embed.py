from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.commands.moderation.profile import (
    MODRAL_EMBED_COLOR,
    MemberProfileView,
    _dashboard_profile_url,
    build_member_profile_embed,
)


def _profile(**overrides):
    values = {
        "username": "member_name",
        "display_name": "Member Display",
        "avatar_hash": None,
        "joined_server_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
        "joined_discord": datetime(2020, 3, 4, tzinfo=timezone.utc),
        "is_member": True,
        "monitored": True,
        "moderation_actions_count": 7,
        "member_notes_count": 4,
        "open_cases_count": 2,
        "top_rules_violated": [SimpleNamespace(title="Be respectful", usage_count=3)],
        "recent_actions": [
            SimpleNamespace(
                id="action-id",
                action_type="warn",
                action_number=42,
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        ],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _member(**overrides):
    values = {
        "id": 456,
        "name": "member_name",
        "display_avatar": SimpleNamespace(url="https://cdn.example/member.png"),
        "communication_disabled_until": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_member_profile_embed_uses_avatar_dates_and_dashboard_links(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://dash.example/")

    embed = build_member_profile_embed(
        _profile(),
        member=_member(),
        server_id=123,
        locale="en",
    )

    assert embed.title == "Member profile — Member Display"
    assert embed.url == "https://dash.example/dashboard/123/users?id=456"
    assert embed.color == MODRAL_EMBED_COLOR
    assert embed.thumbnail.url == "https://cdn.example/member.png"
    assert "`456`" in embed.description
    assert "🔇 Timed out" in embed.description
    assert "👁 Monitored" in embed.description
    assert embed.fields[0].name == "Joined server"
    assert "<t:" in embed.fields[0].value
    assert "**7** actions · **4** notes · **2** open cases" in embed.fields[2].value
    assert "Be respectful × **3**" in embed.fields[3].value
    assert "[`warn` #42]" in embed.fields[4].value
    assert "https://dash.example/dashboard/123/moderation/actions/action-id" in embed.fields[4].value
    assert embed.footer.text == "Modral · Member profile"


def test_member_profile_embed_has_natural_russian_labels():
    embed = build_member_profile_embed(
        _profile(monitored=False, recent_actions=[], top_rules_violated=[]),
        member=_member(communication_disabled_until=None),
        server_id=123,
        locale="ru",
    )

    assert embed.title == "Профиль участника — Member Display"
    assert "**Статус:** 🟢 На сервере" in embed.description
    assert embed.fields[0].name == "Присоединился к серверу"
    assert embed.fields[2].name == "Модерация"
    assert embed.fields[2].value == "**Действий: 7** · **Заметок: 4** · **Открытых дел: 2**"
    assert embed.footer.text == "Modral · Профиль участника"


def test_member_profile_dashboard_button_targets_full_profile(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://dash.example/")

    view = MemberProfileView(server_id=123, user_id=456, locale="ru")
    button = view.children[0]

    assert _dashboard_profile_url(123, 456) == "https://dash.example/dashboard/123/users?id=456"
    assert button.label == "Открыть в дашборде"
    assert button.url == "https://dash.example/dashboard/123/users?id=456"

from datetime import datetime, timezone
from types import SimpleNamespace

from src.commands.profile import PROFILE_EMBED_COLOR, build_public_profile_embed


def _member(**overrides):
    values = {
        "id": 456,
        "name": "member_name",
        "display_name": "Member Display",
        "display_avatar": SimpleNamespace(url="https://cdn.example/member.png"),
        "status": "dnd",
        "joined_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
        "created_at": datetime(2020, 3, 4, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_public_profile_embed_matches_juniper_style_without_moderation_details():
    embed = build_public_profile_embed(member=_member(), locale="en")

    payload = str(embed.to_dict())
    assert embed.title == "Member profile — Member Display"
    assert embed.color == PROFILE_EMBED_COLOR
    assert embed.thumbnail.url == "https://cdn.example/member.png"
    assert "**User ID:** `456`" in embed.description
    assert "**Username:** @member_name" in embed.description
    assert "**Status:** ⛔ Do Not Disturb" in embed.description
    assert embed.fields[0].name == "Joined server"
    assert embed.fields[1].name == "Discord account created"
    assert "<t:" in embed.fields[0].value
    assert embed.footer.text == "Modral · Member profile"
    assert "moderation" not in payload.lower()
    assert "monitored" not in payload.lower()
    assert "dashboard" not in payload.lower()


def test_public_profile_embed_has_natural_russian_labels():
    embed = build_public_profile_embed(member=_member(status="idle"), locale="ru")

    assert embed.title == "Профиль участника — Member Display"
    assert "**Статус:** 🌙 Неактивен" in embed.description
    assert embed.fields[0].name == "Присоединился к серверу"
    assert embed.fields[1].name == "Зарегистрировался в Discord"
    assert embed.footer.text == "Modral · Профиль участника"


def test_public_profile_missing_join_date_uses_placeholder():
    embed = build_public_profile_embed(member=_member(joined_at=None), locale="en")

    assert embed.fields[0].value == "—"

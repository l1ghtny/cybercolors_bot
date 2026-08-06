from datetime import datetime, timezone
from types import SimpleNamespace

import discord

from src.commands.profile import PROFILE_EMBED_COLOR, build_public_profile_embed


def _role(role_id: int, name: str):
    return SimpleNamespace(id=role_id, name=name)


def _member(**overrides):
    values = {
        "id": 456,
        "name": "member_name",
        "display_name": "Member Display",
        "display_avatar": SimpleNamespace(url="https://cdn.example/member.png"),
        "status": "dnd",
        "guild": SimpleNamespace(id=123, owner_id=456),
        "roles": [_role(123, "@everyone"), _role(10, "Regular"), _role(20, "Champion")],
        "color": discord.Color.from_rgb(155, 89, 182),
        "premium_since": datetime(2025, 5, 6, tzinfo=timezone.utc),
        "bot": False,
        "activities": [
            SimpleNamespace(type=discord.ActivityType.playing, name="Chess", title=None)
        ],
        "joined_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
        "created_at": datetime(2020, 3, 4, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_public_profile_embed_matches_juniper_style_without_moderation_details():
    requester = SimpleNamespace(
        display_name="Requester",
        display_avatar=SimpleNamespace(url="https://cdn.example/requester.png"),
    )
    embed = build_public_profile_embed(member=_member(), requester=requester, locale="en")

    payload = str(embed.to_dict())
    assert embed.title == "Member profile — Member Display"
    assert embed.color.value == 0x9B59B6
    assert embed.thumbnail.url == "https://cdn.example/member.png"
    assert "**User ID:** `456`" in embed.description
    assert "**Username:** @member_name" in embed.description
    assert "**Status:** ⛔ Do Not Disturb" in embed.description
    assert "**Top role:** Champion" in embed.description
    assert "**Server roles:** 2" in embed.description
    assert "👑 Server owner · 🚀 Server booster" in embed.description
    assert "**Activity:** 🎮 Playing Chess" in embed.description
    assert embed.fields[0].name == "Joined server"
    assert embed.fields[1].name == "Discord account created"
    assert "<t:" in embed.fields[0].value
    assert embed.footer.text == "Modral · Requested by Requester"
    assert embed.footer.icon_url == "https://cdn.example/requester.png"
    assert "moderation" not in payload.lower()
    assert "monitored" not in payload.lower()
    assert "dashboard" not in payload.lower()


def test_public_profile_embed_has_natural_russian_labels():
    listening = SimpleNamespace(
        type=discord.ActivityType.listening,
        name="Spotify",
        title="Кино",
    )
    embed = build_public_profile_embed(
        member=_member(
            status="idle",
            guild=SimpleNamespace(id=123, owner_id=999),
            bot=True,
            activities=[listening],
        ),
        locale="ru",
    )

    assert embed.title == "Профиль участника — Member Display"
    assert "**Статус:** 🌙 Неактивен" in embed.description
    assert "**Высшая роль:** Champion" in embed.description
    assert "**Ролей на сервере:** 2" in embed.description
    assert "🚀 Бустер сервера · 🤖 Бот" in embed.description
    assert "**Активность:** 🎧 Слушает Кино" in embed.description
    assert embed.fields[0].name == "Присоединился к серверу"
    assert embed.fields[1].name == "Зарегистрировался в Discord"
    assert embed.footer.text == "Modral · Профиль участника"


def test_public_profile_missing_join_date_uses_placeholder():
    embed = build_public_profile_embed(
        member=_member(
            joined_at=None,
            guild=SimpleNamespace(id=123, owner_id=999),
            roles=[_role(123, "@everyone")],
            color=discord.Color.default(),
            premium_since=None,
            activities=[],
        ),
        locale="en",
    )

    assert embed.fields[0].value == "—"
    assert embed.color == PROFILE_EMBED_COLOR
    assert "**Top role:** —" in embed.description
    assert "**Server roles:** 0" in embed.description
    assert "**Badges:**" not in embed.description
    assert "**Activity:**" not in embed.description

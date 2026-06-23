import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlmodel import select

from api.models.moderation_actions import ModerationActionCreate
from api.models.moderation_rules import ModerationRuleReadModel
from api.services.moderation_actions_service import create_action
from api.services.moderation_rules_service import create_manual_rule
from src.db.database import engine, get_async_session
from src.db.models import (
    ActionType,
    GlobalUser,
    ModerationAction,
    ModerationActionRuleCitation,
    Server,
    ServerModerationSettings,
    User,
)
from src.modules.moderation.bot_services import (
    build_action_payload,
    create_bot_moderation_action,
    fetch_active_rule_models,
    find_rule,
    rule_choices,
    rule_label,
)


def _make_discord_id() -> int:
    return 8_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


def _rule_model(*, rule_id: str, code: str | None, title: str) -> ModerationRuleReadModel:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return ModerationRuleReadModel(
        id=rule_id,
        server_id="123",
        code=code,
        title=title,
        description=None,
        sort_order=1,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_rule_helpers_build_labels_and_autocomplete_choices():
    first = _rule_model(rule_id=str(uuid4()), code="1", title="No insults")
    second = _rule_model(rule_id=str(uuid4()), code=None, title="No spam")

    assert rule_label(first) == "1 No insults"
    assert rule_label(second) == "No spam"
    assert find_rule([first, second], first.id) is first
    assert find_rule([first, second], str(uuid4())) is None

    choices = rule_choices([first, second], "spam")
    assert len(choices) == 1
    assert choices[0].name == "No spam"
    assert choices[0].value == second.id


def test_build_action_payload_uses_rule_id_without_bot_api_url(monkeypatch):
    monkeypatch.delenv("BOT_API_URL", raising=False)
    rule_id = uuid4()
    joined_at = datetime.now(timezone.utc)
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=111),
        guild=SimpleNamespace(id=222, name="guild"),
    )
    target = SimpleNamespace(id=333, name="target", nick="target-nick", joined_at=joined_at)

    payload = build_action_payload(
        interaction=interaction,
        user=target,
        action_type=ActionType.WARN,
        rule_id=rule_id,
        commentary="note",
        reason=None,
    )

    assert payload.action_type == ActionType.WARN
    assert payload.rule_id == rule_id
    assert payload.rule_ids == []
    assert payload.moderator_user_id == 111
    assert payload.target_user_joined_at.tzinfo is None


async def _create_bot_action_scenario(sent_messages: list[dict]) -> None:
    async def fake_create_direct_message(user_id: int, content: str) -> dict:
        sent_messages.append({"user_id": user_id, "content": content})
        return {}

    import api.services.moderation_actions_service as action_service

    action_service.create_direct_message = fake_create_direct_message

    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="bot-helper-server", bot_active=True))
        session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
        session.add(GlobalUser(discord_id=target_id, username="target"))
        session.add(User(user_id=moderator_id, server_id=server_id, server_nickname="mod", is_member=True))
        session.add(User(user_id=target_id, server_id=server_id, server_nickname="target-nick", is_member=True))
        await session.flush()
        rule = await create_manual_rule(
            session=session,
            server_id=server_id,
            title="No insults",
            description="Insults are not allowed",
            code="1",
            sort_order=1,
            created_by_user_id=moderator_id,
        )
        rule_id = rule.id
        await session.commit()

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=moderator_id),
        guild=SimpleNamespace(id=server_id, name="bot-helper-server"),
    )
    target = SimpleNamespace(
        id=target_id,
        name="target",
        nick="target-nick",
        joined_at=datetime.now(timezone.utc),
    )

    async with get_async_session() as session:
        rules = await fetch_active_rule_models(session=session, server_id=server_id)
        selected = find_rule(rules, str(rule_id))
        assert selected is not None

        action = await create_bot_moderation_action(
            session=session,
            interaction=interaction,
            user=target,
            action_type=ActionType.WARN,
            rule_id=selected.id,
            commentary="moderator note",
            reason=None,
        )
        await session.commit()

        assert action.action_type == ActionType.WARN
        assert action.rule_id == rule_id
        citation = (
            await session.exec(
                select(ModerationActionRuleCitation).where(
                    ModerationActionRuleCitation.action_id == action.id,
                    ModerationActionRuleCitation.rule_id == rule_id,
                    ModerationActionRuleCitation.server_id == server_id,
                )
            )
        ).one()
        assert citation.rule_code_snapshot == "1"
        assert citation.rule_title_snapshot == "No insults"

    assert sent_messages
    assert sent_messages[0]["user_id"] == target_id
    assert "No insults" in sent_messages[0]["content"]
    assert "moderator note" in sent_messages[0]["content"]

    await engine.dispose()


def test_create_bot_moderation_action_records_rule_citation_and_warn_dm():
    sent_messages: list[dict] = []
    asyncio.run(_create_bot_action_scenario(sent_messages))


async def _mute_effect_scenario(added_roles: list[dict]) -> None:
    async def fake_add_guild_member_role(server_id: int, user_id: int, role_id: int) -> None:
        added_roles.append({"server_id": server_id, "user_id": user_id, "role_id": role_id})

    import api.services.moderation_actions_service as action_service

    action_service.add_guild_member_role = fake_add_guild_member_role

    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()
    mute_role_id = _make_discord_id()

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="mute-effect-server", bot_active=True))
        session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
        session.add(GlobalUser(discord_id=target_id, username="target"))
        session.add(User(user_id=moderator_id, server_id=server_id, server_nickname="mod", is_member=True))
        session.add(User(user_id=target_id, server_id=server_id, server_nickname="target-nick", is_member=True))
        session.add(ServerModerationSettings(server_id=server_id, mute_role_id=mute_role_id))
        prior_action = ModerationAction(
            action_type=ActionType.MUTE,
            moderator_user_id=moderator_id,
            reason="previous mute",
            target_user_id=target_id,
            server_id=server_id,
            is_active=True,
        )
        session.add(prior_action)
        await session.flush()
        prior_action_id = prior_action.id

        payload = ModerationActionCreate(
            action_type=ActionType.MUTE,
            moderator_user_id=moderator_id,
            reason="new mute",
            target_user_id=target_id,
            target_user_name="target",
            target_user_joined_at=datetime.now(timezone.utc).replace(tzinfo=None),
            target_user_server_nickname="target-nick",
            server_id=server_id,
            server_name="mute-effect-server",
        )
        created = await create_action(
            session=session,
            action=payload,
            moderator_user_id=moderator_id,
            apply_discord_effects=True,
        )
        await session.commit()

    async with get_async_session() as session:
        previous = await session.get(ModerationAction, prior_action_id)
        current = await session.get(ModerationAction, created.id)
        assert previous.is_active is False
        assert current.is_active is True

    assert added_roles == [{"server_id": server_id, "user_id": target_id, "role_id": mute_role_id}]
    await engine.dispose()


def test_create_action_mute_effect_assigns_role_and_deactivates_previous_mutes():
    added_roles: list[dict] = []
    asyncio.run(_mute_effect_scenario(added_roles))

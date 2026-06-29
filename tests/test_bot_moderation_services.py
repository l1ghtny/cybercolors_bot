import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlmodel import select

from api.models.moderation_actions import ModerationActionCreate
from api.models.moderation_rules import ModerationRuleReadModel
from api.services.moderation_actions_service import _build_action_log_embed, _build_action_log_message, create_action
from api.services.moderation_rules_service import create_manual_rule
from src.db.database import engine, get_async_session
from src.modules.localization.service import tr
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


def test_build_action_log_message_links_dashboard_and_uses_rule_label(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://dash.example/")
    action_id = uuid4()
    case_id = uuid4()
    rule_id = uuid4()
    action = SimpleNamespace(
        id=action_id,
        action_type=ActionType.WARN,
        server_id=123,
        target_user_id=456,
        moderator_user_id=789,
        reason="rule breach\nCommentary: context note",
        commentary="context note",
        rule=SimpleNamespace(id=rule_id, code="1", title="No insults"),
        rule_citations=[
            SimpleNamespace(
                id=uuid4(),
                rule_id=rule_id,
                rule=SimpleNamespace(id=rule_id, code="1", title="No insults"),
                rule_code_snapshot="1",
                rule_title_snapshot="No insults",
                cited_at=datetime(2026, 1, 1),
            )
        ],
        case_id=case_id,
        case=SimpleNamespace(title="Case Alpha"),
        expires_at=None,
    )

    message = _build_action_log_message(
        action=action,
        moderator_username="moderator",
        target_username="target",
    )

    assert f"https://dash.example/dashboard/123/moderation/actions/{action_id}" in message
    assert f"https://dash.example/dashboard/123/moderation/cases/{case_id}" in message
    assert "**Reason:** rule breach" in message
    assert message.count("**Commentary:** context note") == 1
    assert "Commentary: context note" not in message.replace("**Commentary:** context note", "")
    assert "**Rule:** `1 No insults`" in message
    assert "Rule ID" not in message
    assert str(rule_id) not in message
    assert "**Case:** [Case Alpha]" in message
    assert "**Action ID:** [" in message

    localized_message = _build_action_log_message(
        action=action,
        moderator_username="moderator",
        target_username="target",
        locale="ru",
    )
    assert f"**{tr('ru', 'modlog.action_label')}:**" in localized_message
    assert f"**{tr('ru', 'modlog.commentary_label')}:**" in localized_message
    assert f"**{tr('ru', 'modlog.action_id_label')}:**" in localized_message

    embed = _build_action_log_embed(
        action=action,
        moderator_username="moderator",
        target_username="target",
    )
    assert embed["title"] == "Moderation log: warn"
    assert embed["url"] == f"https://dash.example/dashboard/123/moderation/actions/{action_id}"
    assert embed["color"] == 0xF2C94C
    field_names = [field["name"] for field in embed["fields"]]
    assert field_names == ["Target", "Moderator", "Rule", "Reason", "Commentary", "Case"]
    assert embed["fields"][3]["value"] == "rule breach"
    assert embed["fields"][4]["value"] == "context note"
    assert "Commentary: context note" not in embed["fields"][3]["value"]
    assert embed["footer"]["text"] == f"Action ID: {action_id}"

    localized_embed = _build_action_log_embed(
        action=action,
        moderator_username="moderator",
        target_username="target",
        locale="ru",
    )
    assert localized_embed["title"].startswith(f"{tr('ru', 'modlog.title')}: ")
    assert localized_embed["fields"][4]["name"] == tr("ru", "modlog.commentary_label")

    duplicate_reason_action = SimpleNamespace(**{**action.__dict__, "reason": "1 No insults"})
    duplicate_message = _build_action_log_message(
        action=duplicate_reason_action,
        moderator_username="moderator",
        target_username="target",
    )
    assert "**Reason:**" not in duplicate_message
    assert "**Rule:** `1 No insults`" in duplicate_message
    assert "**Commentary:** context note" in duplicate_message

    duplicate_embed = _build_action_log_embed(
        action=duplicate_reason_action,
        moderator_username="moderator",
        target_username="target",
    )
    assert [field["name"] for field in duplicate_embed["fields"]] == ["Target", "Moderator", "Rule", "Commentary", "Case"]


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
        assert action.reason == "1 No insults"
        assert action.commentary == "moderator note"
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


async def _discord_effect_runs_after_action_flush_scenario(effect_observations: list[dict]) -> None:
    import api.services.moderation_actions_service as action_service

    original_apply_effects = action_service._apply_discord_action_effects

    async def fake_apply_effects(
        *,
        session,
        action,
        resolved_reason,
        resolved_rules,
        resolved_commentary,
        mute_role_id=None,
    ) -> None:
        persisted_action = (
            await session.exec(
                select(ModerationAction).where(
                    ModerationAction.server_id == action.server_id,
                    ModerationAction.target_user_id == action.target_user_id,
                    ModerationAction.moderator_user_id == action.moderator_user_id,
                    ModerationAction.reason == resolved_reason,
                )
            )
        ).one()
        effect_observations.append(
            {
                "action_id": persisted_action.id,
                "mute_role_id": mute_role_id,
                "is_active": persisted_action.is_active,
            }
        )

    action_service._apply_discord_action_effects = fake_apply_effects

    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()
    mute_role_id = _make_discord_id()

    try:
        async with get_async_session() as session:
            session.add(Server(server_id=server_id, server_name="effect-order-server", bot_active=True))
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
                reason="ordered mute",
                target_user_id=target_id,
                target_user_name="target",
                target_user_joined_at=datetime.now(timezone.utc).replace(tzinfo=None),
                target_user_server_nickname="target-nick",
                server_id=server_id,
                server_name="effect-order-server",
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
    finally:
        action_service._apply_discord_action_effects = original_apply_effects
        await engine.dispose()


def test_discord_effect_runs_after_action_is_flushed():
    effect_observations: list[dict] = []
    asyncio.run(_discord_effect_runs_after_action_flush_scenario(effect_observations))

    assert len(effect_observations) == 1
    assert effect_observations[0]["action_id"] is not None
    assert effect_observations[0]["is_active"] is True
    assert effect_observations[0]["mute_role_id"] is not None

async def _new_case_action_scenario(sent_messages: list[dict]) -> None:
    async def fake_create_direct_message(user_id: int, content: str) -> dict:
        sent_messages.append({"user_id": user_id, "content": content})
        return {}

    import api.services.moderation_actions_service as action_service

    action_service.create_direct_message = fake_create_direct_message

    from src.db.models import CaseStatus, ModerationCase
    from src.modules.moderation.bot_services import CASE_NEW_VALUE, resolve_case_id_for_action

    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="case-action-server", bot_active=True))
        session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
        session.add(GlobalUser(discord_id=target_id, username="target"))
        session.add(User(user_id=moderator_id, server_id=server_id, server_nickname="mod", is_member=True))
        session.add(User(user_id=target_id, server_id=server_id, server_nickname="target-nick", is_member=True))
        await session.flush()
        rule = await create_manual_rule(
            session=session,
            server_id=server_id,
            title="No spam",
            description="Repeated spam is not allowed",
            code="2",
            sort_order=2,
            created_by_user_id=moderator_id,
        )
        rule_id = rule.id
        await session.commit()

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=moderator_id, name="moderator"),
        guild=SimpleNamespace(id=server_id, name="case-action-server", icon=None),
    )
    target = SimpleNamespace(
        id=target_id,
        name="target",
        display_name="Target User",
        nick="target-nick",
        joined_at=datetime.now(timezone.utc),
    )

    async with get_async_session() as session:
        rules = await fetch_active_rule_models(session=session, server_id=server_id)
        selected = find_rule(rules, str(rule_id))
        assert selected is not None
        selected_rule_label = rule_label(selected)

        case_id = await resolve_case_id_for_action(
            session=session,
            interaction=interaction,
            user=target,
            action_type=ActionType.WARN,
            selected_case=CASE_NEW_VALUE,
            selected_rule=selected,
            selected_rule_label=selected_rule_label,
            commentary="case note",
        )
        action = await create_bot_moderation_action(
            session=session,
            interaction=interaction,
            user=target,
            action_type=ActionType.WARN,
            rule_id=selected.id,
            commentary="case note",
            reason=None,
            case_id=case_id,
        )
        await session.commit()

    async with get_async_session() as session:
        moderation_case = await session.get(ModerationCase, case_id)
        created_action = await session.get(ModerationAction, action.id)
        assert moderation_case is not None
        assert moderation_case.status == CaseStatus.OPEN
        assert moderation_case.target_user_id == target_id
        assert moderation_case.opened_by_user_id == moderator_id
        assert moderation_case.title.startswith("Warn - Target User: 2 No spam")
        assert created_action.case_id == case_id

    assert sent_messages
    assert sent_messages[0]["user_id"] == target_id
    await engine.dispose()


def test_new_case_selection_creates_case_and_links_action():
    sent_messages: list[dict] = []
    asyncio.run(_new_case_action_scenario(sent_messages))


async def _ban_effect_scenario(banned_users: list[dict]) -> None:
    async def fake_ban_guild_member(server_id: int, user_id: int, delete_message_seconds: int = 0) -> None:
        banned_users.append(
            {
                "server_id": server_id,
                "user_id": user_id,
                "delete_message_seconds": delete_message_seconds,
            }
        )

    import api.services.moderation_actions_service as action_service

    original_ban = action_service.ban_guild_member
    action_service.ban_guild_member = fake_ban_guild_member

    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()

    try:
        async with get_async_session() as session:
            session.add(Server(server_id=server_id, server_name="ban-effect-server", bot_active=True))
            session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
            session.add(GlobalUser(discord_id=target_id, username="target"))
            session.add(User(user_id=moderator_id, server_id=server_id, server_nickname="mod", is_member=True))
            session.add(User(user_id=target_id, server_id=server_id, server_nickname="target-nick", is_member=True))
            payload = ModerationActionCreate(
                action_type=ActionType.BAN,
                moderator_user_id=moderator_id,
                reason="temporary ban",
                target_user_id=target_id,
                target_user_name="target",
                target_user_joined_at=datetime.now(timezone.utc).replace(tzinfo=None),
                target_user_server_nickname="target-nick",
                server_id=server_id,
                server_name="ban-effect-server",
            )
            created = await create_action(
                session=session,
                action=payload,
                moderator_user_id=moderator_id,
                apply_discord_effects=True,
            )
            await session.commit()

        async with get_async_session() as session:
            stored = await session.get(ModerationAction, created.id)
            assert stored.action_type == ActionType.BAN
            assert stored.is_active is True
    finally:
        action_service.ban_guild_member = original_ban
        await engine.dispose()


def test_create_action_ban_effect_calls_discord_ban():
    banned_users: list[dict] = []
    asyncio.run(_ban_effect_scenario(banned_users))

    assert len(banned_users) == 1
    assert banned_users[0]["delete_message_seconds"] == 0


def test_default_dashboard_base_url_is_modral(monkeypatch):
    from api.services.moderation_actions_service import _dashboard_action_url

    monkeypatch.delenv("DASHBOARD_BASE_URL", raising=False)
    assert _dashboard_action_url(478278763239702538, "action-id").startswith(
        "https://dashboard.modral.app/dashboard/478278763239702538/"
    )

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlmodel import select

from api.models.moderation_actions import ModerationActionCreate
from api.models.moderation_rules import ModerationRuleReadModel
from api.services.moderation_action_numbers import resolve_moderation_action_reference
from api.services.moderation_actions_service import (
    _build_action_log_embed,
    _build_action_log_message,
    _build_action_revert_log_embed,
    build_action_log_components,
    create_action,
    get_deleted_messages_for_action,
    get_linked_messages_for_action,
    link_message_to_action,
    revert_action,
)
from api.services.moderation_rules_service import create_manual_rule
from src.db.database import engine, get_async_session
from src.modules.localization.service import tr
from src.db.models import (
    ActionType,
    AttachmentLog,
    DeletedMessage,
    GlobalUser,
    MessageLog,
    ModerationAction,
    ModerationActionDeletedMessageLink,
    ModerationActionMessageLink,
    ModerationActionRuleCitation,
    Server,
    ServerModerationSettings,
    User,
)
from src.modules.moderation.bot_services import (
    build_action_payload,
    build_moderator_action_receipt,
    create_bot_moderation_action,
    fetch_active_rule_models,
    find_rule,
    rule_choices,
    rule_label,
)
from src.modules.moderation.moderation_helpers import handle_message_deletion


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


def test_build_moderator_action_receipt_has_private_details(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://dash.example/")
    action_id = uuid4()
    case_id = uuid4()
    expires_at = datetime(2026, 1, 2, 3, 4, 5)
    action = SimpleNamespace(
        id=action_id,
        action_number=42,
        action_type=ActionType.MUTE,
        case_id=case_id,
        commentary="internal moderator note",
        expires_at=expires_at,
    )

    receipt = build_moderator_action_receipt(
        locale="en",
        server_id=123,
        public_message="<@456> muted for `60` minutes by rule `1 No spam`.",
        action=action,
        rule="1 No spam",
    )

    assert "**Moderator receipt**" in receipt
    assert "Public notice: <@456> muted" in receipt
    assert f"https://dash.example/dashboard/123/moderation/actions/{action_id}" in receipt
    assert f"https://dash.example/dashboard/123/moderation/cases/{case_id}" in receipt
    assert "Rule: `1 No spam`" in receipt
    assert "Commentary: internal moderator note" in receipt
    assert "Expires At: `2026-01-02T03:04:05`" in receipt

    localized = build_moderator_action_receipt(
        locale="ru",
        server_id=123,
        public_message="public",
        action=action,
        rule="1 No spam",
    )
    assert tr("ru", "action.private_receipt_title") in localized
    assert tr("ru", "action.public_notice_label") in localized


def test_build_action_log_message_links_dashboard_and_uses_rule_label(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://dash.example/")
    action_id = uuid4()
    case_id = uuid4()
    rule_id = uuid4()
    action = SimpleNamespace(
        id=action_id,
        action_number=42,
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
    assert "**Rule:** `Rule 1\ufe0f\u20e3: No insults`" in message
    assert "Rule ID" not in message
    assert str(rule_id) not in message
    assert "**Case:** [Case Alpha]" in message
    assert "**Action:** [#42]" in message

    localized_message = _build_action_log_message(
        action=action,
        moderator_username="moderator",
        target_username="target",
        locale="ru",
    )
    assert f"**{tr('ru', 'modlog.action_label')}:**" in localized_message
    assert f"**{tr('ru', 'modlog.commentary_label')}:**" in localized_message
    assert f"**{tr('ru', 'modlog.action_number_label')}:**" in localized_message

    embed = _build_action_log_embed(
        action=action,
        moderator_username="moderator",
        target_username="target",
    )
    assert embed["title"] == "Moderation log: warn #42"
    assert embed["url"] == f"https://dash.example/dashboard/123/moderation/actions/{action_id}"
    assert embed["color"] == 0xF2C94C
    field_names = [field["name"] for field in embed["fields"]]
    assert field_names == ["Target", "Moderator", "Rule", "Reason", "Commentary", "Case"]
    assert embed["fields"][3]["value"] == "rule breach"
    assert embed["fields"][4]["value"] == "context note"
    assert "Commentary: context note" not in embed["fields"][3]["value"]
    assert embed["footer"]["text"] == "Action: #42"

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
    assert "**Rule:** `Rule 1\ufe0f\u20e3: No insults`" in duplicate_message
    assert "**Commentary:** context note" in duplicate_message

    duplicate_embed = _build_action_log_embed(
        action=duplicate_reason_action,
        moderator_username="moderator",
        target_username="target",
    )
    assert [field["name"] for field in duplicate_embed["fields"]] == ["Target", "Moderator", "Rule", "Commentary", "Case"]


def test_action_log_components_include_safe_action_controls(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://dash.example/")
    action_id = uuid4()
    action = SimpleNamespace(
        id=action_id,
        action_type=ActionType.WARN,
        server_id=123,
        is_active=True,
    )

    components = build_action_log_components(action)
    buttons = components[0]["components"]

    assert [button["label"] for button in buttons] == [
        "Open dashboard",
        "Add info in dashboard",
        "Revert",
    ]
    assert buttons[0]["url"] == f"https://dash.example/dashboard/123/moderation/actions/{action_id}"
    assert buttons[1]["url"] == buttons[0]["url"]
    assert buttons[2] == {
        "type": 2,
        "style": 4,
        "label": "Revert",
        "custom_id": f"mod-action:revert:{action_id}",
    }

    kick_buttons = build_action_log_components(
        SimpleNamespace(**{**action.__dict__, "action_type": ActionType.KICK})
    )[0]["components"]
    inactive_buttons = build_action_log_components(
        SimpleNamespace(**{**action.__dict__, "is_active": False})
    )[0]["components"]

    assert len(kick_buttons) == 2
    assert len(inactive_buttons) == 2
    assert build_action_log_components(action, "ru")[0]["components"][2]["label"] == tr(
        "ru",
        "action.revert_button",
    )


def test_build_action_revert_log_embed_links_dashboard_and_uses_display_names(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://dash.example/")
    action_id = uuid4()
    action = SimpleNamespace(
        id=action_id,
        action_number=42,
        action_type=ActionType.WARN,
        server_id=123,
        target_user_id=456,
    )

    embed = _build_action_revert_log_embed(
        action=action,
        moderator_user_id=789,
        moderator_username="moderator",
        target_username="target",
        reason="mistaken action",
        discord_changed=False,
    )

    assert embed["title"] == "Moderation log: revert"
    assert embed["url"] == f"https://dash.example/dashboard/123/moderation/actions/{action_id}"
    assert embed["color"] == 0x5865F2
    assert embed["fields"][0]["value"] == "<@456> (`target`, `456`)"
    assert embed["fields"][1]["value"] == "<@789> (`moderator`, `789`)"
    assert embed["fields"][2]["value"] == f"[warn #42](https://dash.example/dashboard/123/moderation/actions/{action_id})"
    assert embed["fields"][3]["value"] == "mistaken action"
    assert embed["fields"][4]["value"] == "`False`"
    assert embed["footer"]["text"] == "Action: #42"


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
            action_number=1,
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
        assert created.action_number == 2
        assert (
            await resolve_moderation_action_reference(
                session,
                server_id=server_id,
                reference="#2",
            )
        ).id == created.id
        assert (
            await resolve_moderation_action_reference(
                session,
                server_id=server_id,
                reference=str(created.id),
            )
        ).id == created.id
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


async def _action_message_cleanup_scenario(deleted_messages: list[dict]) -> None:
    import api.services.moderation_actions_service as action_service

    original_delete_channel_message = action_service.delete_channel_message

    async def fake_delete_channel_message(channel_id: int, message_id: int) -> None:
        deleted_messages.append({"channel_id": channel_id, "message_id": message_id})

    action_service.delete_channel_message = fake_delete_channel_message

    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()
    other_user_id = _make_discord_id()
    channel_id = _make_discord_id()
    selected_message_id = _make_discord_id()
    recent_message_id = _make_discord_id()
    other_message_id = _make_discord_id()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        async with get_async_session() as session:
            session.add(Server(server_id=server_id, server_name="cleanup-server", bot_active=True))
            session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
            session.add(GlobalUser(discord_id=target_id, username="target"))
            session.add(GlobalUser(discord_id=other_user_id, username="other"))
            session.add(User(user_id=moderator_id, server_id=server_id, server_nickname="mod", is_member=True))
            session.add(User(user_id=target_id, server_id=server_id, server_nickname="target", is_member=True))
            session.add(User(user_id=other_user_id, server_id=server_id, server_nickname="other", is_member=True))
            await session.flush()
            session.add(
                MessageLog(
                    message_id=selected_message_id,
                    server_id=server_id,
                    channel_id=channel_id,
                    user_id=target_id,
                    content="selected message",
                    created_at=now,
                )
            )
            session.add(
                AttachmentLog(
                    message_id=selected_message_id,
                    storage_key="https://cdn.example/selected.png",
                    file_name="selected.png",
                    content_type="image/png",
                )
            )
            session.add(
                MessageLog(
                    message_id=recent_message_id,
                    server_id=server_id,
                    channel_id=channel_id,
                    user_id=target_id,
                    content="recent message",
                    created_at=now,
                )
            )
            session.add(
                MessageLog(
                    message_id=other_message_id,
                    server_id=server_id,
                    channel_id=channel_id,
                    user_id=other_user_id,
                    content="other message",
                    created_at=now,
                )
            )
            payload = ModerationActionCreate(
                action_type=ActionType.WARN,
                moderator_user_id=moderator_id,
                reason="cleanup warn",
                target_user_id=target_id,
                target_user_name="target",
                target_user_joined_at=now,
                target_user_server_nickname="target",
                server_id=server_id,
                server_name="cleanup-server",
                message_cleanup={
                    "message_ids": [str(selected_message_id), str(other_message_id)],
                    "recent_period_minutes": 60,
                    "recent_limit": 5,
                },
            )
            created = await create_action(
                session=session,
                action=payload,
                moderator_user_id=moderator_id,
                apply_discord_effects=False,
            )
            created_action_id = created.id
            await session.commit()

        async with get_async_session() as session:
            remaining_logs = (
                await session.exec(select(MessageLog).where(MessageLog.server_id == server_id))
            ).all()
            deleted_rows = (
                await session.exec(
                    select(DeletedMessage).where(DeletedMessage.server_id == server_id)
                )
            ).all()
            link_rows = (
                await session.exec(
                    select(ModerationActionDeletedMessageLink).where(
                        ModerationActionDeletedMessageLink.moderation_action_id == created_action_id
                    )
                )
            ).all()

        assert [row.message_id for row in remaining_logs] == [other_message_id]
        assert sorted(row.message_id for row in deleted_rows) == sorted(
            [selected_message_id, recent_message_id]
        )
        assert all(row.deleted_by_user_id == moderator_id for row in deleted_rows)
        assert len(link_rows) == 2
        selected_deleted = next(row for row in deleted_rows if row.message_id == selected_message_id)
        assert "selected.png" in (selected_deleted.attachments_json or "")
    finally:
        action_service.delete_channel_message = original_delete_channel_message
        await engine.dispose()


def test_create_action_can_delete_and_link_target_messages():
    deleted_messages: list[dict] = []
    asyncio.run(_action_message_cleanup_scenario(deleted_messages))

    assert len(deleted_messages) == 2


async def _live_message_action_link_migrates_on_delete_scenario() -> None:
    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()
    channel_id = _make_discord_id()
    message_id = _make_discord_id()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="link-server", bot_active=True))
        session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
        session.add(GlobalUser(discord_id=target_id, username="target"))
        session.add(User(user_id=moderator_id, server_id=server_id, is_member=True))
        session.add(User(user_id=target_id, server_id=server_id, is_member=True))
        await session.flush()
        action = ModerationAction(
            action_number=1,
            action_type=ActionType.WARN,
            server_id=server_id,
            target_user_id=target_id,
            moderator_user_id=moderator_id,
            reason="linked evidence",
            created_at=now,
        )
        session.add(action)
        session.add(
            MessageLog(
                message_id=message_id,
                server_id=server_id,
                channel_id=channel_id,
                user_id=target_id,
                content="durable evidence",
                created_at=now,
            )
        )
        await session.flush()
        action_id = action.id
        result = await link_message_to_action(
            session,
            action_id=action_id,
            message_id=message_id,
            linked_by_user_id=moderator_id,
        )
        assert result.state == "live"
        assert len(await get_linked_messages_for_action(session, action_id)) == 1
        await session.commit()

    async with get_async_session() as session:
        await handle_message_deletion(message_id, server_id, session)

    async with get_async_session() as session:
        assert (
            await session.exec(
                select(ModerationActionMessageLink).where(
                    ModerationActionMessageLink.moderation_action_id == action_id
                )
            )
        ).first() is None
        deleted = await get_deleted_messages_for_action(session, action_id)
        assert len(deleted) == 1
        assert deleted[0].message_id == str(message_id)
        assert deleted[0].content == "durable evidence"

    await engine.dispose()


def test_live_message_action_link_migrates_to_deleted_evidence():
    asyncio.run(_live_message_action_link_migrates_on_delete_scenario())


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
        action_number,
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
                "action_number": action_number,
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
                action_number=1,
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
    assert effect_observations[0]["action_number"] == 2
    assert effect_observations[0]["is_active"] is True
    assert effect_observations[0]["mute_role_id"] is not None


async def _all_action_dm_scenario(events: list[tuple[str, str]]) -> None:
    import api.services.moderation_actions_service as action_service

    originals = {
        "create_direct_message": action_service.create_direct_message,
        "add_guild_member_role": action_service.add_guild_member_role,
        "kick_guild_member": action_service.kick_guild_member,
        "ban_guild_member": action_service.ban_guild_member,
    }

    class FakeSession:
        async def get(self, _model, _key):
            return None

    async def fake_dm(user_id: int, content: str) -> dict:
        events.append(("dm", content))
        return {"recipient_id": user_id}

    async def fake_add_role(server_id: int, user_id: int, role_id: int) -> None:
        events.append(("mute", str(role_id)))

    async def fake_kick(server_id: int, user_id: int) -> None:
        events.append(("kick", str(user_id)))

    async def fake_ban(server_id: int, user_id: int, delete_message_seconds: int = 0) -> None:
        events.append(("ban", str(user_id)))

    action_service.create_direct_message = fake_dm
    action_service.add_guild_member_role = fake_add_role
    action_service.kick_guild_member = fake_kick
    action_service.ban_guild_member = fake_ban

    try:
        for action_number, action_type in enumerate(
            (ActionType.WARN, ActionType.MUTE, ActionType.KICK, ActionType.BAN),
            start=1,
        ):
            payload = ModerationActionCreate(
                action_type=action_type,
                moderator_user_id=100,
                reason="Rule 9",
                commentary="Moderator context",
                expires_at=(
                    datetime(2026, 7, 20, tzinfo=timezone.utc)
                    if action_type in {ActionType.MUTE, ActionType.BAN}
                    else None
                ),
                target_user_id=200,
                target_user_name="target",
                target_user_joined_at=datetime(2026, 1, 1),
                target_user_server_nickname=None,
                server_id=300,
                server_name="CyberColors",
            )
            await action_service._apply_discord_action_effects(
                session=FakeSession(),
                action=payload,
                resolved_reason="Rule 9",
                resolved_rules=[],
                resolved_commentary="Moderator context",
                action_number=action_number,
                mute_role_id=400 if action_type == ActionType.MUTE else None,
            )
    finally:
        for name, value in originals.items():
            setattr(action_service, name, value)


def test_warn_mute_kick_and_ban_send_localized_user_dms() -> None:
    events: list[tuple[str, str]] = []
    asyncio.run(_all_action_dm_scenario(events))

    assert [kind for kind, _value in events] == [
        "dm",
        "mute",
        "dm",
        "dm",
        "kick",
        "dm",
        "ban",
    ]
    dm_messages = [value for kind, value in events if kind == "dm"]
    assert ["warned", "muted", "kicked", "banned"] == [
        next(word for word in ("warned", "muted", "kicked", "banned") if word in message)
        for message in dm_messages
    ]
    assert all("Rule 9" in message and "Moderator context" in message for message in dm_messages)
    assert "#1" in dm_messages[0]
    assert "#4" in dm_messages[3]
    assert "**Expires:**" in dm_messages[1]
    assert "**Expires:**" in dm_messages[3]


def test_closed_user_dms_do_not_block_moderation_effect(monkeypatch) -> None:
    import api.services.moderation_actions_service as action_service

    kicked_users: list[int] = []

    class FakeSession:
        async def get(self, _model, _key):
            return None

    async def reject_dm(user_id: int, content: str) -> dict:
        raise RuntimeError("DMs are closed")

    async def fake_kick(server_id: int, user_id: int) -> None:
        kicked_users.append(user_id)

    monkeypatch.setattr(action_service, "create_direct_message", reject_dm)
    monkeypatch.setattr(action_service, "kick_guild_member", fake_kick)

    async def scenario() -> None:
        await action_service._apply_discord_action_effects(
            session=FakeSession(),
            action=ModerationActionCreate(
                action_type=ActionType.KICK,
                moderator_user_id=100,
                reason="Rule 9",
                target_user_id=200,
                target_user_name="target",
                target_user_joined_at=datetime(2026, 1, 1),
                target_user_server_nickname=None,
                server_id=300,
                server_name="CyberColors",
            ),
            resolved_reason="Rule 9",
            resolved_rules=[],
            resolved_commentary=None,
            action_number=12,
        )

    asyncio.run(scenario())
    assert kicked_users == [200]


def test_action_revert_sends_user_dm(monkeypatch) -> None:
    import api.services.moderation_actions_service as action_service

    sent_messages: list[dict] = []

    class FakeSession:
        async def get(self, model, _key):
            if model is Server:
                return SimpleNamespace(server_name="CyberColors")
            return None

    async def fake_dm(user_id: int, content: str) -> dict:
        sent_messages.append({"user_id": user_id, "content": content})
        return {}

    monkeypatch.setattr(action_service, "create_direct_message", fake_dm)
    asyncio.run(
        action_service.send_action_revert_dm(
            session=FakeSession(),
            action=SimpleNamespace(
                action_type=ActionType.MUTE,
                action_number=42,
                target_user_id=200,
                server_id=300,
            ),
            reason="Appeal accepted",
        )
    )

    assert sent_messages[0]["user_id"] == 200
    assert "mute action **#42**" in sent_messages[0]["content"]
    assert "Appeal accepted" in sent_messages[0]["content"]

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


async def _revert_ban_action_scenario(unbanned_users: list[dict]) -> None:
    async def fake_unban_guild_member(server_id: int, user_id: int) -> None:
        unbanned_users.append({"server_id": server_id, "user_id": user_id})

    import api.services.moderation_actions_service as action_service

    original_unban = action_service.unban_guild_member
    action_service.unban_guild_member = fake_unban_guild_member

    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()

    try:
        async with get_async_session() as session:
            session.add(Server(server_id=server_id, server_name="revert-ban-server", bot_active=True))
            session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
            session.add(GlobalUser(discord_id=target_id, username="target"))
            action = ModerationAction(
                action_number=1,
                action_type=ActionType.BAN,
                moderator_user_id=moderator_id,
                reason="bad behavior",
                target_user_id=target_id,
                server_id=server_id,
                is_active=True,
            )
            session.add(action)
            await session.flush()
            action_id = action.id

            read, discord_changed = await revert_action(
                session=session,
                server_id=server_id,
                action_id=action_id,
                moderator_user_id=moderator_id,
                reason="appeal accepted",
            )
            await session.commit()

        async with get_async_session() as session:
            stored = await session.get(ModerationAction, action_id)
            assert stored.is_active is False
            assert stored.expires_at is not None
        assert read.is_active is False
        assert discord_changed is True
    finally:
        action_service.unban_guild_member = original_unban
        await engine.dispose()


def test_revert_ban_action_unbans_and_closes_action():
    unbanned_users: list[dict] = []
    asyncio.run(_revert_ban_action_scenario(unbanned_users))

    assert len(unbanned_users) == 1


async def _revert_mute_action_scenario(removed_roles: list[dict]) -> None:
    async def fake_fetch_guild_member(server_id: int, user_id: int) -> dict:
        return {"user": {"id": str(user_id)}, "roles": [str(mute_role_id)]}

    async def fake_remove_guild_member_role(server_id: int, user_id: int, role_id: int) -> None:
        removed_roles.append({"server_id": server_id, "user_id": user_id, "role_id": role_id})

    import api.services.moderation_actions_service as action_service

    original_fetch_member = action_service.fetch_guild_member
    original_remove_role = action_service.remove_guild_member_role
    action_service.fetch_guild_member = fake_fetch_guild_member
    action_service.remove_guild_member_role = fake_remove_guild_member_role

    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()
    mute_role_id = _make_discord_id()

    try:
        async with get_async_session() as session:
            session.add(Server(server_id=server_id, server_name="revert-mute-server", bot_active=True))
            session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
            session.add(GlobalUser(discord_id=target_id, username="target"))
            session.add(ServerModerationSettings(server_id=server_id, mute_role_id=mute_role_id))
            action = ModerationAction(
                action_number=1,
                action_type=ActionType.MUTE,
                moderator_user_id=moderator_id,
                reason="spam",
                target_user_id=target_id,
                server_id=server_id,
                is_active=True,
            )
            session.add(action)
            await session.flush()
            action_id = action.id

            read, discord_changed = await revert_action(
                session=session,
                server_id=server_id,
                action_id=action_id,
                moderator_user_id=moderator_id,
                reason=None,
            )
            await session.commit()

        async with get_async_session() as session:
            stored = await session.get(ModerationAction, action_id)
            assert stored.is_active is False
        assert read.is_active is False
        assert discord_changed is True
    finally:
        action_service.fetch_guild_member = original_fetch_member
        action_service.remove_guild_member_role = original_remove_role
        await engine.dispose()


def test_revert_mute_action_removes_mute_role_and_closes_action():
    removed_roles: list[dict] = []
    asyncio.run(_revert_mute_action_scenario(removed_roles))

    assert len(removed_roles) == 1


async def _revert_warn_action_scenario() -> None:
    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="revert-warn-server", bot_active=True))
        session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
        session.add(GlobalUser(discord_id=target_id, username="target"))
        action = ModerationAction(
            action_number=1,
            action_type=ActionType.WARN,
            moderator_user_id=moderator_id,
            reason="rule break",
            target_user_id=target_id,
            server_id=server_id,
            is_active=True,
        )
        session.add(action)
        await session.flush()
        action_id = action.id

        read, discord_changed = await revert_action(
            session=session,
            server_id=server_id,
            action_id=action_id,
            moderator_user_id=moderator_id,
            reason="warn accepted by mistake",
        )
        await session.commit()

    async with get_async_session() as session:
        stored = await session.get(ModerationAction, action_id)
        assert stored.is_active is False
        assert stored.expires_at is not None
    assert read.is_active is False
    assert discord_changed is False
    await engine.dispose()


def test_revert_warn_action_closes_action_without_discord_effect():
    asyncio.run(_revert_warn_action_scenario())


def test_default_dashboard_base_url_is_modral(monkeypatch):
    from api.services.moderation_actions_service import _dashboard_action_url

    monkeypatch.delenv("DASHBOARD_BASE_URL", raising=False)
    assert _dashboard_action_url(478278763239702538, "action-id").startswith(
        "https://dashboard.modral.app/dashboard/478278763239702538/"
    )

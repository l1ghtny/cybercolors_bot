import asyncio
from types import SimpleNamespace
from uuid import uuid4

from src.modules.ai.models import MessageModerationInput
from src.db.models import AIModerationDecision, ActionType, ServerAISettings, ServerModerationSettings
from src.modules.ai.models import AIResponse, ModerationVerdict
from src.modules.ai.moderation_review import (
    AIActionSelect,
    AIActionRuleSelectionView,
    AIModerationReviewView,
    _bot_can_read_message_channel,
    _bot_can_send_ai_mod_log,
    build_ai_moderation_embed,
    create_ai_moderation_decision,
    screen_message_with_ai,
)
from api.models.moderation_rules import ModerationRuleReadModel


class FakeSession:
    def __init__(self):
        self.added = None
        self.committed = False

    def add(self, item):
        self.added = item

    async def flush(self):
        return None

    async def refresh(self, item):
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        return None


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeExistingResult:
    def __init__(self, existing):
        self.existing = existing

    def first(self):
        return self.existing


class FakeExistingSession(FakeSession):
    def __init__(self, existing):
        super().__init__()
        self.existing = existing

    async def exec(self, _statement):
        return FakeExistingResult(self.existing)


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


def test_ai_moderation_channel_read_preflight_checks_bot_permissions():
    bot_member = object()
    permissions = SimpleNamespace(view_channel=False, read_messages=True, read_message_history=True)
    channel = SimpleNamespace(id=456, permissions_for=lambda member: permissions)
    message = SimpleNamespace(guild=SimpleNamespace(id=123, me=bot_member), channel=channel)

    assert _bot_can_read_message_channel(message) is False

    permissions.view_channel = True
    assert _bot_can_read_message_channel(message) is True


def test_ai_moderation_mod_log_preflight_checks_write_permissions():
    bot_member = object()
    permissions = SimpleNamespace(view_channel=True, send_messages=False, send_messages_in_threads=False, embed_links=True)
    channel = SimpleNamespace(id=456, type=None, permissions_for=lambda member: permissions)
    guild = SimpleNamespace(id=123, me=bot_member)

    assert _bot_can_send_ai_mod_log(guild, channel) is False

    permissions.send_messages = True
    assert _bot_can_send_ai_mod_log(guild, channel) is True


def test_ai_action_select_supports_watch_suggestion():
    select = AIActionSelect(decision_id=uuid4(), suggested_action="watch")

    values = [option.value for option in select.options]
    assert values == ["watch", "warn", "mute", "kick", "ban", "none"]
    assert any(option.value == "watch" and option.default for option in select.options)


def test_ai_review_view_uses_russian_component_labels():
    view = AIModerationReviewView(decision_id=uuid4(), suggested_action="warn", locale="ru")

    button_labels = [item.label for item in view.children if hasattr(item, "label")]
    assert "\u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c" in button_labels
    assert "\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u043a\u0435\u0439\u0441" in button_labels

    action_select = next(item for item in view.children if isinstance(item, AIActionSelect))
    assert action_select.placeholder == "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u043c\u043e\u0434\u0435\u0440\u0430\u0442\u043e\u0440\u0430"
    warn_option = next(option for option in action_select.options if option.value == "warn")
    assert warn_option.label == "\u041f\u0440\u0435\u0434\u0443\u043f\u0440\u0435\u0436\u0434\u0435\u043d\u0438\u0435"
    assert warn_option.default is True


def test_ai_rule_selection_view_uses_russian_component_labels():
    view = AIActionRuleSelectionView(
        decision_id=uuid4(),
        action_type=ActionType.WARN,
        rules=[_rule_model(str(uuid4()), "1", "Spam")],
        default_rule_ids=set(),
        default_reason="reason",
        default_duration_minutes=60,
        locale="ru",
    )

    assert view.rule_select.placeholder == "\u041d\u0430\u0440\u0443\u0448\u0435\u043d\u043d\u044b\u0435 \u043f\u0440\u0430\u0432\u0438\u043b\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0430"
    labels = [item.label for item in view.children if hasattr(item, "label")]
    assert "\u041f\u043e\u0438\u0441\u043a" in labels
    assert "\u0414\u0430\u043b\u0435\u0435" in labels
    assert "\u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c" in labels
    assert view.content().startswith("\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u043d\u0430\u0440\u0443\u0448\u0435\u043d\u043d\u044b\u0435 \u043f\u0440\u0430\u0432\u0438\u043b\u0430")

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
    assert decision.total_tokens == 10
    assert decision.categories == ["spam"]
    assert decision.rule_ids == ["rule-1"]
    assert decision.attachments_json == [{"filename": "proof.png"}]


def test_create_ai_moderation_decision_returns_existing_message_decision():
    existing = AIModerationDecision(
        server_id=123,
        channel_id=456,
        message_id=789,
        author_user_id=101,
        flagged=True,
        severity="high",
        suggested_action="warn",
    )
    session = FakeExistingSession(existing)
    verdict = ModerationVerdict(flagged=True, severity="high", reason="Spam", suggested_action="warn")
    settings = ServerAISettings(server_id=123, moderation_strictness="high")

    decision = asyncio.run(
        create_ai_moderation_decision(
            session=session,
            message=_fake_message(),
            verdict=verdict,
            settings=settings,
            attachments=[],
        )
    )

    assert decision is existing
    assert session.added is None


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

    assert embed.title == "AI moderation review needed"
    assert "Likely insult" in embed.description
    assert any(field.name == "Context" and "Open in Discord" in field.value for field in embed.fields)
    assert any(field.name == "Suggested action" and "manual_review" in field.value for field in embed.fields)
    assert any(field.name == "Possible rules" and "rule-1" in field.value for field in embed.fields)


def test_send_ai_moderation_review_uses_configured_review_channel(monkeypatch):
    import src.modules.ai.moderation_review as moderation_review

    review_channel_id = 777
    mod_log_channel_id = 888
    sent_payloads = []
    decision = AIModerationDecision(
        server_id=123,
        channel_id=456,
        message_id=789,
        author_user_id=101,
        flagged=True,
        severity="medium",
        suggested_action="watch",
        reason="Needs review",
    )

    class FakeSentMessage:
        id = 999
        channel = SimpleNamespace(id=review_channel_id)

    class FakeChannel:
        id = review_channel_id

        async def send(self, **kwargs):
            sent_payloads.append(kwargs)
            return FakeSentMessage()

    class FakeGuild:
        id = 123
        name = "Guild"
        me = object()

        def __init__(self):
            self.requested_channel_ids = []
            self.review_channel = FakeChannel()

        def get_channel(self, channel_id):
            self.requested_channel_ids.append(channel_id)
            if channel_id == review_channel_id:
                return self.review_channel
            return None

    class ReviewSession(FakeSession):
        async def get(self, model, key):
            if model is ServerModerationSettings:
                return ServerModerationSettings(server_id=123, mod_log_channel_id=mod_log_channel_id)
            if model is AIModerationDecision:
                return decision
            return None

    settings = ServerAISettings(server_id=123, moderation_review_channel_id=review_channel_id)
    session = ReviewSession()
    guild = FakeGuild()
    message = _fake_message()
    message.guild = guild

    async def fake_get_settings(_session, server_id, server_name=None):
        assert server_id == 123
        return settings

    async def fake_server_locale(*_args, **_kwargs):
        return "en"

    async def fake_rule_labels(*_args, **_kwargs):
        return []

    async def fake_open_cases(*_args, **_kwargs):
        return []

    monkeypatch.setattr(moderation_review, "get_async_session", lambda: FakeSessionContext(session))
    monkeypatch.setattr(moderation_review, "get_or_create_server_ai_settings", fake_get_settings)
    monkeypatch.setattr(moderation_review, "_server_locale", fake_server_locale)
    monkeypatch.setattr(moderation_review, "_rule_labels_for_decision", fake_rule_labels)
    monkeypatch.setattr(moderation_review, "fetch_open_case_models", fake_open_cases)
    monkeypatch.setattr(moderation_review, "_bot_can_send_ai_mod_log", lambda *_args, **_kwargs: True)

    sent = asyncio.run(moderation_review.send_ai_moderation_review(guild=guild, message=message, decision=decision))

    assert sent is True
    assert guild.requested_channel_ids == [review_channel_id]
    assert sent_payloads
    assert decision.review_channel_id == review_channel_id
    assert decision.review_message_id == 999


def test_ai_moderation_embed_surfaces_moderator_override():
    decision = AIModerationDecision(
        server_id=123,
        channel_id=456,
        message_id=789,
        author_user_id=101,
        flagged=True,
        severity="medium",
        reason="AI wanted a warning",
        suggested_action="warn",
        selected_action="mute",
        action_override=True,
    )

    embed = build_ai_moderation_embed(decision, _fake_message())

    assert embed.title == "AI moderation review needed"
    assert any(field.name == "Moderator action" and "mute" in field.value and "override: yes" in field.value for field in embed.fields)


def test_ai_moderation_review_view_uses_persistent_custom_ids():
    decision_id = uuid4()

    view = AIModerationReviewView(decision_id=decision_id, suggested_action="warn", include_case_select=True)

    assert view.timeout is None
    custom_ids = {item.custom_id for item in view.children if getattr(item, "custom_id", None)}
    assert f"ai_mod:dismiss:{decision_id}" in custom_ids
    assert f"ai_mod:create_case:{decision_id}" in custom_ids
    assert f"ai_mod:action:{decision_id}" in custom_ids
    assert f"ai_mod:case:{decision_id}" in custom_ids


def _rule_model(rule_id: str, code: str, title: str) -> ModerationRuleReadModel:
    from datetime import datetime

    return ModerationRuleReadModel(
        id=rule_id,
        server_id="123",
        code=code,
        title=title,
        description=None,
        sort_order=int(code),
        is_active=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


def test_ai_action_rule_selection_view_preserves_default_rules_until_changed():
    first_rule_id = str(uuid4())
    second_rule_id = str(uuid4())
    view = AIActionRuleSelectionView(
        decision_id=uuid4(),
        action_type=ActionType.WARN,
        rules=[
            _rule_model(first_rule_id, "1", "No insults"),
            _rule_model(second_rule_id, "2", "No spam"),
        ],
        default_rule_ids={second_rule_id},
        default_reason="AI reason",
        default_duration_minutes=60,
    )

    assert view.selected_rule_ids == [second_rule_id]
    options = view.rule_select.options
    assert [option.default for option in options] == [False, True]


def test_ai_action_rule_selection_view_searches_and_keeps_hidden_selection():
    selected_rule_id = str(uuid4())
    search_match_id = str(uuid4())
    view = AIActionRuleSelectionView(
        decision_id=uuid4(),
        action_type=ActionType.WARN,
        rules=[
            _rule_model(selected_rule_id, "1", "No insults"),
            _rule_model(search_match_id, "2", "No spam"),
        ],
        default_rule_ids={selected_rule_id},
        default_reason="AI reason",
        default_duration_minutes=60,
    )

    view.search_query = "spam"
    view.rebuild_items()

    assert view.selected_rule_ids == [selected_rule_id]
    assert [option.value for option in view.rule_select.options] == [search_match_id]
    assert view.rule_select.options[0].default is False

    view.update_visible_selection(selected_visible_rule_ids=[search_match_id], visible_rule_ids={search_match_id})

    assert view.selected_rule_ids == [selected_rule_id, search_match_id]


def test_ai_action_rule_selection_view_pages_rules():
    rules = [_rule_model(str(uuid4()), str(index + 1), f"Rule {index + 1}") for index in range(30)]
    view = AIActionRuleSelectionView(
        decision_id=uuid4(),
        action_type=ActionType.WARN,
        rules=rules,
        default_rule_ids={str(rules[27].id)},
        default_reason="AI reason",
        default_duration_minutes=60,
    )

    assert view.max_page == 1
    assert len(view.rule_select.options) == 25
    assert str(rules[27].id) in view.selected_rule_ids

    view.page = 1
    view.rebuild_items()

    assert [option.value for option in view.rule_select.options] == [str(rule.id) for rule in rules[25:]]
    assert any(option.value == str(rules[27].id) and option.default for option in view.rule_select.options)


def test_screen_message_with_ai_timeout_does_not_raise_or_commit(monkeypatch):
    session = FakeSession()
    settings = ServerAISettings(
        server_id=123,
        moderation_enabled=True,
        moderation_provider_timeout_seconds=0.001,
    )
    message = _fake_message()
    message.guild.name = "Guild"
    message.author.bot = False

    async def fake_get_settings(_session, server_id, server_name=None):
        return settings

    async def fake_existing(*_args, **_kwargs):
        return None

    async def fake_usage_cap(*_args, **_kwargs):
        return False

    class SlowAI:
        async def check_message(self, message_input: MessageModerationInput, **_kwargs):
            await asyncio.sleep(0.05)
            return ModerationVerdict(flagged=True, severity="high", reason="late")

    import src.modules.ai.moderation_review as moderation_review

    monkeypatch.setattr(moderation_review, "get_async_session", lambda: FakeSessionContext(session))
    monkeypatch.setattr(moderation_review, "get_or_create_server_ai_settings", fake_get_settings)
    monkeypatch.setattr(moderation_review, "_find_existing_decision", fake_existing)
    monkeypatch.setattr(moderation_review, "_usage_cap_reached", fake_usage_cap)
    monkeypatch.setattr(moderation_review, "ai_main_class", SlowAI())

    asyncio.run(screen_message_with_ai(message))

    assert session.committed is False


def test_screen_message_with_ai_kill_switch_skips_provider(monkeypatch):
    session = FakeSession()
    settings = ServerAISettings(
        server_id=123,
        moderation_enabled=True,
        moderation_kill_switch_enabled=True,
    )
    message = _fake_message()
    message.guild.name = "Guild"
    message.author.bot = False

    async def fake_get_settings(_session, server_id, server_name=None):
        return settings

    class FailingAI:
        async def check_message(self, *_args, **_kwargs):
            raise AssertionError("provider should not be called when kill switch is enabled")

    import src.modules.ai.moderation_review as moderation_review

    monkeypatch.setattr(moderation_review, "get_async_session", lambda: FakeSessionContext(session))
    monkeypatch.setattr(moderation_review, "get_or_create_server_ai_settings", fake_get_settings)
    monkeypatch.setattr(moderation_review, "ai_main_class", FailingAI())

    asyncio.run(screen_message_with_ai(message))

    assert session.committed is False


def test_screen_message_with_ai_moderates_allowed_answer_flow_invocation_with_context(monkeypatch):
    session = FakeSession()
    settings = ServerAISettings(
        server_id=123,
        moderation_enabled=True,
        log_ai_decisions=True,
        answer_channel_mode="all",
    )
    bot_member = SimpleNamespace(id=999)
    message = _fake_message()
    message.guild.name = "Guild"
    message.guild.me = bot_member
    message.author.bot = False
    message.author.roles = []
    message.mentions = [bot_member]
    message.reference = SimpleNamespace(
        resolved=SimpleNamespace(
            id=222,
            content="The phrase being joked about",
            attachments=[],
            author=SimpleNamespace(id=333, display_name="original"),
        )
    )

    async def fake_get_settings(_session, server_id, server_name=None):
        return settings

    async def fake_existing(*_args, **_kwargs):
        return None

    async def fake_usage_cap(*_args, **_kwargs):
        return False

    async def fake_send_review(*_args, **_kwargs):
        raise AssertionError("ordinary allowed answer-flow invocation should not send a review")

    class QuietAI:
        async def check_message(self, message_input: MessageModerationInput, **_kwargs):
            assert message_input.current_bot_mentioned is True
            assert message_input.answer_flow_invocation is True
            assert message_input.bot_user_id == 999
            assert message_input.reply_to_message_id == 222
            assert message_input.reply_to_author_user_id == 333
            assert message_input.reply_to_author_display_name == "original"
            assert message_input.reply_to_content == "The phrase being joked about"
            return ModerationVerdict(
                flagged=False,
                severity="none",
                reason="Allowed bot interaction",
                raw_response=AIResponse(content="{}", model="test-model", provider="fake", total_tokens=5),
            )

    import src.modules.ai.moderation_review as moderation_review

    monkeypatch.setattr(moderation_review, "get_async_session", lambda: FakeSessionContext(session))
    monkeypatch.setattr(moderation_review, "get_or_create_server_ai_settings", fake_get_settings)
    monkeypatch.setattr(moderation_review, "_find_existing_decision", fake_existing)
    monkeypatch.setattr(moderation_review, "_usage_cap_reached", fake_usage_cap)
    monkeypatch.setattr(moderation_review, "send_ai_moderation_review", fake_send_review)
    monkeypatch.setattr(moderation_review, "ai_main_class", QuietAI())

    asyncio.run(screen_message_with_ai(message))

    assert session.committed is True
    assert session.added is not None
    assert session.added.flagged is False
    assert session.added.status == "no_action_needed"


def test_screen_message_with_ai_persists_unflagged_decision_when_cap_is_configured(monkeypatch):
    session = FakeSession()
    settings = ServerAISettings(
        server_id=123,
        moderation_enabled=True,
        log_ai_decisions=False,
        moderation_daily_token_limit=5000,
        moderation_provider_timeout_seconds=1,
    )
    message = _fake_message()
    message.guild.name = "Guild"
    message.author.bot = False

    async def fake_get_settings(_session, server_id, server_name=None):
        return settings

    async def fake_existing(*_args, **_kwargs):
        return None

    async def fake_usage_cap(*_args, **_kwargs):
        return False

    async def fake_send_review(*_args, **_kwargs):
        raise AssertionError("unflagged decisions should not send mod-log reviews")

    class QuietAI:
        async def check_message(self, message_input: MessageModerationInput, **_kwargs):
            return ModerationVerdict(
                flagged=False,
                severity="none",
                reason="No issue",
                raw_response=AIResponse(content="{}", model="test-model", provider="fake", total_tokens=42),
            )

    import src.modules.ai.moderation_review as moderation_review

    monkeypatch.setattr(moderation_review, "get_async_session", lambda: FakeSessionContext(session))
    monkeypatch.setattr(moderation_review, "get_or_create_server_ai_settings", fake_get_settings)
    monkeypatch.setattr(moderation_review, "_find_existing_decision", fake_existing)
    monkeypatch.setattr(moderation_review, "_usage_cap_reached", fake_usage_cap)
    monkeypatch.setattr(moderation_review, "send_ai_moderation_review", fake_send_review)
    monkeypatch.setattr(moderation_review, "ai_main_class", QuietAI())

    asyncio.run(screen_message_with_ai(message))

    assert session.committed is True
    assert session.added is not None
    assert session.added.flagged is False
    assert session.added.status == "no_action_needed"
    assert session.added.total_tokens == 42

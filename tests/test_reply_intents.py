import asyncio
import json

import pytest
from pydantic import ValidationError

from api.services import replies_service
from api.models.bot_replies import ReplyConceptCreateModel, ReplyIntentCreateModel
from api.services.reply_variations import suggest_reply_variations
from src.db.models import Replies, ReplyConcept, Triggers
from src.modules.ai.models import AIResponse
from src.modules.on_message_processing.processing_methods import (
    normalize_and_stem_reply_text,
    normalize_reply_text,
)
from src.modules.on_message_processing.reply_matcher import (
    analyze_reply_trigger_coverage,
    canonicalize_reply_concept_references,
    claim_reply_cooldown,
    compile_guild_reply_matcher,
    describe_reply_trigger_variations,
    invalidate_reply_matcher,
)


def test_intent_payload_requires_two_distinct_representative_questions():
    with pytest.raises(ValidationError):
        ReplyIntentCreateModel(
            bot_reply="Answer",
            representative_questions=["What is it?", " what   is it? "],
            admin_id="123",
        )

    payload = ReplyIntentCreateModel(
        bot_reply=" Answer ",
        representative_questions=["What is it?", "How does it work?"],
        generated_variations=["What is it?", "Tell me how it works"],
        admin_id="123",
    )
    assert payload.bot_reply == "Answer"
    assert payload.cooldown_seconds == 10
    assert payload.manual_triggers == []
    assert payload.generated_variations == ["Tell me how it works"]


def test_intent_payload_deduplicates_manual_before_generated_variations():
    payload = ReplyIntentCreateModel(
        bot_reply="Answer",
        representative_questions=["What is it?", "How does it work?"],
        manual_triggers=["What is it?", "Tell me more"],
        generated_variations=["Tell me more", "Explain this"],
        admin_id="123",
    )

    assert payload.manual_triggers == ["Tell me more"]
    assert payload.generated_variations == ["Explain this"]


def test_intent_payload_validates_reply_cooldown_range():
    with pytest.raises(ValidationError):
        ReplyIntentCreateModel(
            bot_reply="Answer",
            representative_questions=["What is it?", "How does it work?"],
            admin_id="123",
            cooldown_seconds=-1,
        )

    with pytest.raises(ValidationError):
        ReplyIntentCreateModel(
            bot_reply="Answer",
            representative_questions=["What is it?", "How does it work?"],
            admin_id="123",
            cooldown_seconds=2_592_001,
        )


def test_create_intent_persists_each_trigger_with_its_actual_source(monkeypatch):
    async def no_op(*_args):
        return None

    async def prepared(*_args, **_kwargs):
        return ["Example one", "Example two"], ["Typed manually"], ["Suggested by AI"]

    class FakeSession:
        def __init__(self):
            self.added = []

        def add(self, item):
            self.added.append(item)

        async def flush(self):
            return None

    monkeypatch.setattr(replies_service, "_ensure_server_exists", no_op)
    monkeypatch.setattr(replies_service, "_ensure_global_user_exists", no_op)
    monkeypatch.setattr(replies_service, "_prepare_intent_triggers", prepared)
    session = FakeSession()

    asyncio.run(
        replies_service.create_reply_intent(
            session,
            1,
            ReplyIntentCreateModel(
                bot_reply="Answer",
                representative_questions=["Example one", "Example two"],
                manual_triggers=["Typed manually"],
                generated_variations=["Suggested by AI"],
                admin_id="2",
            ),
        )
    )

    persisted = {
        item.message: item.source
        for item in session.added
        if isinstance(item, Triggers)
    }
    saved_reply = next(item for item in session.added if isinstance(item, Replies))
    assert saved_reply.cooldown_seconds == 10
    assert persisted == {
        "Example one": "representative",
        "Example two": "representative",
        "Typed manually": "manual",
        "Suggested by AI": "generated",
    }


def test_concept_payload_normalizes_name_and_variants():
    payload = ReplyConceptCreateModel(
        name=" Завсегдатай ",
        variants=["завсегдатай", " завсегдатай ", "постоянный участник"],
    )
    assert payload.name == "завсегдатай"
    assert payload.variants == ["завсегдатай", "постоянный участник"]


def test_russian_normalization_handles_punctuation_whitespace_and_inflection():
    assert normalize_reply_text("  ЧТО—ТАКОЕ...  ") == "что такое"
    assert normalize_and_stem_reply_text("завсегдатай") == normalize_and_stem_reply_text(
        "завсегдатая"
    )


def test_compiled_matcher_resolves_concept_placeholder_and_russian_inflection():
    reply = Replies(
        server_id=1,
        bot_reply="Role answer <@42> <@&84>",
        created_by_id=2,
        mention_user_ids=["42"],
        mention_role_ids=["84"],
        cooldown_seconds=90,
    )
    representative = Triggers(
        message="когда дадут {{завсегдатай}}",
        reply_id=reply.id,
        source="representative",
    )
    concept = ReplyConcept(
        server_id=1,
        name="завсегдатай",
        variants=["завсегдатай", "постоянный участник"],
    )
    matcher = compile_guild_reply_matcher(
        1,
        None,
        [concept],
        [(representative, reply)],
    )

    matched = matcher.match("Когда дадут завсегдатая?")
    assert matched is not None
    assert matched.response_text == "Role answer <@42> <@&84>"
    assert matched.mention_user_ids == frozenset({"42"})
    assert matched.mention_role_ids == frozenset({"84"})
    assert matched.cooldown_seconds == 90
    assert matcher.match("Когда выдадут другую роль?") is None


def test_compiled_matcher_ignores_trigger_with_unknown_concept():
    reply = Replies(server_id=1, bot_reply="Answer", created_by_id=2)
    trigger = Triggers(
        message="что такое {{missing}}",
        reply_id=reply.id,
        source="representative",
    )
    matcher = compile_guild_reply_matcher(1, None, [], [(trigger, reply)])
    assert matcher.rules == ()


def test_reply_cooldown_is_shared_by_all_triggers_for_one_reply():
    invalidate_reply_matcher()
    reply = Replies(
        server_id=1,
        bot_reply="Answer",
        created_by_id=2,
        cooldown_seconds=10,
    )
    first_trigger = Triggers(
        message="what is it",
        reply_id=reply.id,
        source="representative",
    )
    second_trigger = Triggers(
        message="tell me about it",
        reply_id=reply.id,
        source="manual",
    )
    matcher = compile_guild_reply_matcher(
        1,
        None,
        [],
        [(first_trigger, reply), (second_trigger, reply)],
    )
    first_rule = matcher.match("what is it")
    second_rule = matcher.match("tell me about it")

    assert first_rule is not None
    assert second_rule is not None
    assert claim_reply_cooldown(1, first_rule, now=100.0) is True
    assert claim_reply_cooldown(1, second_rule, now=109.9) is False
    assert claim_reply_cooldown(1, second_rule, now=110.0) is True


def test_zero_reply_cooldown_disables_throttling():
    invalidate_reply_matcher()
    reply = Replies(
        server_id=1,
        bot_reply="Answer",
        created_by_id=2,
        cooldown_seconds=0,
    )
    trigger = Triggers(
        message="what is it",
        reply_id=reply.id,
        source="representative",
    )
    rule = compile_guild_reply_matcher(1, None, [], [(trigger, reply)]).rules[0]

    assert claim_reply_cooldown(1, rule, now=100.0) is True
    assert claim_reply_cooldown(1, rule, now=100.0) is True


def test_coverage_uses_live_language_matching_and_source_priority():
    coverage = analyze_reply_trigger_coverage(
        [
            ("generated:0", "когда дают постоянного участника", "generated"),
            ("manual:0", "когда дают завсегдатая?", "manual"),
            ("representative:0", "когда дают {{role}}", "representative"),
        ],
        {"role": ("завсегдатай", "постоянный участник")},
    )

    by_id = {item.id: item for item in coverage}
    assert by_id["representative:0"].covered_by_id is None
    assert by_id["manual:0"].covered_by_id == "representative:0"
    assert by_id["manual:0"].reason == "language_matching"
    assert by_id["generated:0"].covered_by_id == "representative:0"


def test_trigger_variation_preview_returns_inflection_and_concept_groups():
    groups = describe_reply_trigger_variations(
        "когда дадут {{role}}",
        {"role": ("завсегдатай", "постоянный участник")},
    )

    by_label = {group.label: group for group in groups}
    assert by_label["{{role}}"].variants == (
        "завсегдатай",
        "постоянный участник",
    )
    assert "завсегдатая" in by_label["завсегдатай"].variants
    assert "участника" in by_label["участник"].variants
    assert all(group.variants for group in groups)


def test_concept_references_are_canonicalized_with_live_russian_matching():
    concepts = {
        "cybercolors": ("КиберКолорс", "Cyber Colors", "Кибер Королс"),
        "role": ("завсегдатай",),
    }

    assert canonicalize_reply_concept_references(
        "Как вызвать Cyber Colors и встретить завсегдатая?",
        concepts,
    ) == "Как вызвать {{cybercolors}} и встретить {{role}}?"
    assert canonicalize_reply_concept_references(
        "Что умеет {{ CyberColors }}?",
        concepts,
    ) == "Что умеет {{cybercolors}}?"


def test_intent_save_drops_manual_and_generated_triggers_already_covered(monkeypatch):
    async def fake_concepts(_session, _server_id):
        return [
            ReplyConcept(
                server_id=1,
                name="role",
                variants=["завсегдатай", "постоянный участник"],
            )
        ]

    async def fake_server_trigger_rows(_session, _server_id):
        return []

    monkeypatch.setattr(replies_service, "list_reply_concepts", fake_concepts)
    monkeypatch.setattr(replies_service, "_server_trigger_rows", fake_server_trigger_rows)

    representative, manual, generated = asyncio.run(
        replies_service._prepare_intent_triggers(
            object(),
            1,
            ["когда дают {{role}}", "зачем нужна эта роль"],
            ["когда дают завсегдатая", "расскажи про привилегии"],
            ["когда дают постоянного участника", "как вызвать постоянного участника"],
        )
    )

    assert representative == ["когда дают {{role}}", "зачем нужна эта роль"]
    assert manual == ["расскажи про привилегии"]
    assert generated == ["как вызвать {{role}}"]


def test_variation_generation_uses_structured_output_and_deduplicates():
    class FakeProvider:
        provider_name = "fake"

        async def complete(self, request):
            assert request.response_format is not None
            assert request.response_format.strict is True
            assert request.response_format.schema["additionalProperties"] is False
            return AIResponse(
                content=json.dumps(
                    {
                        "variations": [
                            "Что такое завсегдатай?",
                            "Кто такой завсегдатай?",
                            "Зачем нужна роль завсегдатая?",
                            "Как получить завсегдатая?",
                            "Когда дают завсегдатая?",
                            "Что даёт завсегдатай?",
                            "Кому выдают завсегдатая?",
                            "Как стать завсегдатаем?",
                        ]
                    },
                    ensure_ascii=False,
                ),
                model=request.model,
                provider="fake",
            )

    result = asyncio.run(
        suggest_reply_variations(
            bot_reply="Role answer",
            representative_questions=[
                "Что такое завсегдатай?",
                "Как получить роль завсегдатая?",
            ],
            concepts=[],
            provider=FakeProvider(),
            model="test-model",
        )
    )
    assert "Что такое завсегдатай?" not in result.variations
    assert "Кто такой завсегдатай?" in result.variations
    assert result.model == "test-model"


def test_variation_generation_requires_and_enforces_concept_placeholders():
    class FakeProvider:
        provider_name = "fake"

        async def complete(self, request):
            assert "recognition examples only" in request.system_prompt
            request_payload = json.loads(request.messages[0].content)
            assert request_payload["community_concepts"] == [
                {
                    "name": "cybercolors",
                    "placeholder": "{{cybercolors}}",
                    "variants": ["КиберКолорс", "Cyber Colors", "Кибер Королс", "Modral"],
                }
            ]
            return AIResponse(
                content=json.dumps(
                    {
                        "variations": [
                            "Как вызвать Cyber Colors?",
                            "Как пользоваться ботом КиберКолорс?",
                            "Какие функции у Кибер Королс?",
                            "Что умеет Modral?",
                            "Как работает {{ CyberColors }}?",
                            "Какие команды знает этот бот?",
                            "Что можно делать через этого бота?",
                            "Чем он помогает серверу?",
                        ]
                    },
                    ensure_ascii=False,
                ),
                model=request.model,
                provider="fake",
            )

    result = asyncio.run(
        suggest_reply_variations(
            bot_reply="Cyber Colors helps this server.",
            representative_questions=[
                "Что за {{cybercolors}}?",
                "Как пользоваться {{cybercolors}}?",
            ],
            concepts=[
                ReplyConcept(
                    server_id=1,
                    name="cybercolors",
                    variants=["КиберКолорс", "Cyber Colors", "Кибер Королс", "Modral"],
                )
            ],
            provider=FakeProvider(),
            model="test-model",
        )
    )

    assert result.variations[:5] == [
        "Как вызвать {{cybercolors}}?",
        "Как пользоваться ботом {{cybercolors}}?",
        "Какие функции у {{cybercolors}}?",
        "Что умеет {{cybercolors}}?",
        "Как работает {{cybercolors}}?",
    ]
    assert all(
        literal not in " ".join(result.variations)
        for literal in ("КиберКолорс", "Cyber Colors", "Кибер Королс", "Modral")
    )

import asyncio
import json

import pytest
from pydantic import ValidationError

from api.models.bot_replies import ReplyConceptCreateModel, ReplyIntentCreateModel
from api.services.reply_variations import suggest_reply_variations
from src.db.models import Replies, ReplyConcept, Triggers
from src.modules.ai.models import AIResponse
from src.modules.on_message_processing.processing_methods import (
    normalize_and_stem_reply_text,
    normalize_reply_text,
)
from src.modules.on_message_processing.reply_matcher import compile_guild_reply_matcher


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
    assert payload.generated_variations == ["Tell me how it works"]


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
    reply = Replies(server_id=1, bot_reply="Role answer", created_by_id=2)
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
    assert matched.response_text == "Role answer"
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


def test_variation_generation_uses_structured_output_and_deduplicates():
    class FakeProvider:
        provider_name = "fake"

        async def complete(self, request):
            assert request.response_format is not None
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

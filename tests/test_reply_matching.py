import pytest

from src.modules.on_message_processing.processing_methods import reply_trigger_matches


@pytest.mark.parametrize(
    ("trigger", "message"),
    [
        ("Правило 1", "Правило 1\nПравило 1️⃣"),
        ("Правило 1️⃣", "Правило 1\nПравило 1️⃣"),
        ("ПРАВИЛО 2", "правило 2"),
        ("Всё хорошо", "ВСЕ ХОРОШО!"),
        ("<:aww_amy:778583409492230164>", "Вот <:aww_amy:778583409492230164>"),
    ],
)
def test_reply_triggers_use_the_same_normalization_as_messages(trigger, message):
    assert reply_trigger_matches(trigger, message)


@pytest.mark.parametrize(
    ("trigger", "message"),
    [
        ("Правило 1", "Правило 1️⃣"),
        ("Правило 1️⃣", "Правило 1"),
    ],
)
def test_keycap_variant_remains_distinct_from_plain_number_variant(trigger, message):
    assert not reply_trigger_matches(trigger, message)


def test_reply_trigger_does_not_match_a_longer_number():
    assert not reply_trigger_matches("Правило 1", "Правило 12")


def test_empty_normalized_trigger_never_matches():
    assert not reply_trigger_matches("!!!", "любое сообщение")

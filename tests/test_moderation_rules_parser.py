from api.services.moderation_rules_service import get_rule_parse_guide, parse_rules_from_text


def test_parse_rules_from_keycap_numbered_text():
    text = (
        "1️⃣ **No harassment.**\n"
        "Respect other members.\n\n"
        "2️⃣ **No NSFW content.**\n"
        "This includes nudity and pornographic content."
    )

    parsed = parse_rules_from_text(text)

    assert len(parsed) == 2
    assert parsed[0].code == "1"
    assert parsed[0].sort_order == 1
    assert "No harassment" in parsed[0].title
    assert "Respect other members" in (parsed[0].description or "")
    assert parsed[1].code == "2"
    assert parsed[1].sort_order == 2


def test_parse_guide_has_example_and_guidance():
    guide = get_rule_parse_guide()
    assert guide.title
    assert guide.guidance
    assert guide.example


def test_parse_bare_number_bold_rule_preserves_opening_markdown_until_normalized():
    text = (
        "6 **All channels must be used for their intended purpose**\n"
        "Check the channel description before sending a message."
    )

    parsed = parse_rules_from_text(text)

    assert len(parsed) == 1
    assert parsed[0].code == "6"
    assert parsed[0].marker == "6"
    assert parsed[0].title == "All channels must be used for their intended purpose"
    assert "**" not in (parsed[0].description or "")
    assert (parsed[0].description or "").startswith("All channels")

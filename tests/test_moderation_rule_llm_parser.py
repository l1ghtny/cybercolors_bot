from api.services.moderation_rule_llm_parser import parsed_rules_from_llm_json
from api.services.moderation_rules_service import _index_existing_rules
from src.db.models import ModerationRule


def test_parsed_rules_from_llm_json_preserves_markers_and_order():
    parsed = parsed_rules_from_llm_json(
        """
        {
          "rules": [
            {
              "marker": "2️⃣",
              "code": 2,
              "title": "No insults",
              "description": "No insults or harassment.",
              "sort_order": 2
            },
            {
              "marker": "<:rule_ten:123456789012345678>",
              "code": "10",
              "title": "Use channels correctly",
              "description": "Keep <:star:123> as written.",
              "sort_order": 10
            }
          ]
        }
        """
    )

    assert [item.code for item in parsed] == ["2", "10"]
    assert parsed[0].marker == "2️⃣"
    assert parsed[1].marker == "<:rule_ten:123456789012345678>"
    assert "<:star:123>" in (parsed[1].description or "")
    assert [item.sort_order for item in parsed] == [1, 2]


def test_parsed_rules_from_llm_json_rejects_invalid_payload():
    assert parsed_rules_from_llm_json("not json") == []
    assert parsed_rules_from_llm_json('{"items": []}') == []


def test_existing_rule_index_matches_by_code_marker_or_title():
    rule = ModerationRule(
        server_id=1,
        code="10",
        title="Use channels correctly",
        source_marker="🔟",
        sort_order=10,
    )

    indexed = _index_existing_rules([rule])

    assert indexed["10"] is rule
    assert indexed["🔟"] is rule
    assert indexed["use channels correctly"] is rule

from src.modules.discord_mentions import allowed_explicit_mentions, extract_explicit_mentions


def test_extract_explicit_mentions_deduplicates_native_tokens():
    assert extract_explicit_mentions(
        "<@42> <@!43> <@42> <@&84> <@&84> @everyone <#99>"
    ) == ((42, 43), (84,))


def test_extract_explicit_mentions_ignores_empty_or_invalid_tokens():
    assert extract_explicit_mentions(None) == ((), ())
    assert extract_explicit_mentions("<@abc> <@&> <@0> <@&0>") == ((), ())


def test_allowed_explicit_mentions_intersects_configuration_with_message():
    assert allowed_explicit_mentions(
        "<@42> <@43> <@&84>",
        allowed_user_ids=["42", "99"],
        allowed_role_ids=["84", "98"],
    ) == ((42,), (84,))

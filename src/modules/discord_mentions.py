import re


_USER_MENTION_RE = re.compile(r"<@!?(\d+)>")
_ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")


def extract_explicit_mentions(content: str | None) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Return explicitly formatted Discord user and role mentions in text order."""
    if not content:
        return (), ()

    user_ids = tuple(dict.fromkeys(
        mention_id
        for raw_id in _USER_MENTION_RE.findall(content)
        if (mention_id := int(raw_id)) > 0
    ))
    role_ids = tuple(dict.fromkeys(
        mention_id
        for raw_id in _ROLE_MENTION_RE.findall(content)
        if (mention_id := int(raw_id)) > 0
    ))
    return user_ids, role_ids


def allowed_explicit_mentions(
    content: str | None,
    *,
    allowed_user_ids: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
    allowed_role_ids: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Intersect an explicit notification allowlist with mentions in the message."""
    mentioned_user_ids, mentioned_role_ids = extract_explicit_mentions(content)
    allowed_users = {int(value) for value in allowed_user_ids if str(value).isdigit()}
    allowed_roles = {int(value) for value in allowed_role_ids if str(value).isdigit()}
    return (
        tuple(user_id for user_id in mentioned_user_ids if user_id in allowed_users),
        tuple(role_id for role_id in mentioned_role_ids if role_id in allowed_roles),
    )

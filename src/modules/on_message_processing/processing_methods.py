import re
import string

import demoji


def e_replace(string):
    string_new = string.replace('ё', 'е')
    return string_new


def em_replace(string):
    emoji = demoji.findall(string)
    for i in emoji:
        unicode = i.encode('unicode-escape').decode('ASCII')
        string = string.replace(i, unicode)
    return string


def normalize_reply_text(value: str) -> str:
    """Normalize configured reply triggers and incoming messages identically."""
    normalized = e_replace(em_replace(value.casefold()))
    return normalized.translate(str.maketrans('', '', string.punctuation))


def string_found(string1, string2):
    search = re.search(r"\b" + re.escape(string1) + r"\b", string2)
    if search:
        return True
    return False


def normalized_reply_trigger_matches(
    trigger_text_raw: str,
    normalized_message: str,
) -> bool:
    trigger_text = normalize_reply_text(trigger_text_raw)
    if not trigger_text:
        return False

    if trigger_text_raw.startswith('<'):
        return trigger_text in normalized_message
    return string_found(trigger_text, normalized_message)


def reply_trigger_matches(trigger_text: str, message_content: str) -> bool:
    """Return whether a configured trigger matches a Discord message."""
    normalized_message = normalize_reply_text(message_content)
    return normalized_reply_trigger_matches(trigger_text, normalized_message)

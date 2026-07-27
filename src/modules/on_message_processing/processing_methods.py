import re
import string
import unicodedata
from functools import lru_cache

import demoji
from pymorphy3 import MorphAnalyzer


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
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = re.sub(
        r"([0-9#*])\ufe0f?\u20e3",
        lambda match: f" keycap{ord(match.group(1)):x} ",
        normalized,
    )
    normalized = e_replace(em_replace(normalized))
    normalized = "".join(
        " " if unicodedata.category(character).startswith(("P", "Z")) else character
        for character in normalized
    )
    normalized = normalized.translate(str.maketrans({character: " " for character in string.punctuation}))
    return " ".join(normalized.split())


_RUSSIAN_VOWELS = "аеиоуыэюя"
_PERFECTIVE_GROUND = re.compile(r"(?:ив|ивши|ившись|ыв|ывши|ывшись)$")
_PERFECTIVE_GROUND_A = re.compile(r"(?<=[ая])(?:в|вши|вшись)$")
_REFLEXIVE = re.compile(r"(?:ся|сь)$")
_ADJECTIVE = re.compile(
    r"(?:ее|ие|ые|ое|ими|ыми|ей|ий|ый|ой|ем|им|ым|ом|его|ого|ему|ому|их|ых|ую|юю|ая|яя|ою|ею)$"
)
_PARTICIPLE = re.compile(r"(?:ем|нн|вш|ющ|щ)$")
_PARTICIPLE_A = re.compile(r"(?<=[ая])(?:ивш|ывш|ующ)$")
_VERB = re.compile(
    r"(?:ила|ыла|ена|ейте|уйте|ите|или|ыли|ей|уй|ил|ыл|им|ым|ен|ило|ыло|ено|ят|ует|уют|ит|ыт|ены|ить|ыть|ишь|ую|ю)$"
)
_VERB_A = re.compile(r"(?<=[ая])(?:ла|на|ете|йте|ли|л|ем|н|ло|но|ет|ны|ть|ешь|нно)$")
_NOUN = re.compile(
    r"(?:иями|ями|ами|ией|иям|ием|иях|ев|ов|ие|ье|еи|ии|ай|ей|ой|ий|й|иям|ям|ием|ем|ам|ом|о|у|ах|иях|ях|ы|ь|ию|ью|ю|ия|ья|я|а|евы|овы|ие|ьи|и|ей|ой|ий|ям|ем|ам|ом|о|у|ах|ях|ы|ь|ию|ью|ю|ия|ья|я|а)$"
)


def _russian_stem(word: str) -> str:
    """Small Snowball-style stemmer used only for deterministic reply matching."""
    if len(word) < 4 or not re.fullmatch(r"[а-я]+", word):
        return word
    rv_index = next((index + 1 for index, char in enumerate(word) if char in _RUSSIAN_VOWELS), len(word))
    prefix, rv = word[:rv_index], word[rv_index:]

    next_rv = _PERFECTIVE_GROUND.sub("", rv)
    if next_rv == rv:
        next_rv = _PERFECTIVE_GROUND_A.sub("", rv)
    if next_rv == rv:
        rv = _REFLEXIVE.sub("", rv)
        adjectival = _ADJECTIVE.sub("", rv)
        if adjectival != rv:
            rv = _PARTICIPLE.sub("", adjectival)
            rv = _PARTICIPLE_A.sub("", rv)
        else:
            verbal = _VERB.sub("", rv)
            rv = _VERB_A.sub("", rv) if verbal == rv else verbal
            if rv == next_rv or rv == _REFLEXIVE.sub("", next_rv):
                rv = _NOUN.sub("", rv)
    else:
        rv = next_rv

    rv = re.sub(r"и$", "", rv)
    stem = prefix + rv
    stem = re.sub(r"ость?$", "", stem)
    stem = re.sub(r"ейше?$", "", stem)
    stem = re.sub(r"нн$", "н", stem)
    stem = re.sub(r"ь$", "", stem)
    return stem


@lru_cache(maxsize=1)
def _russian_morphology() -> MorphAnalyzer:
    return MorphAnalyzer()


@lru_cache(maxsize=4096)
def russian_word_forms_matching_reply_stem(word: str) -> tuple[str, ...]:
    """Return dictionary word forms accepted by the live reply stemmer."""
    normalized = normalize_reply_text(word)
    if not re.fullmatch(r"[а-я]+", normalized) or len(normalized) < 4:
        return (normalized,) if normalized else ()

    parses = _russian_morphology().parse(normalized)
    if not parses or not parses[0].is_known:
        return (normalized,)

    expected_stem = _russian_stem(normalized)
    forms: list[str] = []
    seen: set[str] = set()
    for lexeme in parses[0].lexeme:
        candidate = normalize_reply_text(lexeme.word)
        if (
            candidate
            and candidate not in seen
            and _russian_stem(candidate) == expected_stem
        ):
            seen.add(candidate)
            forms.append(candidate)

    if normalized not in seen:
        forms.insert(0, normalized)
    else:
        forms.remove(normalized)
        forms.insert(0, normalized)
    return tuple(forms)


def normalize_and_stem_reply_text(value: str) -> str:
    normalized = normalize_reply_text(value)
    return " ".join(_russian_stem(token) for token in normalized.split())


def string_found(string1, string2):
    search = re.search(r"\b" + re.escape(string1) + r"\b", string2)
    if search:
        return True
    return False


def normalized_reply_trigger_matches(
    trigger_text_raw: str,
    normalized_message: str,
) -> bool:
    trigger_text = normalize_and_stem_reply_text(trigger_text_raw)
    if not trigger_text:
        return False

    normalized_message = normalize_and_stem_reply_text(normalized_message)

    if trigger_text_raw.startswith('<'):
        return trigger_text in normalized_message
    return string_found(trigger_text, normalized_message)


def reply_trigger_matches(trigger_text: str, message_content: str) -> bool:
    """Return whether a configured trigger matches a Discord message."""
    normalized_message = normalize_reply_text(message_content)
    return normalized_reply_trigger_matches(trigger_text, normalized_message)

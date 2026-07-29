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


def normalize_reply_surface_text(value: str) -> str:
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


# These are intentionally product-level language rules, not administrator data.
# Genuine server-specific synonyms still belong in reusable reply concepts.
_REPLY_LANGUAGE_VARIATION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("что", ("что", "што", "чо", "чё", "шо")),
    ("кто", ("кто", "хто")),
    (
        "зачем",
        ("зачем", "почему", "для чего", "нахрена", "нахрен", "нахера", "нахуя"),
    ),
    ("кого", ("кого", "каво", "ково")),
    ("когда", ("когда", "када")),
)

_REPLY_LANGUAGE_VARIANTS_BY_CANONICAL = {
    canonical: variants for canonical, variants in _REPLY_LANGUAGE_VARIATION_GROUPS
}
_REPLY_LANGUAGE_ALIAS_TOKENS = {
    tuple(normalize_reply_surface_text(variant).split()): (canonical,)
    for canonical, variants in _REPLY_LANGUAGE_VARIATION_GROUPS
    for variant in variants
}
_MAX_REPLY_LANGUAGE_ALIAS_TOKENS = max(
    (len(tokens) for tokens in _REPLY_LANGUAGE_ALIAS_TOKENS),
    default=1,
)


def normalize_reply_text(value: str) -> str:
    """Normalize triggers/messages and canonicalize built-in language variants."""
    tokens = normalize_reply_surface_text(value).split()
    canonical_tokens: list[str] = []
    index = 0
    while index < len(tokens):
        matched = False
        max_size = min(_MAX_REPLY_LANGUAGE_ALIAS_TOKENS, len(tokens) - index)
        for size in range(max_size, 0, -1):
            replacement = _REPLY_LANGUAGE_ALIAS_TOKENS.get(tuple(tokens[index:index + size]))
            if replacement is None:
                continue
            canonical_tokens.extend(replacement)
            index += size
            matched = True
            break
        if not matched:
            canonical_tokens.append(tokens[index])
            index += 1
    return " ".join(canonical_tokens)


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
    """Return language variants and dictionary forms accepted by live matching."""
    normalized = normalize_reply_text(word)
    if not normalized or " " in normalized:
        return (normalized,) if normalized else ()

    forms: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        if candidate and candidate not in seen:
            seen.add(candidate)
            forms.append(candidate)

    add(normalized)
    for variant in _REPLY_LANGUAGE_VARIANTS_BY_CANONICAL.get(normalized, ()):
        add(variant)

    if not re.fullmatch(r"[а-я]+", normalized):
        return tuple(forms)

    parses = _russian_morphology().parse(normalized)
    if not parses or not parses[0].is_known:
        return tuple(forms)

    # Pronouns such as "кто" and "кого" are distinct question meanings, while
    # nouns, adjectives, and verbs need case/gender/number coverage.
    inflectable_parts_of_speech = {
        "NOUN",
        "ADJF",
        "ADJS",
        "COMP",
        "VERB",
        "INFN",
        "PRTF",
        "PRTS",
        "GRND",
        "NUMR",
    }
    if parses[0].tag.POS not in inflectable_parts_of_speech:
        return tuple(forms)

    for lexeme in parses[0].lexeme:
        add(normalize_reply_surface_text(lexeme.word))
    return tuple(forms)


@lru_cache(maxsize=4096)
def russian_reply_token_stems(word: str) -> tuple[str, ...]:
    """Return every fast runtime stem compiled for a configured Russian word."""
    stems: list[str] = []
    seen: set[str] = set()
    for form in russian_word_forms_matching_reply_stem(word):
        normalized_form = normalize_reply_text(form)
        form_tokens = normalized_form.split()
        if len(form_tokens) != 1:
            continue
        stem = _russian_stem(form_tokens[0])
        if stem not in seen:
            seen.add(stem)
            stems.append(stem)
    return tuple(stems)


def normalize_and_stem_reply_text(value: str) -> str:
    normalized = normalize_reply_text(value)
    return " ".join(_russian_stem(token) for token in normalized.split())


def normalized_reply_trigger_matches(
    trigger_text_raw: str,
    normalized_message: str,
) -> bool:
    trigger_tokens = normalize_reply_text(trigger_text_raw).split()
    if not trigger_tokens:
        return False

    normalized_message = normalize_and_stem_reply_text(normalized_message)
    units: list[str] = []
    for token in trigger_tokens:
        stems = russian_reply_token_stems(token) or (_russian_stem(token),)
        escaped = [re.escape(stem) for stem in stems]
        units.append(escaped[0] if len(escaped) == 1 else "(?:" + "|".join(escaped) + ")")
    expression = r"(?<!\w)" + r"\s+".join(units) + r"(?!\w)"
    return re.search(expression, normalized_message, re.UNICODE) is not None


def reply_trigger_matches(trigger_text: str, message_content: str) -> bool:
    """Return whether a configured trigger matches a Discord message."""
    normalized_message = normalize_reply_text(message_content)
    return normalized_reply_trigger_matches(trigger_text, normalized_message)

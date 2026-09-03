"""Magic's noun and keyword vocabulary, loaded from data.

The legacy noun parser recognized four creature subtypes
(``KNOWN_CREATURE_SUBTYPES = ("wall", "elephant", "djinn", "efreet")``) and
silently discarded every other restriction word, so "destroy target creature
with flying" and "destroy target creature" compiled to the same instruction.
Scaling past a few hundred cards means the vocabulary has to be data: the
catalogs under ``data/vocabulary/`` are fetched by
``scripts/fetch_vocabulary.py`` and committed, so nothing here touches the
network.

Multiword types ("time lord", "serra angel") are indexed by first word so the
noun parser can try a longest match without scanning the whole catalog.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "vocabulary"


def _load(name: str) -> frozenset[str]:
    path = DATA_DIR / f"{name}.json"
    if not path.exists():  # pragma: no cover - guarded by test_grammar_vocabulary
        raise FileNotFoundError(
            f"vocabulary catalog {name!r} missing; run scripts/fetch_vocabulary.py"
        )
    return frozenset(json.loads(path.read_text(encoding="utf-8")))


CREATURE_TYPES: frozenset[str] = _load("creature_types")
LAND_TYPES: frozenset[str] = _load("land_types")
ARTIFACT_TYPES: frozenset[str] = _load("artifact_types")
ENCHANTMENT_TYPES: frozenset[str] = _load("enchantment_types")
PLANESWALKER_TYPES: frozenset[str] = _load("planeswalker_types")
SPELL_TYPES: frozenset[str] = _load("spell_types")
SUPERTYPES: frozenset[str] = _load("supertypes")

#: The supertypes a matcher can answer by reading a **type line** — which is all
#: of them but one. Scryfall reports "token" as a supertype because a token
#: object's printed line reads "Token Creature - Goblin"; this engine's
#: ``make_token_card`` prints no such word and answers "is this a token?" from
#: the permanent's identity instead (the ``nontoken`` key, CR 111.1). So a
#: type-line test for "token" would answer False for every token there is — a
#: restriction that silently matches nothing rather than one that matches too
#: much, which is the same bug wearing the other coat. Splitting the set here
#: rather than editing the fetched data keeps ``fetch_vocabulary.py`` free to
#: re-download it, and leaves "a token creature" to refuse loudly.
TYPE_LINE_SUPERTYPES: frozenset[str] = SUPERTYPES - {"token"}
CARD_TYPES: frozenset[str] = _load("card_types")
KEYWORD_ABILITIES: frozenset[str] = _load("keyword_abilities")
KEYWORD_ACTIONS: frozenset[str] = _load("keyword_actions")
ABILITY_WORDS: frozenset[str] = _load("ability_words")

ALL_SUBTYPES: frozenset[str] = (
    CREATURE_TYPES | LAND_TYPES | ARTIFACT_TYPES | ENCHANTMENT_TYPES
    | PLANESWALKER_TYPES | SPELL_TYPES
)

COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

NUMBER_WORDS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fifteen": 15, "twenty": 20,
}

#: The ordinals a printed "…the **first** <thing> that player <verb>s each
#: turn" clause names. Beside :data:`NUMBER_WORDS` rather than folded into it:
#: "two spells" is a count and "the second spell" is a position, and one table
#: answering both would let a production read a count where the card printed a
#: position.
ORDINAL_WORDS: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
}

# Keyword abilities the engine actually implements. A keyword outside this set
# still *parses* (it is in the Scryfall catalog) but lowering refuses it, which
# is the honest answer: the word is recognized, the behavior is not built.
IMPLEMENTED_KEYWORDS: frozenset[str] = frozenset({
    "flying", "first strike", "double strike", "trample", "vigilance", "haste",
    "defender", "reach", "banding", "protection", "landwalk", "swampwalk",
    "forestwalk", "islandwalk", "mountainwalk", "plainswalk", "desertwalk",
    "lifelink", "deathtouch", "indestructible", "flash", "menace", "hexproof",
    "prowess", "rampage",
    # CR 702.18: shroud. The behaviour was already the *first* question
    # `_can_be_targeted` asks and has been since before the registry existed —
    # seat-blind, as the rule requires (a shrouded permanent cannot be targeted
    # by its own controller either, which is what separates it from hexproof
    # one line up). What was missing was the word: outside this set the grammar
    # refuses every grant of it, so a card printing "has shroud" was
    # unsupported for a mechanic the engine enforces.
    "shroud",
    # CR 702.36: fear. The same shape as shroud two entries up — the behaviour
    # has been in the declare-blockers step since before the registry existed
    # (CR 702.36b's "can't be blocked except by artifact creatures and/or black
    # creatures", both halves read through the layers), with three CR-cited
    # tests behind it, and only the *word* was missing. Outside this set the
    # grammar refuses every grant of it, so "gains fear until end of turn" was
    # unsupported for a mechanic the engine enforces.
    "fear",
    # CR 702.22b's specialized banding. A **family** word like "protection" and
    # "landwalk" beside it: what a card prints is the word plus a quality
    # ("bands with other legendary creatures"), and the quality is payload read
    # by engine/banding.py. The registry lists abilities, so it lists this one
    # once — `keywords.keyword_ability_name` is what strips a printed quality
    # back to it, exactly as it strips protection's colour.
    "bands with other",
    # CR 702.25: flanking. Like rampage two entries up, the CR *defines* it as a
    # triggered ability rather than describing one, so the behaviour is a
    # compile-time rewrite (`engine/flanking.py`) and this set holds the word.
    # The word is not decoration for it: Telim'Tor buffs "attacking creatures
    # **with** flanking", Barbed Foliage takes it away and Agility grants it, so
    # every reader of the registry — the filter, the removal gate, the grant
    # gate — has a Mirage card behind it.
    "flanking",
    # CR 702.26: phasing. A static ability that modifies the untap step, so
    # unlike flanking and rampage above it the *word* is the whole of it —
    # `Game.resolve_phasing_for` reads it off layer 6 at each player's untap
    # step, which is what lets Teferi's Curse and Shimmer grant it through the
    # ordinary channels with nothing else to build.
    "phasing",
})


#: Keywords whose argument is a **number** (CR 702.23a's "Rampage N"), as
#: opposed to protection's quality or landwalk's land type. The set is here and
#: the number is not: which keywords take one is vocabulary, the value they take
#: is payload — a card printing "rampage 4" needs no code.
#:
#: A set rather than "consume any digit after any keyword", because a digit
#: sitting behind a keyword that does not take one belongs to whatever comes
#: next, and consuming it would be a silent misparse rather than a refusal.
NUMERIC_ARGUMENT_KEYWORDS: frozenset[str] = frozenset({"rampage"})


#: The keyword **families** a card can name wholesale: "loses all landwalk
#: abilities" (Hammerheim). CR 702.14a defines landwalk as a family of
#: "[type]walk" abilities rather than one ability, so a card that names the
#: family is naming every member of it — and the parser produces the **family
#: word**, not a member list.
#:
#: It used to produce the list, derived from :data:`IMPLEMENTED_KEYWORDS` so
#: that no second hand-written tuple could drift from the registry. The
#: derivation was honest and the premise was not: CR 702.14a builds a
#: landwalk's name out of a printed quality, so "snow forestwalk" is a member
#: no registry of *words* can contain, and Hammerheim left Rime Dryad's snow
#: forestwalk in place while reporting that it had removed it. An open family
#: is expanded where the permanent's abilities are known —
#: :func:`engine.keywords.expand_ability_removal` — exactly as
#: `engine/evasion_negation.py` answers the same sentence with the family word
#: and asks the enforcement site.
#:
#: The value is a tuple because the parser above returns a keyword *list*; a
#: family that named more than one word would list them here.
KEYWORD_FAMILIES: dict[str, tuple[str, ...]] = {
    "landwalk": ("landwalk",),
}


def _index_by_first_word(words: frozenset[str]) -> dict[str, tuple[tuple[str, ...], ...]]:
    """Map each first word to the multiword entries starting with it, longest
    first, so the noun parser can greedily match "time lord" before "time"."""
    index: dict[str, list[tuple[str, ...]]] = {}
    for entry in words:
        parts = tuple(entry.split())
        index.setdefault(parts[0], []).append(parts)
    return {
        head: tuple(sorted(entries, key=len, reverse=True))
        for head, entries in index.items()
    }


SUBTYPE_INDEX = _index_by_first_word(ALL_SUBTYPES)
KEYWORD_INDEX = _index_by_first_word(KEYWORD_ABILITIES)


@lru_cache(maxsize=None)
def manifest() -> dict:
    """Provenance of the committed catalogs (source, fetch date, counts)."""
    path = DATA_DIR / "manifest.json"
    if not path.exists():  # pragma: no cover
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def match_longest(
    words: tuple[str, ...], start: int, index: dict[str, tuple[tuple[str, ...], ...]]
) -> tuple[str, int] | None:
    """Greedily match the longest vocabulary entry in *index* at *words[start]*.

    Returns ``(matched_entry, words_consumed)`` or None.
    """
    if start >= len(words):
        return None
    for candidate in index.get(words[start], ()):
        end = start + len(candidate)
        if end <= len(words) and tuple(words[start:end]) == candidate:
            return " ".join(candidate), len(candidate)
    return None


#: Where a capital letter starts inside a type word. A space, a hyphen and a
#: period each begin a new one ("time lord", "assembly-worker", "b.o.b."); an
#: apostrophe does **not** ("urza's", "c'tan", "shi'ar"), which is the whole
#: reason this is a regex rather than ``str.title()`` — that spells the land
#: type "Urza'S".
_TYPE_WORD_CAPITALS = re.compile(r"(^|[\s\-.])([a-z])")


def display_type_word(word: str) -> str:
    """*word* spelled as a type line prints it.

    The catalogs are lowercase — Scryfall's own casing is not preserved by
    ``fetch_vocabulary.py`` and nothing in the engine needs it until a word has
    to be *shown*. That happens when an effect grants a type the printed line
    never carried (Demonic Embrace's Demon, Mishra's Factory's Assembly-Worker):
    the word has no printed spelling on that card to copy, so it is spelled
    here. A word the line already carries keeps its printed spelling instead —
    see ``layer_bridge.displayed_type_line``.
    """
    return _TYPE_WORD_CAPITALS.sub(
        lambda found: found.group(1) + found.group(2).upper(), word.lower()
    )


__all__ = [
    "ABILITY_WORDS", "ALL_SUBTYPES", "ARTIFACT_TYPES", "CARD_TYPES",
    "COLOR_WORDS", "CREATURE_TYPES", "ENCHANTMENT_TYPES", "IMPLEMENTED_KEYWORDS",
    "KEYWORD_ABILITIES", "KEYWORD_ACTIONS", "KEYWORD_FAMILIES", "KEYWORD_INDEX",
    "LAND_TYPES",
    "NUMBER_WORDS", "NUMERIC_ARGUMENT_KEYWORDS", "ORDINAL_WORDS",
    "PLANESWALKER_TYPES", "SPELL_TYPES",
    "SUBTYPE_INDEX",
    "SUPERTYPES", "TYPE_LINE_SUPERTYPES", "display_type_word", "manifest",
    "match_longest",
]


#: Head nouns that name an object without naming a card type — "permanent",
#: "card", "spell", "source", "target". Here rather than in `nouns` because the
#: singularizer below needs them and both are word lookup, not parsing: a module
#: *under* `nouns` in the layer order (`abilities`) can reach them only here.
GENERIC_NOUNS = frozenset({
    "permanent", "permanents", "card", "cards", "spell", "spells",
    "source", "sources", "target", "targets",
})


def singular(word: str) -> str:
    """Best-effort singularization for vocabulary lookup. Only trims when the
    trimmed form is itself known, so "wall"/"walls" both resolve but a real
    word ending in s is left alone."""
    if word.endswith("s"):
        stem = word[:-1]
        if stem in CARD_TYPES or stem in ALL_SUBTYPES or stem in GENERIC_NOUNS:
            return stem
        if word.endswith("es"):
            stem2 = word[:-2]
            if stem2 in CARD_TYPES or stem2 in ALL_SUBTYPES:
                return stem2
    return word

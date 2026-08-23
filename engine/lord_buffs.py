"""Continuous "other creatures get …" static abilities (CR 613, layers 6 and 7c).

The lord anthem — *Other Goblins get +1/+1 and have mountainwalk*, *Black
creatures get +1/+1*, *Attacking creatures you control get +1/+0* — is one
template with five independent parameters:

===========================  ==================================================
who is buffed                colour, creature subtype, "other" (CR 613 does not
                             exempt the source unless the card says so),
                             controller scope, and a state qualifier
                             (attacking / blocking / tapped / untapped)
what they get                a power/toughness delta, keyword abilities, and —
                             for Zombie Master's shape — a granted activated
                             ability
===========================  ==================================================

Before this module there was no table. The continuous consumer
(``_recalculate_lord_buffs``) read the **colour and the controller** off a bare
``static_line`` and nothing else, with a second regex re-reading the same
sentence for the subtype lords. Three consequences, all of them the
gate/dispatch split this codebase keeps finding:

* The support gate admitted every line beginning ``"other "`` — a prefix, not a
  template. "Other Goblins glimmer uncontrollably." compiled as supported.
* The two *qualified* anthems could not be expressed at all, so each got its own
  instruction kind whose parse rule spelled out one card's numbers
  (``"attacking creatures you control get +1/+0"``,
  ``"untapped creatures you control get +0/+2"``). A card printed +2/+0 was
  unsupported; a card printed "attacking creatures **an opponent controls**"
  would have been silently mis-applied.
* Nothing could delegate a claim here, so the grammar refused these lines by
  name rather than lowering them.

Everything below is derived from the printed sentence. A differently-named card
with the same template needs no code at all — which is the property
``tests/rules/test_lord_buffs.py`` pins with invented cards, because a test
naming only the real card would have passed against the broken version.

**Duration is the line between the two readings of a board-wide buff.**
Nothing here matches a clause carrying one: "Attacking creatures get +2/+0
*until end of turn*" (Army of Allah) is a one-shot spell effect that locks its
set in at resolution (CR 611.2c) and stays on ``buff_creatures_global``. A
static ability has no duration and is re-derived on every recompute (CR 611.3a).
Those are different rules and they keep different instruction kinds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

# The instruction kind a derived lord buff compiles to. One kind for the whole
# family: the parameters are payload, so a new printing of the template adds no
# dispatch.
LORD_BUFF_KIND = "lord_buff"

# State qualifiers, mapped to the ``ast.ObjectFilter`` field and value that
# express them. The grammar reads this to rebuild the filter it started from and
# compare for equality, so the qualifier vocabulary has exactly one definition
# and a qualifier added here cannot be silently dropped by a lowering written
# before it existed.
QUALIFIER_FIELDS: dict[str, tuple[str, bool]] = {
    "attacking": ("attacking", True),
    "blocking": ("blocking", True),
    "tapped": ("tapped", True),
    "untapped": ("tapped", False),
}

# Activated abilities a lord can grant in quotes, mapped to the metadata flag
# that arms them. Keyed by the **whole** quoted text including its cost: the
# reader (mixins/stack/activation.py) charges {B} and nothing else, so a
# differently-costed printing of the same ability is genuinely not implemented
# and must fail loud rather than be granted for free.
GRANTED_ACTIVATED_ABILITIES: dict[str, str] = {
    "{b}: regenerate this permanent.": "granted_regen_ability",
}

# Conditions a lord buff may hang on, mapped to the predicate that evaluates
# them (resolved by the consumer, which is the only thing holding a game).
# Jihad is the one card in the pool with one; an unrecognized "as long as …"
# makes the whole line refuse rather than dropping the condition, which would
# turn a conditional anthem into an unconditional one.
CONDITIONS: dict[str, str] = {
    "as long as the chosen player controls a nontoken permanent of the chosen color":
        "chosen_color_permanent",
}

_QUALIFIER_WORDS = tuple(QUALIFIER_FIELDS)


# Magic's noun and keyword catalogs are data (``data/vocabulary/``), read
# through the grammar's loader so there is one reader of those files. They are
# fetched lazily because the grammar package imports *this* module — the
# derivation belongs to the engine, and the grammar delegates to it rather than
# the other way round.
@lru_cache(maxsize=1)
def _vocabulary():
    from .grammar import vocabulary

    return vocabulary


def grantable_keywords() -> frozenset[str]:
    """Keyword abilities a lord may grant, at CR 613 layer 6.

    "protection" and "landwalk" are category words rather than abilities —
    protection has its own metadata channel with its own checks, and a bare
    "landwalk" names no land type — so claiming either here would say layer 6
    carries something it does not.
    """
    return _vocabulary().IMPLEMENTED_KEYWORDS - {"protection", "landwalk"}


@dataclass(frozen=True)
class LordBuffFilter:
    """Which creatures a lord buff reaches."""

    colors: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    # "you" scopes the anthem to its controller ("creatures you control");
    # None means every player's creatures (Bad Moon, Crusade).
    controller: str | None = None
    # "Other Goblins" — CR 613 applies a static ability to its own source unless
    # the card excludes it, so this is a field rather than an assumption.
    other_than_source: bool = False
    # A state the buffed creature must currently be in. Evaluated when P/T is
    # *read*, not when the board is recomputed — a creature that taps between
    # recomputes must lose an untapped-only bonus immediately (CR 611.3a).
    qualifier: str | None = None
    # "…with a +1/+1 counter on it" (Pridemalkin). A restriction on the buffed
    # set, read off the ``plus_counters`` record rather than the P/T bonus —
    # the same distinction ``permanent_matches_filter`` makes, and for the same
    # reason: a Giant Growth writes power_bonus and places no counter.
    with_plus1_counter: bool = False


@dataclass(frozen=True)
class LordBuff:
    """What a lord buff gives, and to whom."""

    filter: LordBuffFilter = field(default_factory=LordBuffFilter)
    power: int = 0
    toughness: int = 0
    keywords: tuple[str, ...] = ()
    # "…and have **protection from Dogs**" (Feline Sovereign). Its own field
    # rather than a keyword, because "protection" is not one: it names a
    # *quality* and is read from its own channel, which is exactly why
    # `grantable_keywords` excludes the word.
    protection_from: tuple[str, ...] = ()
    # A quoted activated ability the lord grants (Zombie Master), as a key into
    # GRANTED_ACTIVATED_ABILITIES.
    granted_ability: str | None = None
    # A key into CONDITIONS: the buff applies only while it holds.
    condition: str | None = None


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

# "get +1/+1" / "gets +0/+2" / "get -1/-1" (Kaervek, the Spiteful). Both persons
# are printed, because the subject may be a plural noun phrase or a subtype name
# that reads as singular; both signs, because a debuff is the same layer-7c
# contribution with a negative delta and ``int()`` reads the sign as printed.
_PT_RE = re.compile(r"^gets? (?P<power>[+-]\d+)/(?P<toughness>[+-]\d+)$")

_PT_AND_KEYWORD_RE = re.compile(
    r"^gets? (?P<power>[+-]\d+)/(?P<toughness>[+-]\d+) and ha(?:ve|s) (?P<keywords>.+)$"
)

_KEYWORD_RE = re.compile(r"^ha(?:ve|s) (?P<keywords>.+)$")

# A duration ends the static reading: see the module docstring.
_DURATIONS = ("until end of turn", "until end of combat", "this turn", "until your next turn")


def _split_condition(line: str) -> tuple[str, str | None] | None:
    """``(clause, condition key)``, or None when an unmodelled "as long as" is
    present. A condition that is recognized but not implemented has to take the
    whole line down: dropping it would make a conditional anthem permanent."""
    index = line.find(" as long as ")
    if index < 0:
        return line, None
    condition = CONDITIONS.get(line[index + 1:])
    if condition is None:
        return None
    return line[:index], condition


def _parse_keywords(text: str) -> tuple[str, ...] | None:
    """The keyword abilities *text* names ("mountainwalk", "flying and trample")."""
    grantable = grantable_keywords()
    words = [part.strip() for part in re.split(r",| and ", text) if part.strip()]
    if not words or any(word not in grantable for word in words):
        return None
    return tuple(words)


_PROTECTION_FROM_RE = re.compile(r"^protection from (?P<quality>.+)$")


def _split_protection(text: str) -> tuple[str, tuple[str, ...]]:
    """*text* with any "protection from X" clauses lifted out.

    Returns the remaining keyword text and the qualities. Split rather than
    parsed together because they end up in different places: a keyword goes into
    layer 6 and protection into its own channel, and a word in the wrong one is
    a grant nothing reads.
    """
    kept: list[str] = []
    qualities: list[str] = []
    for part in re.split(r",| and ", text):
        part = part.strip()
        if not part:
            continue
        match = _PROTECTION_FROM_RE.match(part)
        if match is not None:
            qualities.append(match.group("quality").strip())
        else:
            kept.append(part)
    return " and ".join(kept), tuple(qualities)


def _parse_subject(words: list[str]) -> LordBuffFilter | None:
    """The noun phrase naming the buffed creatures, or None if unrecognized.

    Consumes strictly left to right in the order the templates print, and every
    word must be accounted for — a leftover adjective means a restriction the
    consumer would drop, so the line refuses instead.
    """
    index = 0
    other = False
    qualifier: str | None = None
    colors: list[str] = []
    subtypes: list[str] = []
    with_plus1_counter = False

    # "Each creature you control…" / "All creatures…": a distributive article
    # naming exactly the set an unqualified anthem already reaches, so it is
    # consumed and contributes nothing. Not interchangeable with "other",
    # which *excludes* the source — hence separate words rather than one list.
    if index < len(words) and words[index] in ("each", "all"):
        index += 1
    if index < len(words) and words[index] == "other":
        other = True
        index += 1
    if index < len(words) and words[index] in _QUALIFIER_WORDS:
        qualifier = words[index]
        index += 1
    color_words = _vocabulary().COLOR_WORDS
    if index < len(words) and words[index] in color_words:
        colors.append(color_words[words[index]])
        index += 1
    if index < len(words):
        subtype = _creature_subtype(words[index])
        if subtype is not None:
            subtypes.append(subtype)
            index += 1
    # The head noun. Optional only when a subtype already supplied one
    # ("Other Goblins"); "Other Zombie creatures" spells it out.
    if index < len(words) and words[index] in ("creature", "creatures"):
        index += 1
    elif not subtypes:
        return None

    controller: str | None = None
    if words[index:index + 2] == ["you", "control"]:
        controller = "you"
        index += 2
    # "Creatures **your opponents control** get -1/-0" (Waker of Waves) — the
    # debuff's mirror of "you control", and a scope the consumer has to know
    # about explicitly: read as "every player" it would shrink the source's
    # own creatures too.
    elif words[index:index + 3] == ["your", "opponents", "control"]:
        controller = "opponent"
        index += 3

    # "…with a +1/+1 counter on it" (Pridemalkin). Spelled out in full so a
    # differently-worded restriction ("with a -1/-1 counter", "with two or
    # more counters") leaves words unconsumed and refuses the line rather
    # than being read as this one.
    if words[index:index + 6] == ["with", "a", "+1/+1", "counter", "on", "it"]:
        with_plus1_counter = True
        index += 6

    if index != len(words):
        return None
    return LordBuffFilter(
        colors=tuple(colors),
        subtypes=tuple(subtypes),
        controller=controller,
        other_than_source=other,
        qualifier=qualifier,
        with_plus1_counter=with_plus1_counter,
    )


def _creature_subtype(word: str) -> str | None:
    """The creature type *word* names, however it was pluralised.

    The catalog (``data/vocabulary/creature_types.json``) stores singulars, and
    some types are their own plural (Merfolk, Djinn), so every candidate stem is
    tried *against the catalog* rather than a shape being assumed. The "-ves"
    forms are here because Magic prints several of them — Elves, Dwarves,
    Wolves — and a trailing-"s" rule alone turns "elves" into "elve".
    """
    creature_types = _vocabulary().CREATURE_TYPES
    candidates = [word, word[:-1], word[:-2]]
    if word.endswith("ves"):
        candidates += [word[:-3] + "f", word[:-3] + "fe"]
    for candidate in candidates:
        if candidate and candidate in creature_types:
            return candidate
    return None


def lord_buff_for(normalized_line: str) -> LordBuff | None:
    """The continuous buff *normalized_line* grants to other creatures, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``).
    """
    line = normalized_line.strip().strip(".").strip()
    if not line or any(duration in line for duration in _DURATIONS):
        return None

    split = _split_condition(line)
    if split is None:
        return None
    clause, condition = split

    # The verb splits the sentence: everything left of it is the subject.
    match = re.search(r"\b(gets?|ha(?:ve|s))\b", clause)
    if match is None or match.start() == 0:
        return None
    subject = _parse_subject(clause[:match.start()].split())
    if subject is None:
        return None
    effect = clause[match.start():].strip()

    keywords: tuple[str, ...] = ()
    protection_from: tuple[str, ...] = ()
    granted_ability: str | None = None
    power = toughness = 0

    quoted = re.match(r'^ha(?:ve|s) "(?P<ability>.+)"$', effect)
    if quoted is not None:
        ability = quoted.group("ability").strip()
        if ability not in GRANTED_ACTIVATED_ABILITIES:
            return None
        granted_ability = ability
    elif (both := _PT_AND_KEYWORD_RE.match(effect)) is not None:
        power, toughness = int(both.group("power")), int(both.group("toughness"))
        rest, protection_from = _split_protection(both.group("keywords"))
        found = _parse_keywords(rest) if rest else ()
        if found is None:
            return None
        keywords = found
    elif (pt := _PT_RE.match(effect)) is not None:
        power, toughness = int(pt.group("power")), int(pt.group("toughness"))
    elif (kw := _KEYWORD_RE.match(effect)) is not None:
        rest, protection_from = _split_protection(kw.group("keywords"))
        found = _parse_keywords(rest) if rest else ()
        if found is None:
            return None
        keywords = found
    else:
        return None

    return LordBuff(
        subject, power, toughness, keywords, protection_from, granted_ability,
        condition,
    )


# ---------------------------------------------------------------------------
# Instruction payloads
# ---------------------------------------------------------------------------

def lord_buff_payload(buff: LordBuff) -> dict[str, object]:
    """*buff* as an ``OracleInstruction`` payload, emitting only what is set."""
    payload: dict[str, object] = {"power": buff.power, "toughness": buff.toughness}
    if buff.filter.colors:
        payload["colors"] = list(buff.filter.colors)
    if buff.filter.subtypes:
        payload["subtypes"] = list(buff.filter.subtypes)
    if buff.filter.controller:
        payload["controller"] = buff.filter.controller
    if buff.filter.other_than_source:
        payload["other"] = True
    if buff.filter.qualifier:
        payload["while"] = buff.filter.qualifier
    if buff.filter.with_plus1_counter:
        payload["with_plus1_counter"] = True
    if buff.keywords:
        payload["keywords"] = list(buff.keywords)
    if buff.protection_from:
        payload["protection_from"] = list(buff.protection_from)
    if buff.granted_ability:
        payload["granted_ability"] = buff.granted_ability
    if buff.condition:
        payload["condition"] = buff.condition
    return payload


def lord_buff_from_payload(payload: dict) -> LordBuff:
    """Rebuild the derived buff a ``lord_buff`` instruction carries."""
    return LordBuff(
        filter=LordBuffFilter(
            colors=tuple(payload.get("colors") or ()),
            subtypes=tuple(payload.get("subtypes") or ()),
            controller=payload.get("controller"),
            other_than_source=bool(payload.get("other")),
            qualifier=payload.get("while"),
            with_plus1_counter=bool(payload.get("with_plus1_counter")),
        ),
        power=int(payload.get("power", 0)),
        toughness=int(payload.get("toughness", 0)),
        keywords=tuple(payload.get("keywords") or ()),
        protection_from=tuple(payload.get("protection_from") or ()),
        granted_ability=payload.get("granted_ability"),
        condition=payload.get("condition"),
    )


__all__ = [
    "CONDITIONS", "GRANTED_ACTIVATED_ABILITIES", "LORD_BUFF_KIND", "LordBuff",
    "LordBuffFilter", "QUALIFIER_FIELDS", "grantable_keywords", "lord_buff_for",
    "lord_buff_from_payload", "lord_buff_payload",
]

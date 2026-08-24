"""Text-keyed combat restrictions on a creature (CR 506, 509).

"This creature can't attack unless defending player controls an Island",
"attacks each combat if able", "can't be blocked by Walls" — printed templates,
not card quirks. They are derived from oracle text here rather than listed, so a
card printed with one of these wordings needs no registration.

These used to be an ``elif`` chain of **exact string equality** inside
``engine/oracle.py``. That chain hardcoded *Island*, so a creature printed
"unless defending player controls a Mountain" fell through to a bare
``static_line``: the card reported `supported` and then attacked freely, with
the restriction silently absent. The land type is data, and is carried in the
payload.

Each entry names the code that enforces it, because a restriction recognized
here but dispatched nowhere is worse than one that fails to parse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .grammar.vocabulary import COLOR_WORDS, CREATURE_TYPES, IMPLEMENTED_KEYWORDS

# Basic land types a "controls a <type>" clause can name. Restricted to the five
# basics deliberately: the enforcing check in declare_attackers_step scopes its
# search to lands, and a nonbasic type would need the same scoping decided
# per card.
_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")

# Colour words a blocker narrowing can name, as one alternation. Read from the
# grammar's vocabulary rather than spelled out, so this file and the parser
# cannot come to disagree about what a colour word is.
_COLOR_WORD = "|".join(sorted(COLOR_WORDS))

# Printed number words a threshold can be written with. Shared with nothing on
# purpose: the compiler's own `_NUMBER_WORDS` covers trigger counts and is a
# different table for a different clause; what they have in common is English,
# not a rule.
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


@dataclass(frozen=True)
class CombatRestriction:
    """An instruction kind the combat steps dispatch on, plus its data."""

    kind: str
    payload: dict[str, object] = field(default_factory=dict)


# (pattern, kind) — enforced by:
#   cant_attack_without_land_type   phases/declare_attackers_step.can_attack
#   cant_attack_without_controlled_count  phases/declare_attackers_step.can_attack
#   cant_attack                     phases/declare_attackers_step.can_attack
#   controlled_creatures_cant_attack  phases/declare_attackers_step.can_attack
#   cant_block                      phases/declare_blockers_step
#   must_attack_each_combat         phases/declare_attackers_step._must_attack_if_able
#   cant_be_blocked_by              phases/declare_blockers_step
#   cant_be_blocked_except_by       phases/declare_blockers_step
#   cant_block_power_n_or_greater   phases/declare_blockers_step
#   can_block_only_with_keyword     phases/declare_blockers_step
#   must_be_blocked                 phases/declare_blockers_step
#   must_be_blocked_by_all_able     phases/declare_blockers_step
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            rf"^this creature can't attack unless defending player controls "
            rf"an? (?P<land_type>{'|'.join(_LAND_TYPES)})$"
        ),
        "cant_attack_without_land_type",
    ),
    # "…unless **you** control four or more artifacts" (Gadrak). The count and
    # the type are payload for the reason the land type above is: a card printed
    # with any other number or type is the same restriction, and baking either
    # into the kind made every variation a new kind, a new handler branch and a
    # new gate entry.
    (
        re.compile(
            r"^this creature can't attack unless you control "
            r"(?P<count>\w+) or more (?P<controlled_type>[a-z]+)s$"
        ),
        "cant_attack_without_controlled_count",
    ),
    (re.compile(r"^this creature can't attack$"), "cant_attack"),
    (
        # "Except for creatures named Akron Legionnaire and artifact creatures,
        # creatures you control can't attack." A restriction printed on one
        # permanent that reaches every creature its controller has, so it is
        # enforced by a board scan in `can_attack` rather than read off the
        # attacker's own program. The exception list is payload — a union of
        # noun-phrase filters, exactly the shape the "except by" blocker
        # whitelist carries — because a card printed with any other exceptions
        # is the same restriction. Parsed by `_blocker_union`, and a phrase it
        # cannot read refuses the line: an unreadable *exception* would make
        # the restriction reach creatures the card exempts, which for a
        # restriction is the direction that silently forbids a legal attack.
        re.compile(
            r"^except for (?P<attack_exceptions>.+), "
            r"creatures you control can't attack$"
        ),
        "controlled_creatures_cant_attack",
    ),
    # "This **token** can't block" (the Pirate Pursued Whale makes). A token is
    # a creature and "this token" is the same self-reference "this creature" is
    # — the word differs only because the card printing it is a token. Both
    # spellings, rather than normalizing one to the other, because the normalizer
    # would have to know which cards are tokens.
    (re.compile(r"^this (?:creature|token) can't block$"), "cant_block"),
    (re.compile(r"^this creature attacks each combat if able$"), "must_attack_each_combat"),
    # "…can't be blocked by **Walls**" (Invisibility's mirror, Ali Baba's
    # targets) and "…can't be blocked by **artifact creatures**" (Argothian
    # Pixies, Artifact Ward). One restriction: what differs is the noun phrase,
    # which is payload for the same reason the land type and the power
    # threshold in this file are. Two rows because a subtype and a card type
    # are different captures, not because they are different rules — both
    # produce `cant_be_blocked_by` and one enforcement site asks
    # `subject_matches` about the blocker.
    (
        re.compile(r"^this creature can't be blocked by (?P<blocker_subtype>[a-z]+)s$"),
        "cant_be_blocked_by",
    ),
    (
        re.compile(
            r"^this creature can't be blocked by "
            r"(?P<blocker_type>artifact|enchantment|land) creatures$"
        ),
        "cant_be_blocked_by",
    ),
    (
        # "…can't be blocked by **red** creatures" (Elder Spawn). A colour, and
        # payload for the reason the subtype above is: the restriction is the
        # same sentence with a different word in it.
        re.compile(
            rf"^this creature can't be blocked by (?P<blocker_color>{_COLOR_WORD}) creatures$"
        ),
        "cant_be_blocked_by",
    ),
    (
        # "…can't be blocked by creatures with power 3 or greater" (Amrou
        # Kithkin). The mirror of `cant_block_power_n_or_greater` below, which
        # reads the same threshold off the *blocker's* text instead — one says
        # "nothing that big may block me" and the other "I may not block
        # anything that big", and they are different cards.
        re.compile(
            r"^this creature can't be blocked by creatures with power "
            r"(?P<blocker_power>\d+) or greater$"
        ),
        "cant_be_blocked_by",
    ),
    (
        # "…can't be blocked **except by** Walls and/or creatures with flying"
        # (Elven Riders, Evil Eye of Orms-by-Gore). The inverse of the rows
        # above: those name what may not block, this names the only things that
        # may, and a blocker matching *any* member of the union is legal.
        #
        # Its own kind rather than a negated `cant_be_blocked_by`, because the
        # two differ in what they say about everything unnamed — "can't be
        # blocked by Walls" lets the rest of the board through, "except by
        # Walls" lets none of it through.
        re.compile(r"^this creature can't be blocked except by (?P<allowed>.+)$"),
        "cant_be_blocked_except_by",
    ),
    # A blocking *requirement* rather than a restriction (CR 509.1c), and
    # weaker than Lure's: **one** able creature must block it, not every
    # able creature. The two are enforced a dozen lines apart in the
    # blockers step and must not be folded together — "all able" on a card
    # printed "must be blocked" would forbid the defender keeping a blocker
    # back, which is a legal declaration.
    (re.compile(r"^this creature must be blocked if able$"), "must_be_blocked"),
    (
        # "All Walls able to block this creature do so." (Marble Priest.) Lure's
        # requirement (CR 509.1c) narrowed to a printed noun, and printed on the
        # creature itself rather than on an Aura — so it is a template here
        # beside the others rather than a second copy of the Aura reader. The
        # noun is payload for the reason every noun in this file is: a card
        # printed "All Zombies able to block…" is the same requirement.
        re.compile(
            rf"^all (?P<blocker_subtype>{'|'.join(sorted(CREATURE_TYPES))})s able to "
            r"block this creature do so$"
        ),
        "must_be_blocked_by_all_able",
    ),
    (
        # The unnarrowed form on a creature's own text, for the same reason.
        re.compile(r"^all creatures able to block this creature do so$"),
        "must_be_blocked_by_all_able",
    ),
    (
        # The threshold is data for the same reason the land type is: "power 4 or
        # greater" is the same restriction Ironclaw Orcs has, and baking 2 into
        # the instruction kind made every other number a new kind, a new handler
        # branch, and a new gate entry.
        re.compile(
            r"^this creature can't block creatures with power (?P<power>\d+) or greater$"
        ),
        "cant_block_power_n_or_greater",
    ),
    (
        # "This creature can block only creatures with flying." (Shacklegeist.)
        # The mirror of the restrictions above: those name what may *not* be
        # blocked, this names the only thing that may. The keyword is payload for
        # the reason the threshold beside it is — a card printed with any other
        # evasion word is the same restriction.
        re.compile(
            r"^this creature can block only creatures with (?P<required_keyword>[a-z]+)$"
        ),
        "can_block_only_with_keyword",
    ),
)


def combat_restriction_for(
    normalized_line: str, card_name: str | None = None
) -> CombatRestriction | None:
    """The combat restriction *normalized_line* imposes, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``), which
    is what the compiler holds at the point it needs this — usually with the
    card's self-references collapsed to "this creature"
    (``oracle._restriction_line``). *card_name* is what that collapse erased:
    "creatures named **this creature**" (Akron Legionnaire's exception names
    the card itself) is resolved back to the printed name here, because the
    filter matches by *name*, never by identity — a second Akron Legionnaire
    and a token wearing the name are both excepted. A caller with no name to
    give gets a refusal for that phrase, never a filter that matches nothing.
    """
    for pattern, kind in _PATTERNS:
        match = pattern.match(normalized_line)
        if match is None:
            continue
        # Numeric captures reach handlers as ints: a payload whose type depends
        # on which regex matched is how a comparison silently becomes a string
        # compare. A printed number **word** is read here too — the regex only
        # delimits it, the way it delimits a noun phrase everywhere else — and a
        # word with no number behind it refuses the whole line rather than
        # reaching a comparison as a string, where it would compare unequal to
        # every count and quietly stop the creature attacking at all.
        payload = {}
        for key, value in match.groupdict().items():
            if value is not None and value.isdigit():
                payload[key] = int(value)
                continue
            if key == "count" and value is not None:
                number = _NUMBER_WORDS.get(value)
                if number is None:
                    return None
                payload[key] = number
                continue
            payload[key] = value
        # A captured subtype must actually be one. The blocker pattern above
        # reads any bare plural noun ("by walls"), which is what keeps it from
        # needing a 350-entry alternation — but a word the vocabulary has never
        # heard of would produce a filter matching nothing, the restriction
        # would go inert, and the creature would be blockable by anything. That
        # is the widening direction, so the line refuses instead and its card is
        # reported unsupported naming the clause.
        subtype = payload.get("blocker_subtype")
        if subtype is not None and subtype not in CREATURE_TYPES:
            return None
        # A captured colour reaches the payload as its **symbol**, converted
        # here for the reason a captured number is converted to an int here: a
        # payload whose shape depends on which regex matched is how a filter
        # silently stops matching. Every other reader of `color_filter` in this
        # engine takes a symbol.
        colour = payload.get("blocker_color")
        if colour is not None:
            payload["blocker_color"] = COLOR_WORDS[colour]
        # "…except by Walls and/or creatures with flying". The union is parsed
        # **here**, and a phrase this cannot read refuses the line — the regex
        # above ends in `.+`, so admitting the match and leaving the tail to the
        # enforcement site would be a restriction the gate accepts and nobody
        # applies. That is the widening direction: an evasion ability nothing
        # enforces makes the creature blockable by everything.
        allowed = payload.pop("allowed", None)
        if allowed is not None:
            filters = _blocker_union(allowed)
            if filters is None:
                return None
            payload["allowed_blockers"] = filters
        # "Except for <union>, creatures you control can't attack." The union
        # is parsed here for the reason "except by" is: the regex ends in `.+`,
        # and admitting the match while a member went unread would be an
        # exception nothing honours — a creature the card exempts refused its
        # attack, silently.
        exceptions = payload.pop("attack_exceptions", None)
        if exceptions is not None:
            filters = _blocker_union(exceptions, card_name)
            if filters is None:
                return None
            payload["exceptions"] = filters
        return CombatRestriction(kind, payload)
    return None


#: One member of an "except by" union, as the subject-filter payload that tests
#: it. Each entry is a whole printed noun phrase rather than a word, because
#: "creatures with flying" and "artifact creatures" are two words doing two
#: different jobs and splitting them would need the noun parser this file
#: deliberately does not have.
def _blocker_union(phrase: str, card_name: str | None = None) -> list[dict] | None:
    """The filters a noun-phrase union names, or None.

    Two rows carry one: the blocker whitelist ("can't be blocked except by
    Walls and/or creatures with flying") and the attack-exception list
    ("Except for creatures named Akron Legionnaire and artifact creatures,
    …"). One parser, because the members are the same printed vocabulary and
    a phrase readable in one union and not the other would be a fork nobody
    could find.

    None means "this file does not read that phrase", which keeps the card
    unsupported with the clause named. Returning a partial union instead would
    be an evasion ability that lets through more than the card allows — or an
    exception list that exempts fewer creatures than the card prints.
    """
    filters: list[dict] = []
    for part in re.split(r"\s*(?:and/or|and|or)\s+", phrase.strip()):
        part = part.strip()
        if not part:
            continue
        described = _blocker_noun(part, card_name)
        if described is None:
            return None
        filters.append(described)
    return filters or None


def _blocker_noun(part: str, card_name: str | None = None) -> dict | None:
    """One member of the union, as a subject-filter payload."""
    named = re.fullmatch(r"creatures named (.+)", part)
    if named is not None:
        # "creatures named Kobolds of Kher Keep" — the name is data, matched
        # through `name_key` by the subject matcher, so there is nothing to
        # validate it against: a token's name (Wolves of the Hunt) is a name no
        # card file lists. "this creature" is what `_restriction_line` collapsed
        # the card's own name to; only the caller knows what it was, and a
        # caller that cannot say refuses the phrase rather than carrying a
        # filter that matches nothing.
        name = named.group(1).strip()
        if name == "this creature":
            if not card_name:
                return None
            name = card_name
        return {"type_filter": "creature", "named": name}
    keyword = re.fullmatch(r"creatures with ([a-z ]+)", part)
    if keyword is not None:
        # The word has to be a keyword the engine implements, checked here for
        # the reason the subtype is checked in `combat_restriction_for`: the
        # matcher would answer "no permanent has that" for anything else, and a
        # *whitelist* whose members match nothing is a creature that cannot be
        # blocked at all. Loud refusal instead.
        word = keyword.group(1).strip()
        if word not in IMPLEMENTED_KEYWORDS:
            return None
        return {"type_filter": "creature", "with_keywords": [word]}
    colored = re.fullmatch(rf"({_COLOR_WORD}) creatures", part)
    if colored is not None:
        return {"type_filter": "creature", "color_filter": COLOR_WORDS[colored.group(1)]}
    typed = re.fullmatch(r"(artifact|enchantment|land) creatures", part)
    if typed is not None:
        return {"type_filter_all": [typed.group(1), "creature"]}
    singular = part[:-1] if part.endswith("s") else part
    if singular in CREATURE_TYPES:
        return {"subtype_filter": singular}
    return None

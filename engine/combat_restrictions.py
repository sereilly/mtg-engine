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

from .grammar.vocabulary import CREATURE_TYPES

# Basic land types a "controls a <type>" clause can name. Restricted to the five
# basics deliberately: the enforcing check in declare_attackers_step scopes its
# search to lands, and a nonbasic type would need the same scoping decided
# per card.
_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")

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
#   cant_block                      phases/declare_blockers_step
#   must_attack_each_combat         phases/declare_attackers_step._must_attack_if_able
#   cant_be_blocked_by              phases/declare_blockers_step
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


def combat_restriction_for(normalized_line: str) -> CombatRestriction | None:
    """The combat restriction *normalized_line* imposes, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``), which
    is what the compiler holds at the point it needs this.
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
        return CombatRestriction(kind, payload)
    return None

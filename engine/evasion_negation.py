"""Board-wide effects that switch an evasion ability off for blocking (CR 509.1b).

"Creatures with islandwalk can be blocked as though they didn't have
islandwalk." (Undertow.) Legends prints this on five enchantments and three
creatures, one per basic land type, and the shape is a template rather than a
card quirk — so the landwalk word is payload and a card printed with any other
one needs no registration, exactly as the land type in
``engine/combat_restrictions.py`` is payload.

**"As though it didn't have" is not "loses".** CR 702.14b makes landwalk an
evasion ability, and an evasion ability creates a *blocking restriction*
(509.1b); this text lifts the restriction and nothing else. The attacker still
has the keyword — `has_keyword("islandwalk")` stays true, a lord that counts
creatures with islandwalk still counts it, and Magical Hack remapping the word
still finds it. Modelling it as a layer-6 removal would be a shorter
implementation of a different card.

There is no instruction kind here, and that is the point: like
`untap_restrictions.py` and `global_statics.py`, the enforcement site reads the
permanent's own text at the moment it needs the answer, so a card printed with
this template needs no registration at all. What the gate claims and what the
blockers step enforces are then the same function rather than two agreeing
tables.

The effect is *global* and belongs to no particular creature, so unlike the
restrictions in `combat_restrictions.py` it is not read off the attacker.
`declare_blockers_step._attacker_has_active_landwalk` asks the board: while any
permanent with this line is on the battlefield, that landwalk stops restricting
blocks for every creature, its controller's included (the card says "creatures",
not "creatures your opponents control").
"""

from __future__ import annotations

import re
from functools import lru_cache

#: The evasion abilities this file can switch off. Landwalk only, and
#: deliberately: the enforcement site above is the landwalk check, so a word
#: admitted here that it does not read would be a line the gate accepts and
#: nothing acts on. Flying's and fear's negations arrive with the card that
#: prints them, beside the check that enforces *them*.
_NEGATABLE = ("plainswalk", "islandwalk", "swampwalk", "mountainwalk", "forestwalk")

_REMINDER = re.compile(r"\([^)]*\)")

_TEMPLATE = re.compile(
    rf"^creatures with (?P<keyword>{'|'.join(_NEGATABLE)}) can be blocked "
    rf"as though they didn't have (?P<repeat>{'|'.join(_NEGATABLE)})$"
)


def evasion_negation_for(line: str) -> str | None:
    """The evasion keyword one printed *line* switches off for blocking, or None.

    The printed sentence names the keyword twice and both halves must agree: a
    card reading "creatures with islandwalk can be blocked as though they
    didn't have swampwalk" is not a card this file has ever seen, and matching
    it on the first half alone would silently negate the wrong ability.
    """
    match = _TEMPLATE.match(_normalize(line))
    if match is None or match.group("keyword") != match.group("repeat"):
        return None
    return match.group("keyword")


def _normalize(line: str) -> str:
    return " ".join(_REMINDER.sub("", line).lower().split()).strip().rstrip(".")


@lru_cache(maxsize=None)
def negated_evasion_abilities(oracle_text: str) -> frozenset[str]:
    """Every evasion ability a card's whole text switches off.

    Cached on the text, which is immutable on a ``CardDefinition`` — the
    block-legality check runs this over every permanent on the battlefield for
    each attacker/blocker pair it considers, so it has to cost a dict lookup.
    A *set* rather than the first match, because Lord Magnus prints two of these
    lines and answering with one of them would leave the other silently
    unenforced.
    """
    if "as though" not in oracle_text.lower():
        return frozenset()
    return frozenset(
        keyword
        for line in oracle_text.splitlines()
        if (keyword := evasion_negation_for(line)) is not None
    )


__all__ = [
    "evasion_negation_for",
    "negated_evasion_abilities",
]

"""Text-keyed extra land plays (CR 305.2, 505.5b).

"You may play any number of lands on each of your turns" (Fastbond), "You may
play an additional land on each of your turns", "You may play two additional
lands on each of your turns" — one printed template with one parameter, how many
extra land plays the permanent grants. The optional rider that comes with the
unlimited form ("Whenever you play a land, if it wasn't the first land you played
this turn, ~ deals N damage to you") is the second parameter.

This replaced ``Game._fastbond_count``, which counted battlefield permanents
**named "Fastbond"** and was consulted from four places (cast validation, the
land-drop damage, the AI's land policy and the web layer's playable-card list).
The gate and the dispatch were written with different literals, which is the
split this codebase keeps finding: ``scripts/parse_coverage.py`` claimed the
*sentence* "you may play any number of lands on each of your turns", so any card
printed with it counted as covered, while the code behind that claim only ever
fired for one name. Measured before this table was written: an invented card with
Fastbond's exact text compiled **supported**, granted no extra land play, and
dealt no damage.

Everything below is derived from the printed sentence, so a differently-named
card with the same template needs no code at all —
``tests/rules/test_land_play_allowance.py`` pins that with invented cards.

The **support gate reads this same table** (``oracle._derived_static_claims``),
so a wording it does not understand cannot be admitted as supported and then
silently unenforced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import _NUMBER_WORDS

_COUNT_WORD = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))

# Nouns a card uses to refer to itself in these lines. "~" is the placeholder
# some normalizations leave behind when the card's own name is stripped.
_SELF_NOUN = r"(?:this (?:artifact|creature|enchantment|land|permanent)|~)"


@dataclass(frozen=True)
class LandPlayAllowance:
    """Extra land plays one permanent grants.

    extra                 -- additional land plays beyond the one CR 305.2
                             allows; ``None`` means any number
    damage_per_extra_land -- damage the source deals its controller when a land
                             is played that wasn't the first this turn (0 when
                             the card prints no such rider)
    every_player          -- whether the permission reaches **every** seat
                             ("Each player may play an additional land during
                             each of their turns", Storm Cauldron) rather than
                             its controller alone ("**You** may play…",
                             Fastbond). A field rather than two dataclasses,
                             because the seat the sentence names is the one
                             thing that differs and the count, the rider and
                             every reader are the same either way — and a field
                             the caller must consult is what stops the wider
                             sentence being read as the narrower one, which is
                             a card that grants its own controller a land drop
                             and quietly takes one from everybody else.
    """

    extra: int | None
    damage_per_extra_land: int = 0
    every_player: bool = False


_ANY_NUMBER = re.compile(r"^you may play any number of lands on each of your turns$")

# The other direction: no land plays at all (Worms of the Earth). CR 305.1's
# permission withdrawn rather than a count granted, so it is its own predicate
# and its own name — the allowance dataclass counts *extra* plays and has no
# value meaning "none", and inventing one would make every reader of `extra`
# have to remember a special case.
#
# Deliberately **not** the same rule as "lands can't enter the battlefield" on
# the same card: that one is CR 614.17 and lives in `engine/replacements.py`,
# because it is about a land arriving from anywhere rather than about the action
# of playing one. A card printing only this line still lets a reanimated land
# through, which is what it says.
_NO_LAND_PLAYS = re.compile(r"^players can't play lands$")

_ADDITIONAL = re.compile(
    rf"^you may play (?:an|(?P<count>{_COUNT_WORD})) additional lands? "
    r"(?:on|during) each of your turns$"
)

# The same permission with the seat widened: "**Each player** may play an
# additional land during **each of their turns**." (Storm Cauldron.)
#
# Its own pattern rather than an optional group on the one above, because the
# possessive has to *agree* with the subject: "each player may play an
# additional land on each of your turns" is a sentence nobody prints, and a
# regex loose enough to accept it would be loose enough to read Fastbond's
# sentence as everyone's. The preposition differs too ("during" against "on"),
# which is the printing rather than a parameter — both spellings are accepted
# on both patterns because the word carries no meaning here, and refusing one
# would cost a card for its typography.
_ADDITIONAL_EACH_PLAYER = re.compile(
    rf"^each player may play (?:an|(?P<count>{_COUNT_WORD})) additional lands? "
    r"(?:on|during) each of their turns$"
)

# Fastbond's rider. Anchored at both ends for the usual reason: a line saying
# more than this carries something the land-drop path would not perform.
_DAMAGE_RIDER = re.compile(
    rf"^whenever you play a land, if it wasn't the first land you played this turn, "
    rf"{_SELF_NOUN} deals (?P<amount>\d+) damage to you$"
)


def land_play_line(normalized_line: str) -> str | None:
    """Name the part of the template *normalized_line* states, or None.

    ``"allowance"`` for the permission clause, ``"damage_rider"`` for the
    self-damage trigger that may accompany it. Its callers are
    ``scripts/parse_coverage.py`` (which needs to know each sentence is claimed
    by code that really runs) and the grammar's refusal registry — nothing
    dispatches on the returned name.
    """
    line = normalized_line.strip().lower().rstrip(".")
    if (
        _ANY_NUMBER.match(line)
        or _ADDITIONAL.match(line)
        or _ADDITIONAL_EACH_PLAYER.match(line)
    ):
        return "allowance"
    if _NO_LAND_PLAYS.match(line):
        return "prohibition"
    if _DAMAGE_RIDER.match(line):
        return "damage_rider"
    return None


@lru_cache(maxsize=None)
def lands_cannot_be_played(oracle_text: str) -> bool:
    """Whether *oracle_text* withdraws CR 305.1's permission to play a land.

    Read by ``Game._may_play_another_land``, which is the one question every
    land-drop gate asks — cast validation, the AI's land policy and the web
    layer's playable list — so a prohibition cannot be enforced in one of them
    and not the others. The **support gate reads this same table**
    (``land_play_line`` above), which is what stops a card being admitted with
    its prohibition unenforced: an unenforced "can't" is silent and wrong in the
    player's favour.
    """
    lowered = oracle_text.lower()
    if "play lands" not in lowered:
        return False
    return any(
        _NO_LAND_PLAYS.match(raw_line.strip().rstrip("."))
        for raw_line in lowered.splitlines()
    )


@lru_cache(maxsize=None)
def land_play_allowance_for(oracle_text: str) -> LandPlayAllowance | None:
    """The extra land plays *oracle_text* grants, or None.

    Cached on the text itself, which is immutable on a ``CardDefinition``, so
    the per-permanent scan in the land-drop path stays as cheap as the name
    comparison it replaced. The permission clause is what makes an allowance:
    the damage rider alone is a trigger this module does not own, so a card
    printing only the rider returns None rather than silently granting a land.
    """
    lowered = oracle_text.lower()
    if "each of your turns" not in lowered and "each of their turns" not in lowered:
        return None
    extra: int | None = 0
    found = False
    every_player = False
    damage = 0
    for raw_line in lowered.split("\n"):
        line = raw_line.strip().rstrip(".")
        if not line:
            continue
        if _ANY_NUMBER.match(line):
            extra, found = None, True
            continue
        additional = _ADDITIONAL.match(line)
        if additional is None:
            # The seat-widened spelling (Storm Cauldron). Read second so the
            # narrower sentence keeps its own reading; the two cannot both
            # match, because each anchors on its own subject.
            additional = _ADDITIONAL_EACH_PLAYER.match(line)
            if additional is not None:
                every_player = True
        if additional is not None:
            count = additional.group("count")
            if extra is not None:
                extra += _NUMBER_WORDS[count] if count else 1
            found = True
            continue
        rider = _DAMAGE_RIDER.match(line)
        if rider is not None:
            damage += int(rider.group("amount"))
    if not found:
        return None
    return LandPlayAllowance(
        extra=extra, damage_per_extra_land=damage, every_player=every_player
    )


__all__ = [
    "LandPlayAllowance",
    "land_play_allowance_for",
    "land_play_line",
    "lands_cannot_be_played",
]

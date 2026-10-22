"""Whether a card in a zone answers to a **name** — and the cards that count as
a card of a name they do not have.

CR 201.2a: two objects have the same name if they have at least one name in
common. CR 709.4a: a split card everywhere but the stack has both its halves'
names. So "is this card named N?" is a question about a *set* of names, and one
reader answers it for every count over a zone — a card with two names read off
its one printed spelling ("Fire // Ice") is named neither.

And one printed static widens it::

    If this card is in a graveyard, effects from spells named Flame Burst
    count it as a card named Flame Burst.

(Pardic Firecat; Diligent Farmhand prints it of Muscle Burst.) A static ability
that functions **in the graveyard** (CR 113.6b: an ability that states which
zones it functions in functions only from those) and changes what a name count
sees — but only for effects *from spells* of one name. It gives the card no
name: a tutor for "a card named Flame Burst" does not find a Firecat, and
neither does a count taken by anything but a Flame Burst.

**Text-keyed**, like ``combat_restrictions`` and ``cast_restrictions``: both
names are payload, so a card printing the sentence of another spell needs no
registration. The support gate (``derived_static_claims._derived_static_claims``), the
grammar's claim (``grammar/registries``) and the count
(``handlers/_common._card_matches_filter``) all read :func:`counts_as_line`,
so what is claimed and what is counted are one table.

The count is of **cards**, so a Firecat in a graveyard is one card named Flame
Burst — never two, and never one per line it prints.
"""

from __future__ import annotations

import re

from .faces import card_names
from .search_filters import name_key

#: The registry label the grammar's claim and the coverage report carry.
CLAIM = "counted_names"

#: The zones the printed condition may name, as ``printed word -> zone``. One
#: row because the pool prints one; a card saying "in your hand" is a row, not
#: a second pattern.
_ZONES: dict[str, str] = {"a graveyard": "graveyard"}

#: Neither name may hold a full stop: the line is one sentence, and a name
#: allowed to run past one would swallow whatever sentence followed it — a
#: creature admitted on this line with its next sentence read as part of a
#: card name nothing is called.
_COUNTS_AS = re.compile(
    r"^if this card is in (?P<zone>a graveyard), effects from spells named "
    r"(?P<spell>[^.]+?) count it as a card named (?P<name>[^.]+?)\.?$",
    re.IGNORECASE,
)


def counts_as_line(line: str) -> tuple[str, str, str] | None:
    """``(zone, spell name key, counted name key)`` for a counts-as line, else
    None.

    The names are returned as :func:`~engine.search_filters.name_key` reduces
    them, which is how every other name in the engine is compared — the grammar
    hands a ``named`` filter over lower-cased with its punctuation split off,
    and Oracle spells it otherwise.
    """
    match = _COUNTS_AS.match(line.strip())
    if match is None:
        return None
    zone = _ZONES.get(match.group("zone").lower())
    spell, name = name_key(match.group("spell")), name_key(match.group("name"))
    if zone is None or not spell or not name:
        return None
    return zone, spell, name


def counts_as_claims_line(line: str) -> bool:
    """Whether *line* is one this module carries out in full."""
    return counts_as_line(line) is not None


def _counted_as(card, zone: str, spell_key: str) -> tuple[str, ...]:
    """The name keys *card* counts as, in *zone*, to effects of a spell named
    *spell_key*.

    Read off the **printed** text: a card outside the battlefield has no
    computed characteristics (CR 613.1), so there is no layer to ask and no
    effect that could have removed the line.
    """
    text = getattr(card, "oracle_text", "") or ""
    if "count it as a card named" not in text.lower():
        return ()
    # Late, for the module cycle: ``oracle`` imports this one for its gate.
    from .oracle import expand_ability_lines

    expanded = expand_ability_lines(
        text, card_name=getattr(card, "name", None),
        legendary=bool(getattr(card, "is_legendary", False)),
    )
    found = []
    for raw in expanded.splitlines():
        read = counts_as_line(raw)
        if read is not None and read[0] == zone and read[1] == spell_key:
            found.append(read[2])
    return tuple(found)


def card_answers_to_name(
    card, name: str, *, zone: str | None = None, effect_spell: str | None = None,
) -> bool:
    """Whether *card* is, or counts as, a card named *name*.

    *zone* is where the card is and *effect_spell* the name of the **spell**
    whose effect is asking — both None for a reader that is not a spell's
    effect (an ability, a continuous recompute, a search), which then gets
    CR 201.2a's answer and nothing more.
    """
    wanted = name_key(str(name))
    if not wanted:
        # CR 201.2a: an object with no name has the same name as nothing.
        return False
    if any(name_key(own) == wanted for own in card_names(card)):
        return True
    if zone is None or not effect_spell:
        return False
    return wanted in _counted_as(card, zone, name_key(effect_spell))


def cards_sharing_a_name(pile) -> frozenset[int]:
    """The positions in *pile* whose card shares a name with **another** card
    of the pile (CR 201.2a: at least one name in common).

    By position, because "another" cannot be asked by identity: a deck repeats
    one immutable ``CardDefinition`` per copy, so two copies of a card in a hand
    are one object. A card with no name shares a name with nothing.
    """
    held: dict[str, list[int]] = {}
    for index, card in enumerate(pile):
        for own in {name_key(name) for name in card_names(card)}:
            if own:
                held.setdefault(own, []).append(index)
    return frozenset(
        index for indices in held.values() if len(indices) > 1 for index in indices
    )


__all__ = [
    "CLAIM", "card_answers_to_name", "cards_sharing_a_name",
    "counts_as_claims_line", "counts_as_line",
]

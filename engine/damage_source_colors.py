"""What colour a damage source is (CR 105, CR 609.7b).

A damage event's ``source`` is a ``Permanent`` for a permanent and the printed
``CardDefinition`` for a spell (CR 109.5), and three different questions in this
engine ask what colour it is: a colour shield's recheck (CR 609.7b — "when the
source *would deal damage*, the shield rechecks the source's properties"), a
Circle of Protection's chosen colour, and protection's damage prevention
(CR 702.16e). They asked it three ways.

**And a static ability may answer differently from the object itself.** "Black
and/or red permanents and spells are colorless sources of damage." (Ghostly
Flame.) The permanent is still black; only its colour *as a source of damage* is
rewritten, which is why this cannot be a layer-5 colour change — a layer-5
Ghostly Flame would stop a black creature being enchanted by "enchant black
creature", make it an illegal target for a spell that says "target black
permanent", and stop a Bad Moon buffing it. None of that is the card.

So the colour of a source-of-damage is its own question with its own answer,
derived here beside ``damage_events.damage_source_seat`` and for exactly that
function's reason: every damage path passes through one seam, and a rule read at
the fire sites is a rule as many places can forget it as there are sites.

There is no instruction kind here. Like ``evasion_negation.py`` and
``untap_restrictions.py``, the reader asks the board at the moment it needs the
answer, so a card printed with this template needs no registration at all — and
what the support gate claims and what the damage paths enforce are the same
function rather than two agreeing tables.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .oracle_types import _COLOR_WORD_TO_SYMBOL

#: The claim string the support gates use for a line this file implements.
CLAIM = "damage_source_colors"

_COLOUR = "|".join(_COLOR_WORD_TO_SYMBOL)

#: "Black and/or red permanents and spells are colorless sources of damage."
#: (Ghostly Flame.) The colour list is payload, and so is the join: Magic prints
#: "and/or" for a union of qualities and plain "or" elsewhere, and a card naming
#: one colour prints neither.
#:
#: "permanents **and** spells" is the whole set of things that can be a source
#: (CR 109.5 leaves an ability's source as the object that produced it, which is
#: one or the other), so the phrase is required rather than payload: a card
#: naming only one half would be a narrower rule this cannot express, and
#: matching it here would apply the wider one.
_COLORLESS_SOURCE = re.compile(
    rf"^(?P<colors>({_COLOUR})(?:\s*(?:and/or|and|or)\s*({_COLOUR}))*) "
    r"permanents and spells are colorless sources of damage$"
)

_JOINS = re.compile(r"\s*(?:and/or|and|or)\s*")


def colorless_source_line(line: str) -> frozenset[str] | None:
    """The colour symbols *line* makes colorless **as damage sources**, or None.

    Read by the support gate, by the grammar's parse claim and by
    :func:`damage_source_colors`, so a wording admitted here is a wording the
    damage paths really honour.
    """
    match = _COLORLESS_SOURCE.match(" ".join(line.split()).strip().lower().rstrip("."))
    if match is None:
        return None
    words = [word for word in _JOINS.split(match.group("colors")) if word]
    return frozenset(_COLOR_WORD_TO_SYMBOL[word] for word in words)


def source_colors(source, *, game=None, seat: int | None = None) -> tuple[str, ...]:
    """The colours a damage source *is*, before any damage-source rewrite.

    A permanent answers through the CR 613 layer system, which is what makes a
    lace (CR 105, layer 5) and a copy's colours (CR 707.2a, layer 1) reach a
    colour shield at all — this used to read the printed ``colors`` plus one
    hand-checked ``color_override`` metadata key, so Legends' five "becomes red
    **until end of turn**" spells wrote a second channel the shields never saw
    and a Circle of Protection: Red let the reddened creature through.

    A spell has no permanent — and this used to say that therefore "the printed
    colours are the whole answer", which was the same mistake one zone over.
    CR 613.1 applies the layers to an **object**, and Celestial Dawn's second
    sentence is a layer-5 effect whose scope is a seat's spells and cards. So a
    spell answers through ``object_colors`` with the seat that controls it
    (CR 109.5); a caller with no *game* or no seat gets the printed colours,
    which is the answer it had before.
    """
    if source is None:
        return ()
    effective = getattr(source, "effective_colors", None)
    if effective is not None:
        return tuple(sorted(effective))
    card = getattr(source, "card", source)
    if game is None:
        return tuple(getattr(card, "colors", ()) or ())
    from .object_colors import card_colors

    return card_colors(game, card, seat)


@lru_cache(maxsize=None)
def _line_colors(text: str) -> frozenset[str]:
    """The colours one permanent's whole text makes colorless as sources."""
    colours: set[str] = set()
    for line in (text or "").splitlines():
        found = colorless_source_line(line)
        if found:
            colours.update(found)
    return frozenset(colours)


def colorless_source_colors(game) -> frozenset[str]:
    """Every colour some permanent on the battlefield makes a colorless source.

    Asked of the board rather than of the damaged permanent or the source,
    because the sentence is about neither: it is a rule the game is playing
    under while the enchantment is there, and it reaches both players' sources
    ("permanents **and spells**", with no controller narrowing).

    Read off ``effective_card``, so a copy of Ghostly Flame and a Ghostly Flame
    whose text was changed both answer with what they now say (CR 707.2,
    CR 612.1).
    """
    if game is None:
        return frozenset()
    colours: set[str] = set()
    for perm in game.all_permanents():
        colours.update(_line_colors(perm.effective_card.oracle_text or ""))
    return frozenset(colours)


def damage_source_colors(game, source, *, seat: int | None = None) -> tuple[str, ...]:
    """The colours *source* has **as a source of damage** (CR 609.7b).

    The one answer every damage-colour question asks. A source none of the
    board's rewrites names keeps its own colours; one that any of them names is
    colorless *entirely* — "black and/or red permanents … are **colorless**
    sources", not "lose black and red", so a black-green source that deals
    damage is colorless and a shield answering to green no longer answers to it.

    *seat* is whose the source is, for the spell half — every damage event
    already carries it as ``source_seat`` (``damage_events.damage_source_seat``,
    derived once per event), so the callers pass that rather than deriving a
    second answer. Omitting it keeps the printed reading, which is what a
    caller holding no event has.
    """
    colours = source_colors(source, game=game, seat=seat)
    if not colours:
        return colours
    rewritten = colorless_source_colors(game)
    return () if rewritten & set(colours) else colours


__all__ = [
    "CLAIM", "colorless_source_colors", "colorless_source_line",
    "damage_source_colors", "source_colors",
]

"""What a seat's lands produce instead, while an effect says so (CR 611.2).

``Permanent.metadata["produced_mana_swaps"]`` is the other half of this idea and
it is deliberately not this one. That record names *one land* and one symbol
("If target Plains is tapped for mana, it produces colorless mana instead of
white mana" — Quarum Trench Gnomes), so it lives on the permanent it changes and
dies with it (CR 400.7). Deep Water's sentence — "Until end of turn, if you tap
a land you control for mana, it produces {U} instead of any other type" — names
a **class** and a **window**:

- the class includes lands that have not entered the battlefield yet, so there
  is no permanent to write it on and nothing to update when one arrives;
- which lands a seat controls is answered when a land is tapped, not when the
  ability resolved, so a record stamped on the board at resolution would be
  wrong the moment control changed;
- "until end of turn" needs a sweep, and the per-permanent record has none.

So the record hangs off the **player**, exactly as ``engine/shields.py`` and
``engine/damage_redirects.py`` hang theirs — an attribute rather than a
``PlayerState`` field, so a new kind of swap needs no new field and no new
clearing line, and the cleanup step's one call expires it.

**Where it is read** is the tap seam, ``Game.tap_land_for_mana``, and the
payment planner. It cannot be read by ``Permanent.effective_produced_mana``:
that is a property with no game, so it cannot ask who controls the land — and
the property is bypassed anyway on any land with a compiled mana ability, which
runs and writes into the pool itself. The tap seam is the one place both
branches meet, which is also the place the sentence describes.

**The third half: a static ability that says it from the battlefield.** "If a
land is tapped for mana, it produces {B} instead of any other type" (Infernal
Darkness), "…colorless mana instead…" (Ritual of Subdual), "If tapped for mana,
Plains produce {R}, Islands produce {G}, … instead of any other type" (Naked
Singularity, Reality Twist). CR 106.12b calls these replacement effects over
the mana production event, and CR 613's static reading is what makes them
different from the two records above: nothing resolves and nothing is stamped,
so the sentence is *derived from the source's text* on every tap, the way
``engine/land_animation.py`` and ``engine/land_types.py``'s "All X are Y"
derive theirs. Which lands it covers is a land **type** and not a controller —
"a land" is every land on every battlefield, which is why the scan is over
``all_permanents`` and asks no seat anything.

One question, three producers, and therefore one answer:
:func:`swapped_symbol`. The CR 614 interceptor that applies it is
``engine/replacements.py``'s ``_substitute_land_mana`` — registered there
because that is where a replacement effect goes and where the support gate
looks for the line's claim, and thin because deciding *what* a land produces
instead is this module's question and the payment planner has to be able to ask
it without applying anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .shields import END_OF_TURN  # noqa: F401  (one duration vocabulary)


@dataclass
class LandManaSwap:
    """One "your lands produce <symbol> instead" record on a seat.

    produced   -- the symbol every covered land makes instead
    lands      -- the printed noun phrase it covers, as a filter payload. Held
                  to what ``subject_filters.subject_matches`` can test, by the
                  lowering, for the reason every filter in this engine is: a
                  restriction the matcher drops is a swap over strictly more
                  lands than the card prints.
    lifetime   -- END_OF_TURN; the sweep that clears shields clears these.
    source_name-- the card that armed it, for the log.
    """

    produced: str
    lands: dict = field(default_factory=dict)
    lifetime: str = END_OF_TURN
    source_name: str | None = None


#: Where the list hangs off a player, for the reason ``engine/shields.py`` uses
#: an attribute: a ``PlayerState`` carries it without learning what a swap is.
_SWAPS_ATTR = "_land_mana_swaps"


def swaps_on(player) -> list[LandManaSwap]:
    """The swaps armed by *player*, created on first use."""
    records = getattr(player, _SWAPS_ATTR, None)
    if records is None:
        records = []
        setattr(player, _SWAPS_ATTR, records)
    return records


def add_swap(player, swap: LandManaSwap) -> LandManaSwap:
    """Put *swap* on *player* and return it."""
    swaps_on(player).append(swap)
    return swap


def clear_swaps(player, lifetime: str | None = None) -> None:
    """Expire records whose duration has run out — the same shape
    ``shields.clear_shields`` and ``damage_redirects.clear_redirects`` have, so
    a turn-step sweep stays one call."""
    records = swaps_on(player)
    records[:] = [r for r in records if lifetime is not None and r.lifetime != lifetime]


# ---------------------------------------------------------------------------
# The static reading: "If a land is tapped for mana, it produces X instead …"
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManaSubstitution:
    """One printed "produces <symbol> instead of any other type" clause.

    produced   -- the symbol the covered lands make instead.
    land_type  -- the basic land type the clause names ("plains"), or None for
                  the untyped spelling that covers every land ("**a land** is
                  tapped for mana"). None is "no restriction" and never
                  "unreadable": a type word the catalog has never heard of
                  refuses the whole line, because a clause that reaches nothing
                  and a clause nobody implemented look identical on a board.
    """

    produced: str
    land_type: str | None = None


#: "If a land is tapped for mana, it produces <mana> instead of any other
#: type." (Ritual of Subdual, Infernal Darkness.) Anchored at both ends: a
#: sentence saying more than this carries a rider nothing here performs.
_ANY_LAND_RE = re.compile(
    r"^if a land is tapped for mana, it produces (?P<mana>.+?) "
    r"instead of any other type$"
)

#: "If tapped for mana, Plains produce {R}, Islands produce {G}, … instead of
#: any other type." (Naked Singularity, Reality Twist.) How *many* clauses is
#: payload — the two cards differ only in the list — so the list is split
#: rather than counted in the pattern.
_BY_TYPE_RE = re.compile(
    r"^if tapped for mana, (?P<clauses>.+?) instead of any other type$"
)
_ONE_TYPE_RE = re.compile(r"^(?:and )?(?P<type>[a-z']+) produce (?P<mana>.+)$")


@lru_cache(maxsize=1)
def _land_types() -> frozenset[str]:
    # Imported lazily: the grammar package imports engine-level derivation
    # modules, so a module-level import here would close a cycle.
    from .grammar import vocabulary

    return vocabulary.LAND_TYPES


def _land_subtype(word: str) -> str | None:
    """The land type *word* names, however it was pluralised.

    The catalog stores singulars and "Plains" is its own plural, so each
    candidate stem is tried *against the catalog* rather than a shape being
    assumed — the same reason ``land_animation._land_subtype`` works this way.
    """
    land_types = _land_types()
    for candidate in (word, word[:-1]):
        if candidate and candidate in land_types:
            return candidate
    return None


def _mana_symbol(phrase: str) -> str | None:
    """The one mana symbol *phrase* names, or None.

    Two printed spellings, because the pool prints both: the symbol itself
    (``{B}``) and the colour written out (``colorless mana``, and the five
    colour words the same sentence could carry — Quarum Trench Gnomes already
    prints "colorless mana instead of **white** mana" one module over). A
    phrase naming more than one symbol, or none, refuses: the record this feeds
    holds a single symbol, so "produces {B}{B}" read as "{B}" would be a card
    making half the mana it prints.
    """
    from .grammar import vocabulary

    text = phrase.strip()
    match = re.fullmatch(r"\{([wubrgc])\}", text)
    if match is not None:
        return match.group(1).upper()
    word, _, tail = text.partition(" ")
    if tail != "mana":
        return None
    if word == "colorless":
        return "C"
    return vocabulary.COLOR_WORDS.get(word)


@lru_cache(maxsize=None)
def substitution_line(normalized_line: str) -> "tuple[ManaSubstitution, ...] | None":
    """The mana substitutions *normalized_line* imposes, or None.

    Takes an already-lowercased line with or without its trailing full stop —
    the form ``replacement_claims_line`` and the board scan below both reduce
    to, so the claim and the behaviour are one function.
    """
    line = normalized_line.strip().lower().rstrip(".")
    untyped = _ANY_LAND_RE.match(line)
    if untyped is not None:
        symbol = _mana_symbol(untyped.group("mana"))
        if symbol is None:
            return None
        return (ManaSubstitution(produced=symbol, land_type=None),)
    typed = _BY_TYPE_RE.match(line)
    if typed is None:
        return None
    found: list[ManaSubstitution] = []
    for clause in typed.group("clauses").split(", "):
        parts = _ONE_TYPE_RE.match(clause.strip())
        if parts is None:
            return None
        land_type = _land_subtype(parts.group("type"))
        symbol = _mana_symbol(parts.group("mana"))
        if land_type is None or symbol is None:
            return None
        found.append(ManaSubstitution(produced=symbol, land_type=land_type))
    return tuple(found) or None


def substitutions_on(source) -> tuple[ManaSubstitution, ...]:
    """Every substitution *source*'s printed text imposes, in printed order.

    Read off ``effective_card``, so a text change (layer 3) or a copy (layer 1)
    is what the static says — the same reading every other text-keyed table in
    this engine takes.
    """
    text = getattr(source.effective_card, "oracle_text", "") or ""
    found: list[ManaSubstitution] = []
    for line in text.split("\n"):
        read = substitution_line(line)
        if read:
            found.extend(read)
    return tuple(found)


def static_substituted_symbol(game, land) -> str | None:
    """The symbol a battlefield static makes *land* produce instead, or None.

    Every battlefield, not the land controller's: "**a land** is tapped for
    mana" names no seat at all, so an opponent's Ritual of Subdual covers this
    land exactly as its controller's does. That is the same reading
    ``replacements._applies_lands_cant_enter`` takes of "Lands can't enter the
    battlefield" and for the same reason — the sentence has no "you" in it.

    Where several clauses reach one land — a Tundra under Naked Singularity is
    both a Plains and an Island — the first in printed order answers. CR 616.1
    would put the choice to the land's controller; taking the printed order is
    one legal set of those choices, and it is stated here rather than left to
    whichever scan order happened to win.
    """
    for source in game.all_permanents():
        for substitution in substitutions_on(source):
            if substitution.land_type is None or land.has_type(substitution.land_type):
                return substitution.produced
    return None


def swapped_symbol(game, land) -> str | None:
    """The symbol *land* produces instead of whatever it would have, or None.

    The recorded per-seat swaps are asked of the **controller's** records and
    nobody else's: "a land **you** control" is CR 109.5's you, the seat whose
    ability armed the swap, so an opponent's Deep Water says nothing about this
    land. The controller is read through the control seam rather than off the
    permanent, because that is the one answer to who controls what.

    The last record wins where a seat has two, which is CR 613.7's timestamp
    order: a second "instead of any other type" applies to the first one's
    answer, and the answer is a single symbol either way. The battlefield
    statics are asked first for that reason and no other — a record armed by a
    resolution is the more recent of the two in every board this pool can
    build, since a static applies from the moment its source entered.
    """
    from .subject_filters import subject_matches

    seat = game.controller_index_of(land)
    if seat is None:
        return None
    found = static_substituted_symbol(game, land)
    for record in swaps_on(game.players[seat]):
        if subject_matches(game, land, record.lands, observer=seat):
            found = record.produced
    return found


__all__ = [
    "END_OF_TURN", "LandManaSwap", "ManaSubstitution", "add_swap",
    "clear_swaps", "static_substituted_symbol", "substitution_line",
    "substitutions_on", "swapped_symbol", "swaps_on",
]

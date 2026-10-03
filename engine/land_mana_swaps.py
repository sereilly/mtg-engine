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

from .oracle_types import MANA_COLOR_OF_CHOICE
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
    #: The permanent whose recorded ``chosen_color`` this swap follows, for
    #: "lands tapped for mana produce mana of **the chosen color**" (Hall of
    #: Gemstone). None on every other record, which carries its symbol in
    #: ``produced``.
    #:
    #: Read when a land is tapped rather than snapshotted when the swap is
    #: armed, and the difference is an interactive seat: the colour choice is a
    #: queued prompt, so the step that arms this record can run before the
    #: answer arrives. Nothing can be tapped for mana in between — no player
    #: gets priority inside a resolution (CR 608.2) — so the later read is the
    #: same answer, and it is the one that cannot be a stale default.
    chosen_by: object | None = None
    #: "…instead of any other type **and amount**." (Harvest Mage.) The record
    #: clamps the whole production to one mana, as Contamination's static does.
    #: False on every record armed before a card printed the words.
    replaces_amount: bool = False
    #: "…instead of any other **color**." (Hall of Gemstone.) Only the coloured
    #: mana a covered land makes is replaced; its {C} stays {C}, because
    #: colorless is a type of mana but not a color (CR 106.1a, 106.1b). False
    #: is "any other type".
    colors_only: bool = False

    def symbol(self) -> str:
        """The symbol this record makes a covered land produce."""
        if self.chosen_by is None:
            return self.produced
        return str(getattr(self.chosen_by, "metadata", {}).get("chosen_color") or "")


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
    #: "…instead of any other type **and amount**." (Contamination.) The
    #: sentence replaces *how much* as well as *which*, so a land that makes
    #: two mana makes one {B} — where Infernal Darkness's "instead of any other
    #: type" leaves the amount alone and a two-mana land makes {B}{B}.
    #:
    #: Its own field rather than a second template, because the two cards print
    #: one sentence with one word's difference and the amount is what that word
    #: changes. Read as the type-only form, Contamination is a strictly better
    #: card on any land that makes more than one mana — which is the direction
    #: a substitution must never drift in.
    replaces_amount: bool = False
    #: "…instead of any other **color**" (Hall of Gemstone's record): the
    #: colourless part of the production passes through unchanged. Every
    #: printed static in the pool says "type", so this is only ever set from a
    #: :class:`LandManaSwap` that carries it.
    colors_only: bool = False


#: "If a land is tapped for mana, it produces <mana> instead of any other
#: type." (Ritual of Subdual, Infernal Darkness.) Anchored at both ends: a
#: sentence saying more than this carries a rider nothing here performs.
_ANY_LAND_RE = re.compile(
    r"^if a land is tapped for mana, it produces (?P<mana>.+?) "
    r"instead of any other type(?P<amount> and amount)?$"
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
        return (
            ManaSubstitution(
                produced=symbol,
                land_type=None,
                replaces_amount=bool(untyped.group("amount")),
            ),
        )
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


def static_substitution_for(game, land) -> "ManaSubstitution | None":
    """The battlefield static that makes *land* produce something else, or None.

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
                return substitution
    return None


def static_substituted_symbol(game, land) -> str | None:
    """The **symbol** a battlefield static makes *land* produce, or None.

    :func:`static_substitution_for` read for the one field most callers want.
    Kept as its own name because that is what every reader outside the tap seam
    asks for — the payment planner wants a colour, not a rule — and because the
    two must not be able to disagree about *which* static won, which they
    cannot when one calls the other.
    """
    found = static_substitution_for(game, land)
    return None if found is None else found.produced


#: The colours "a color of your choice" ranges over (CR 105.1) — never {C},
#: which is not a colour (CR 105.2c). Ordered WUBRG so a planner that walks it
#: is deterministic. Public because the planner hook answers the same five for
#: a land whose *own* (granted) mana ability makes any colour.
COLORS = ("W", "U", "B", "R", "G")


def _color_of_choice(requested, land) -> str:
    """The colour a tapper named for "one mana of a color of your choice".

    The tap seam always carries the colour the tapping seat asked the land for
    (``Game.tap_land_for_mana``'s ``chosen_color``), so that request *is* the
    choice. A request that is not a colour — colorless, or nothing — falls back
    to a colour the land itself makes, and only then to white: still a colour
    of the tapper's, and never a symbol the sentence rules out.
    """
    wanted = str(requested or "").upper()
    if wanted in COLORS:
        return wanted
    for symbol in getattr(land, "effective_produced_mana", ()) or ():
        if str(symbol).upper() in COLORS:
            return str(symbol).upper()
    return COLORS[0]


def swapped_production(game, land, requested=None) -> "ManaSubstitution | None":
    """What *land* produces instead of whatever it would have, or None.

    *requested* is the colour the tapper asked for, supplied by the tap seam
    alone. It answers a record whose symbol is "a color of your choice"
    (Harvest Mage); with no request — the payment planner asking what a land
    *could* make — such a record answers with :data:`MANA_COLOR_OF_CHOICE`
    itself, which a reader turns into the five colours.

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
    found = static_substitution_for(game, land)
    for record in swaps_on(game.players[seat]):
        if not subject_matches(game, land, record.lands, observer=seat):
            continue
        # A record following a chosen colour nobody has named yet says nothing,
        # rather than making the land produce the empty symbol — which is a
        # land that taps for no mana at all.
        symbol = record.symbol()
        if symbol == MANA_COLOR_OF_CHOICE and requested is not None:
            # "…one mana of a color of your choice…" (Harvest Mage): named by
            # the tapper for this one production (CR 106.12b).
            symbol = _color_of_choice(requested, land)
        if symbol:
            # The amount is the *record's* printed word — "…and amount"
            # (Harvest Mage) — and never inherited from whatever static it is
            # overriding: Deep Water prints "instead of any other type" and
            # stops there, so its record leaves the amount alone.
            found = ManaSubstitution(
                produced=symbol, land_type=None,
                replaces_amount=record.replaces_amount,
                colors_only=record.colors_only,
            )
    return found


def production_snapshot(player) -> dict:
    """Every bucket a mana production can write into, copied before it runs.

    The unrestricted pool under ``None`` and each CR 106.6 "spend this mana
    only to…" bucket under its own key (``restricted_mana.mana_bucket``). A
    swap is a replacement over the **production event** (CR 106.12b), and where
    the mana lands is a fact about the ability that made it, not about the
    event — so the seam has to see every bucket, not only the pool.

    It used to see the pool alone. Mishra's Workshop's {C}{C}{C} goes to the
    ``artifact`` bucket, so it escaped Deep Water, Infernal Darkness,
    Contamination and Harvest Mage alike: under Contamination it made three
    colourless where the card says one {B}.
    """
    snapshot = {None: dict(player.mana_pool)}
    for key, bucket in (getattr(player, "restricted_mana", None) or {}).items():
        snapshot[key] = dict(bucket)
    return snapshot


def substitute_production(
    player, before: dict, produced: str, amount: "int | None" = None,
    *, colors_only: bool = False,
) -> int:
    """Turn everything produced since *before* into *produced*, and return how
    much that is.

    **Bucket by bucket**, so mana keeps the restriction it was made with: the
    restriction is created by the ability that produced the mana (CR 106.6),
    the swap changes only the type — and, for "and amount", how much — of what
    that ability produced. CR 106.6a says the same of a replacement that adds
    mana: "any restrictions … created by the spell or ability will apply to all
    mana produced." A Workshop under Deep Water makes {U}{U}{U} that still pays
    only for artifact spells; dropped into the open pool it would be a strictly
    better land than the one printed.

    *amount* is "…and amount" (Contamination, Harvest Mage): the whole
    production is clamped to that many, counted across every bucket in the
    order they were written — the pool first, then each restricted bucket.

    *colors_only* is "…instead of any other **color**" (Hall of Gemstone):
    colourless mana is a type but not a colour (CR 106.1a), so {C} the land made is
    left exactly where it is and only the coloured mana is replaced.
    """
    buckets = [(None, player.mana_pool)]
    buckets.extend((getattr(player, "restricted_mana", None) or {}).items())
    total = 0
    for key, bucket in buckets:
        prior = before.get(key, {})
        gained = 0
        for symbol in list(bucket):
            if colors_only and symbol not in COLORS:
                continue
            delta = int(bucket.get(symbol, 0)) - int(prior.get(symbol, 0))
            if delta > 0:
                bucket[symbol] = int(bucket[symbol]) - delta
                gained += delta
        if amount is not None:
            gained = min(gained, max(0, int(amount) - total))
        if gained:
            bucket[produced] = int(bucket.get(produced, 0)) + gained
            total += gained
    return total


def payment_colors(game, land) -> "tuple[str, ...] | None":
    """The symbols tapping *land* can put in its controller's pool under a
    swap, or None when no swap applies.

    One symbol for every fixed swap; all five colours for "a color of your
    choice", because the tapper may name any of them. The payment planner and
    the client's colour prompt both ask this, so the two cannot disagree about
    what a Forest under Harvest Mage can pay for.

    A swap of colours only (Hall of Gemstone) leaves a land's {C} alone, so a
    land that makes only colourless is answered by no swap at all, and one
    that makes both keeps its {C} beside the swapped colour.
    """
    found = swapped_production(game, land)
    swapped = None if found is None else found.produced
    if swapped is None:
        return None
    offered = COLORS if swapped == MANA_COLOR_OF_CHOICE else (swapped,)
    if not found.colors_only:
        return offered
    own = {str(s).upper() for s in (getattr(land, "effective_produced_mana", ()) or ())}
    if not own & set(COLORS):
        return None
    return offered + (("C",) if "C" in own else ())


def swapped_symbol(game, land) -> str | None:
    """The **symbol** *land* produces instead, or None.

    :func:`swapped_production` read for the one field most callers want, and
    the same pairing :func:`static_substituted_symbol` makes one level down.
    """
    found = swapped_production(game, land)
    return None if found is None else found.produced


__all__ = [
    "COLORS", "END_OF_TURN", "LandManaSwap", "ManaSubstitution", "add_swap",
    "clear_swaps", "payment_colors", "production_snapshot",
    "static_substituted_symbol", "static_substitution_for",
    "substitute_production", "substitution_line", "substitutions_on",
    "swapped_production", "swapped_symbol", "swaps_on",
]

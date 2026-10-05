"""What colour an object is (CR 105) — a card in a zone, a spell, a permanent.

CR 105 asks the question of every object, and CR 613.1e answers it for a
permanent through the layer system. A card in a hand, a graveyard, a library or
the exile has no layer stack of its own, so this engine reads its printed
colours — which is right for every card in the pool but one.

"Nonland permanents you control are white. **The same is true for spells you
control and nonland cards you own that aren't on the battlefield.**" (Celestial
Dawn.) The second sentence is what makes an off-battlefield colour a real
question: with the Dawn out, the Swamp-turned-Plains in play is white *and* so
is the Dark Ritual still in hand, which is what lets it be cast at all under the
Dawn's own spending restriction.

**One reader**, which is the whole point of the module -- and since the ULG
round it answers for a permanent too (:func:`object_colors`), by handing that
half to the layer system. Not because a permanent needed a second reader, but
because half this module's callers hold "a spell **or** a permanent" and cannot
say which: a cost tax reads a card being cast and a permanent whose ability is
being activated, and protection reads a spell's colour and a creature's. A
caller that has to branch on the kind of object is a caller that can forget one
of the two, which is how every site below came to read the printed field.

The colour of a card outside the battlefield used to be read in three places that
could not agree — ``handlers/_common._card_matches_filter`` (a filter payload),
``search_filters.card_colors`` (a library search) and ``_stack_item_colors`` (a
spell) — and each read the printed field. Two of those took neither a game nor
an owner and documented the printed reading as deliberate, which it was, right
up until a card printed the sentence above.

The seat matters and is not optional. "Cards **you own**" is CR 108.3's owner
for a card in a zone and CR 109.5's controller for a spell, and a caller that
cannot say whose card it is gets the printed answer — the safe direction, since
a colour override applied to the wrong seat's cards is the card backwards.
"""

from __future__ import annotations

#: The printed colour word as the symbol the rest of the engine spells a colour
#: with. A third copy of this map would be a third chance to disagree, so the
#: two that exist (``layer_bridge``'s for permanents and this one) are the whole
#: population and both are two lines from the reader that needs them.
_COLOR_WORD_SYMBOLS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}


def _seat_index(game, seat) -> int | None:
    """*seat* as an index, whether the caller had one or a ``PlayerState``.

    Both spellings, because the callers genuinely have both: a handler scanning
    a hand holds the player object and a stack item records the index. Resolved
    by **identity**, never by value — two seats can compare equal early in a
    game, and this engine has been bitten by value comparison on a battlefield,
    a hand and a graveyard already.
    """
    if seat is None or game is None:
        return None
    if isinstance(seat, int):
        return seat
    for index, player in enumerate(getattr(game, "players", ()) or ()):
        if player is seat:
            return index
    return None


def color_override_for_seat(game, seat) -> tuple[str, ...] | None:
    """The colours *seat*'s spells and non-battlefield cards are set to, or None.

    Derived from the board on every call rather than stored, like every other
    static in this engine (CR 611.3a): the source leaving is the effect ending,
    with nothing to sweep and no stamp to clear.

    Only a static that prints the *second* sentence reaches here. A card
    printing the first alone would be a board-wide colour and nothing more, and
    admitting it here would recolour a hand on the strength of a sentence about
    the battlefield.
    """
    index = _seat_index(game, seat)
    if index is None:
        return None
    from .global_statics import global_static_for

    for permanent in game.controlled_by(index):
        # The printed text, for ``global_static_sources``' reason exactly: the
        # effective card folds in abilities these very statics grant, so asking
        # it here would make the answer depend on itself.
        static = global_static_for(getattr(permanent.card, "oracle_text", "") or "")
        if static is None or static.sets_colors is None:
            continue
        if not static.extends_to_spells_and_cards:
            continue
        symbols = tuple(
            _COLOR_WORD_SYMBOLS[word]
            for word in static.sets_colors
            if word in _COLOR_WORD_SYMBOLS
        )
        # Completeness rather than truth, for the reason ``sets_colors`` is
        # ``None`` when a static says nothing about colour: ``()`` is
        # CR 105.2c's colourless and a real answer, so "did anything survive
        # the map?" is the wrong question -- a printed word this map could not
        # read would fall through to the *printed* colours, which is a hand
        # recoloured by half a sentence.
        if len(symbols) == len(static.sets_colors):
            return symbols
    return None


def card_colors(game=None, card=None, seat=None) -> tuple[str, ...]:
    """The effective colours of *card* while *seat* owns or controls it.

    Falls back to the printed colours whenever the caller cannot say whose card
    it is or there is no game to ask, which is what every caller did before this
    module existed — so a site that has not been taught the seat keeps exactly
    the behaviour it had rather than guessing.

    A **land card is never recoloured**: the sentence says "nonland cards", and
    a land in a hand is one whatever the battlefield has done to the lands
    already on it.
    """
    printed = tuple(getattr(card, "colors", ()) or ())
    if card is None:
        return printed
    if "land" in (getattr(card, "type_line", "") or "").lower():
        return printed
    override = color_override_for_seat(game, seat)
    return override if override is not None else printed


def object_colors(game, obj, seat=None) -> tuple[str, ...]:
    """The effective colours of **any** object (CR 105 over CR 109.1).

    CR 613.1 is about an *object*, not a permanent: "the values of an object's
    characteristics are determined by starting with the actual object … then
    all applicable continuous effects are applied", and layer 5 is one of them.
    A permanent's answer comes out of the layer system; every other object's
    comes out of :func:`card_colors` above. Two derivations because the two
    kinds of object genuinely have nothing in common -- one reads a per-object
    layer stack, the other scans a seat's board -- but **one place they are
    asked**, which is what a caller holding "a spell or a permanent" needs.

    Dispatched on ``effective_colors``, which is what a ``Permanent`` has and a
    ``CardDefinition`` does not, for ``_source_has_quality``'s reason exactly: a
    token, an animated land and a copy are all permanents by that question and
    the import stays out. Empty is a real answer on both sides (CR 105.2c), so
    the dispatch is ``is not None`` and never truthiness.

    *seat* is ignored for a permanent, which is right rather than lax: the
    layers already know whose it is, and a caller holding a board object should
    not have to say.
    """
    if obj is None:
        return ()
    effective = getattr(obj, "effective_colors", None)
    if effective is not None:
        return tuple(sorted(effective))
    return card_colors(game, getattr(obj, "card", obj), seat)


# ---------------------------------------------------------------------------
# Colour *relations* (CR 105.2, CR 105.4)
# ---------------------------------------------------------------------------
#
# Everything above answers "what colour is this object". The four questions
# below are asked *about* those answers, and they live here for the reason the
# readers above do: Invasion prints each of them on several cards in several
# grammatical positions — a sweep's narrowing (Spreading Plague), a prevention
# predicate (Well-Laid Plans), a cast prohibition (Mana Maze), a cost change
# (Urza's Filter), a trigger's narrowing (Rewards of Diversity), a static's
# condition (Spirit of Resistance) — and a relation spelled at each of those
# sites is as many chances to disagree about a colourless object as there are
# sites. Every one of them takes **colour sets**, not objects: which reader
# produced the set (a layer stack, a stack item, a damage source) is the
# caller's knowledge and the relation is the same whoever asks.

#: CR 105.1: the five colours, in WUBRG order. The symbols the rest of the
#: engine spells a colour with.
ALL_COLORS: tuple[str, ...] = ("W", "U", "B", "R", "G")


def share_a_color(one, other) -> bool:
    """Whether two colour sets share a colour (CR 105.2).

    A non-empty **intersection**, which is the whole definition: a colourless
    object shares a colour with nothing — not even with another colourless one
    — and a multicoloured object shares with anything having one of its
    colours (CR 105.2b: it *is* each of them). Never an equality: a white-blue
    creature and a blue-black one share blue.

    Takes anything iterable over colour symbols, so a ``set`` out of the layer
    system, a ``tuple`` off a stack item and a ``frozenset`` a record kept all
    ask the one question.
    """
    return bool(frozenset(one or ()) & frozenset(other or ()))


def is_multicolored(colors) -> bool:
    """Whether a colour set is **multicolored** (CR 105.2b: two or more of the
    five colours).

    Counted against :data:`ALL_COLORS` rather than by ``len``: a set carrying
    a symbol that is not a colour ("C", a stray empty string off a malformed
    record) must not make a monocoloured object gold.
    """
    return len(frozenset(colors or ()) & frozenset(ALL_COLORS)) >= 2


def colors_among(game, permanents) -> frozenset[str]:
    """Every colour at least one of *permanents* has (CR 105.2, layer 5).

    "…protection from each color **among permanents you control**" (Pledge of
    Loyalty) and "a permanent **of each color**" (Spirit of Resistance) are
    this one union read two ways — as a set, and as a test that the set is
    full. Through the layer-aware accessor, so a permanent a Lace has recoloured
    counts as what it now is and a multicoloured one counts for each of its
    colours.
    """
    found: set[str] = set()
    for permanent in permanents:
        found.update(game._effective_colors(permanent))
    return frozenset(found) & frozenset(ALL_COLORS)


def colors_among_described(
    game, described: "dict | None", *, observer: int | None, source=None
) -> tuple[str, ...]:
    """The colours among the permanents a filter payload *described* names, in
    WUBRG order — "a color **of a permanent you control**" (Meteor Crater).

    :func:`colors_among` over the set ``subject_matches`` admits, so the noun
    phrase means here what it means in a sweep or a count and the colours are
    the layers' (a Lace-recoloured permanent offers what it now is, a
    colourless one offers nothing). *observer* is the seat "you control" is
    relative to and *source* the permanent whose ability this is.

    A tuple in the one fixed order, because every caller either offers the
    list to a player or takes its first entry as a deterministic default.
    """
    from .subject_filters import subject_matches

    found = colors_among(
        game,
        (
            permanent
            for permanent in game.all_permanents()
            if subject_matches(
                game, permanent, described, observer=observer, source=source
            )
        ),
    )
    return tuple(color for color in ALL_COLORS if color in found)


def of_each_color(game, permanents) -> bool:
    """Whether *permanents* include one **of each color** (CR 105.1's five).

    One permanent may answer for several colours — a white-blue-black-red-green
    creature is "a creature of each color" on its own — because the sentence
    asks that every colour be represented, not that five different permanents
    represent them. A colourless permanent represents none.

    The noun ("a **permanent** of each color", "a **creature** of each color")
    is the caller's: it hands over the permanents that noun names.
    """
    return colors_among(game, permanents) == frozenset(ALL_COLORS)


__all__ = [
    "ALL_COLORS", "card_colors", "color_override_for_seat", "colors_among",
    "colors_among_described",
    "is_multicolored", "object_colors", "of_each_color", "share_a_color",
]

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


__all__ = ["card_colors", "color_override_for_seat", "object_colors"]

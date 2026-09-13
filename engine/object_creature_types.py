"""What creature types an object has (CR 205.3) — a card in a zone, a spell, a
permanent.

The exact twin of ``engine/object_colors.py`` one characteristic over, and it
exists for that module's reason rather than by analogy. CR 613.1 applies the
layers to a **permanent**; a card in a hand, a library, a graveyard or the exile
has no layer stack, so this engine reads its printed type line — which is right
for every card in the pool but one.

"Creatures you control are the chosen type. **The same is true for creature
spells you control and creature cards you own that aren't on the battlefield.**"
(Conspiracy.) The second sentence is what makes an off-battlefield creature type
a real question: with a Conspiracy naming Goblin out, the Grizzly Bears in play
is a Goblin *and so is the one still in hand*, which is what makes "search your
library for a Goblin card" and "discard a Goblin card" find it.

**One reader**, which is the point of the module: a caller holding "a spell or a
card" cannot branch on the kind of object without being able to forget one of
them, and the printed read is what every such site did before Conspiracy was in
the pool.

The seat matters and is not optional. "Cards **you own**" is CR 108.3's owner
for a card in a zone and CR 109.5's controller for a spell, and a caller that
cannot say whose card it is gets the printed answer — the safe direction, since
a type override applied to the wrong seat's cards is the card backwards.

**Only creature cards.** The printed sentence says "creature spells" and
"creature cards", not "cards": a Lightning Bolt in hand under a Conspiracy is
not a Goblin, and CR 205.3d says so independently — an object cannot gain a
subtype that does not correspond to one of its types. Read off the printed type
line, which for a card outside the battlefield is the whole of what there is.
"""

from __future__ import annotations


def _seat_index(game, seat) -> int | None:
    """*seat* as an index, whether the caller had one or a ``PlayerState``.

    Both spellings, because the callers genuinely have both — and resolved by
    **identity**, never by value, for ``object_colors._seat_index``' reason:
    two seats can compare equal early in a game, and this engine has been
    bitten by value comparison on a battlefield, a hand and a graveyard.
    """
    if seat is None or game is None:
        return None
    if isinstance(seat, int):
        return seat
    for index, player in enumerate(getattr(game, "players", ()) or ()):
        if player is seat:
            return index
    return None


def creature_type_override_for_seat(game, seat) -> str | None:
    """The creature type *seat*'s creature spells and non-battlefield creature
    cards are set to, or None.

    Derived from the board on every call rather than stored, like every other
    static in this engine (CR 611.3a): the source leaving is the effect ending,
    with nothing to sweep and no stamp to clear.

    Only a static that prints the *second* sentence reaches here. A card
    printing the first alone would be a board-wide creature type and nothing
    more, and admitting it here would retype a hand on the strength of a
    sentence about the battlefield.

    The word itself is not in the static's text — it is the type the source
    chose as it entered (CR 614.1c) — so this reads the source permanent's own
    record, which is what makes a source still resolving its entry choice
    answer None rather than a blank type.
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
        if static is None or not static.sets_creature_type:
            continue
        if not static.extends_to_spells_and_cards:
            continue
        chosen = permanent.metadata.get("chosen_creature_type")
        if chosen:
            return str(chosen).lower()
    return None


def card_creature_types(game=None, card=None, seat=None) -> frozenset[str]:
    """The effective creature types of *card* while *seat* owns or controls it.

    Falls back to the printed subtypes whenever the caller cannot say whose card
    it is or there is no game to ask, which is what every caller did before this
    module existed — so a site that has not been taught the seat keeps exactly
    the behaviour it had rather than guessing.

    A **noncreature card is never retyped**: the sentence says "creature cards",
    and CR 205.3d would forbid it in any case.
    """
    from .layer_bridge import printed_shape

    if card is None:
        return frozenset()
    types, printed = printed_shape(card)
    if "creature" not in types:
        return printed
    override = creature_type_override_for_seat(game, seat)
    # CR 205.1a: the new subtype **replaces** the existing creature types, so
    # the Bear stops being a Bear. Only the creature types — a card printed as
    # an artifact creature keeps its artifact type — but a card outside the
    # battlefield has no computed characteristics, and the printed subtypes of
    # a creature card that also carries another set's are read off one line
    # here. Splitting them would need the vocabulary; the population is
    # artifact creatures, whose artifact subtypes (Equipment, Vehicle) never
    # appear on one, so the printed set is the creature set.
    return frozenset({override}) if override is not None else printed


def object_creature_types(game, obj, seat=None) -> frozenset[str]:
    """The effective creature types of **any** object (CR 205.3 over CR 109.1).

    A permanent's answer comes out of the layer system, where Conspiracy's first
    sentence already put it (``layer_bridge.collect_type_effects``); every other
    object's comes out of :func:`card_creature_types` above. Two derivations
    because the two kinds of object have nothing in common — one reads a
    per-object layer stack, the other scans a seat's board — but **one place
    they are asked**.

    Dispatched on ``effective_colors``, which is what a ``Permanent`` has and a
    ``CardDefinition`` does not — the same probe ``object_colors.object_colors``
    uses, and for its reason: a token, an animated land and a copy are all
    permanents by that question and no import of the model is needed. Subtypes
    have no such accessor of their own (``computed_types`` is a function), so
    the *colour* accessor is the probe for both modules and the two cannot come
    to disagree about what a permanent is.

    *seat* is ignored for a permanent, which is right rather than lax: the
    layers already know whose it is.
    """
    if obj is None:
        return frozenset()
    if getattr(obj, "effective_colors", None) is not None:
        from .layer_bridge import computed_types

        return frozenset(computed_types(obj)[1])
    return card_creature_types(game, getattr(obj, "card", obj), seat)


__all__ = [
    "card_creature_types",
    "creature_type_override_for_seat",
    "object_creature_types",
]

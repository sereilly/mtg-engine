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

import re
from functools import lru_cache

# ---------------------------------------------------------------------------
# "Every creature type" — a characteristic-defining ability (CR 604.3).
# ---------------------------------------------------------------------------

#: "Mistform Ultimus is every creature type (even if this card isn't on the
#: battlefield)." The self-reference collapsed to "this creature" first, so the
#: card's own name is not part of the pattern; the parenthetical is optional
#: because the normalizer that strips reminder text strips it too, and the
#: sentence means the same thing without it (CR 604.3 makes every CDA work in
#: every zone — the words only say so).
_EVERY_CREATURE_TYPE = re.compile(
    r"^this (?:creature|card) is every creature type"
    r"(?: \(even if this card isn't on the battlefield\))?$"
)


#: The label the grammar's registry claim gives the sentence
#: (``grammar/registries.registry_for_line``). Nothing dispatches on it.
EVERY_CREATURE_TYPE_CLAIM = "object_creature_types"


def every_creature_type_line(line: str, card_name: str | None = None) -> bool:
    """Whether *line* is the "is every creature type" CDA, in full.

    The one reader of the sentence: the support gate, the grammar's registry
    claim and the type seed (:func:`defines_every_creature_type`) all ask it,
    so a wording it cannot read is a card reported unsupported rather than one
    admitted with every creature type missing.
    """
    from .self_reference import _collapse_self_references

    lowered = " ".join(line.strip().lower().split()).rstrip(".")
    return bool(
        _EVERY_CREATURE_TYPE.match(
            _collapse_self_references(lowered, card_name, "this creature")
        )
    )


@lru_cache(maxsize=None)
def defines_every_creature_type(oracle_text: str, card_name: str) -> bool:
    """Whether a card printing *oracle_text* is every creature type.

    CR 702.73a's changeling under its pre-Lorwyn wording (Mistform Ultimus):
    "This object is every creature type." A characteristic-defining ability,
    so it is part of what the card **is** in every zone (CR 604.3) — a hand
    card for amplify, a library card for "search for a Goblin card", a spell
    for "Sliver spells can't be countered", and a permanent, where CR 613.3
    applies it first in layer 4 so any later type-*setting* effect replaces it
    (the card's ruling, 2006-09-25: "if Mistform Ultimus becomes another type
    as the result of a spell or ability, it will lose all its other creature
    types").

    Cached per card text, because it is asked by the type seed on every
    characteristic read.
    """
    if not oracle_text or "every creature type" not in oracle_text.lower():
        return False
    return any(
        every_creature_type_line(line, card_name)
        for line in oracle_text.splitlines()
    )


def every_creature_type_subtypes(
    card_types, subtypes, oracle_text: str, card_name: str
) -> frozenset[str]:
    """*subtypes* with every creature type added when the card's text defines
    them (:func:`defines_every_creature_type`) and it is a creature.

    "Creature" is required for CR 205.3d's reason: an object can have a
    creature type only if it is a creature (or kindred), so a Mistform Ultimus
    an effect had made a noncreature would not be a Goblin. The vocabulary
    (``data/vocabulary/``) is the list, never one spelled here.
    """
    if "creature" not in card_types or not defines_every_creature_type(
        oracle_text, card_name
    ):
        return frozenset(subtypes)
    from .grammar.vocabulary import CREATURE_TYPES

    return frozenset(subtypes) | CREATURE_TYPES


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
        # The text after layers 1 and 3, for ``global_static_sources``' reason
        # exactly: the effective card folds in abilities these very statics
        # grant, so asking it here would make the answer depend on itself.
        static = global_static_for(
            getattr(permanent.card_through_layer_3, "oracle_text", "") or ""
        )
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


# ---------------------------------------------------------------------------
# "Share a creature type" — the relation (CR 205.3m), the twin of
# ``object_colors.share_a_color`` one characteristic over.
# ---------------------------------------------------------------------------


def creature_types(game, obj, seat=None) -> frozenset[str]:
    """The **creature** types of any object — CR 205.3m's list, and nothing
    else on the subtype line.

    :func:`object_creature_types` answers with every subtype the object has,
    which is right for "is it a Goblin?" and wrong for a relation: an animated
    Forest's "forest" and an Equipment's "equipment" are subtypes, but they are
    not creature types, and two Forests do not "share a creature type". So the
    answer is narrowed to the creature-type vocabulary (``data/vocabulary/``),
    never to a list spelled here.

    Through the layers for a permanent (a Mistform that became a Goblin is a
    Goblin; a face-down creature is a blank with none, CR 708.2) and through
    :func:`card_creature_types` for a card (Conspiracy's second sentence), so
    every reader of the relation reads one set.
    """
    from .grammar.vocabulary import CREATURE_TYPES

    return frozenset(
        str(word).lower() for word in object_creature_types(game, obj, seat)
    ) & CREATURE_TYPES


def share_a_creature_type(one, other) -> bool:
    """Whether two creature-type sets share a creature type.

    A non-empty **intersection**, for ``share_a_color``'s reason exactly: an
    object with no creature type shares one with nothing — not even with
    another typeless object — and a creature of several types shares with
    anything having one of them. Takes anything iterable over lowercase type
    words, so a set out of :func:`creature_types`, a list a resolver carried in
    a payload and a frozenset a record kept all ask the one question.
    """
    return bool(frozenset(one or ()) & frozenset(other or ()))


def shares_a_creature_type_with_each(types, anchors) -> bool:
    """Whether *types* shares a creature type with **each** of *anchors*.

    "…a creature card from your hand that shares a creature type with **each
    creature tapped this way**" (Cryptic Gateway). Each anchor is asked on its
    own, so the shared type may differ from one anchor to the next — the card's
    ruling (2022-12-08): an Elf Warrior shares Elf with an Elf Wizard and
    Warrior with a Human Warrior, and qualifies for both.

    One anchor is the plain relation, which is why every reader goes through
    this form. **No anchor is no match**: "each of nothing" is vacuously true,
    and a resolver that lost its record would otherwise admit every object —
    the direction a dropped narrowing must never fail in.
    """
    anchor_sets = [frozenset(anchor or ()) for anchor in anchors]
    if not anchor_sets:
        return False
    mine = frozenset(types or ())
    return all(mine & anchor for anchor in anchor_sets)


def shared_creature_type_count(type_sets) -> int:
    """The size of the largest group of *type_sets* that all share **one**
    creature type.

    "…three or more creatures **that share a creature type**" (Graxiplon). The
    group must have a type in common among all of its members — a Goblin
    Warrior, a Goblin and an Elf Warrior are not three that share one, though
    each pair of them does — so this counts, per creature type, how many of the
    objects have it, and takes the greatest. An object with no creature type
    belongs to no group.
    """
    tally: dict[str, int] = {}
    for types in type_sets:
        for word in frozenset(types or ()):
            tally[word] = tally.get(word, 0) + 1
    return max(tally.values(), default=0)


__all__ = [
    "card_creature_types",
    "creature_type_override_for_seat",
    "creature_types",
    "EVERY_CREATURE_TYPE_CLAIM",
    "defines_every_creature_type",
    "every_creature_type_line",
    "every_creature_type_subtypes",
    "object_creature_types",
    "share_a_creature_type",
    "shared_creature_type_count",
    "shares_a_creature_type_with_each",
]

"""What colour an object is (CR 105) — a card in a zone, a spell, a permanent.

CR 105 asks the question of every object, and CR 613.1e answers it for a
permanent through the layer system. A card in a hand, a graveyard, a library or
the exile has no layer stack of its own, so this engine reads its printed
colours — which is right for every card in the pool but two.

"Nonland permanents you control are white. **The same is true for spells you
control and nonland cards you own that aren't on the battlefield.**" (Celestial
Dawn.) The second sentence is what makes an off-battlefield colour a real
question: with the Dawn out, the Swamp-turned-Plains in play is white *and* so
is the Dark Ritual still in hand, which is what lets it be cast at all under the
Dawn's own spending restriction.

"All cards that aren't on the battlefield, spells, and permanents are
colorless." (Mycosynth Lattice.) The second card, and the wider sentence: every
player's spells and every card in every zone, land cards too, so it needs no
seat to answer (:func:`every_zone_color_override`).

**One reader**, which is the whole point of the module -- and since the ULG
round it answers for a permanent too (:func:`object_colors`), by handing that
half to the layer system. Not because a permanent needed a second reader, but
because half this module's callers hold "a spell **or** a permanent" and cannot
say which: a cost tax reads a card being cast and a permanent whose ability is
being activated, and protection reads a spell's colour and a creature's. A
caller that has to branch on the kind of object is a caller that can forget one
of the two, which is how every site below came to read the printed field.

The colour of a card outside the battlefield used to be read in three places that
could not agree — ``handlers/_filters._card_matches_filter`` (a filter payload),
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

from contextlib import contextmanager
from functools import lru_cache

from .global_statics import global_static_for
from .text_changes import spell_text_card

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
    found = _seat_override(game, seat)
    return None if found is None else found[1]


def _seat_override(game, seat) -> tuple[int, tuple[str, ...]] | None:
    """:func:`color_override_for_seat`'s answer beside its source's timestamp
    (CR 613.7a), which :func:`card_colors` orders it against an every-zone
    static by."""
    index = _seat_index(game, seat)
    if index is None:
        return None

    for permanent in game.controlled_by(index):
        # The text after layers 1 and 3, for ``global_static_sources``' reason
        # exactly: the effective card folds in abilities these very statics
        # grant, so asking it here would make the answer depend on itself —
        # and the printed card would miss a colour word a text change rewrote.
        static = global_static_for(
            getattr(permanent.card_through_layer_3, "oracle_text", "") or ""
        )
        if static is None or static.sets_colors is None:
            continue
        if not static.extends_to_spells_and_cards:
            continue
        symbols = _symbols_of(static.sets_colors)
        if symbols is not None:
            return int(getattr(permanent, "timestamp", 0) or 0), symbols
    return None


def _symbols_of(words) -> tuple[str, ...] | None:
    """A static's colour words as symbols, or None when one is not a colour.

    Completeness rather than truth, for the reason ``sets_colors`` is
    ``None`` when a static says nothing about colour: ``()`` is CR 105.2c's
    colourless and a real answer, so "did anything survive the map?" is the
    wrong question -- a printed word this map could not read would fall
    through to the *printed* colours, which is a hand recoloured by half a
    sentence.
    """
    symbols = tuple(
        _COLOR_WORD_SYMBOLS[word] for word in words if word in _COLOR_WORD_SYMBOLS
    )
    return symbols if len(symbols) == len(words) else None


def every_zone_color_override(game) -> tuple[str, ...] | None:
    """The colours **every** spell and every card off the battlefield is set
    to, whoever owns it, or None (CR 613.1e over CR 109.1's objects).

    "All cards that aren't on the battlefield, spells, and permanents are
    colorless." (Mycosynth Lattice.) The sentence names no seat, so it is
    read off every battlefield, and it names "all cards", so a land card is
    reached too. Derived on every call for :func:`color_override_for_seat`'s
    reason.
    """
    found = _every_zone_override(game)
    return None if found is None else found[1]


def _every_zone_override(game) -> tuple[int, tuple[str, ...]] | None:
    """:func:`every_zone_color_override` beside its source's timestamp. Of
    several such statics the newest sets the colours (CR 613.7a, CR 105.3)."""
    if game is None or not hasattr(game, "all_permanents"):
        return None
    answer: tuple[int, tuple[str, ...]] | None = None
    for permanent in game.all_permanents():
        symbols = _every_zone_colors(
            getattr(permanent.card_through_layer_3, "oracle_text", "") or ""
        )
        if symbols is None:
            continue
        stamp = int(getattr(permanent, "timestamp", 0) or 0)
        if answer is None or stamp >= answer[0]:
            answer = (stamp, symbols)
    return answer


@lru_cache(maxsize=None)
def _every_zone_colors(oracle_text: str) -> tuple[str, ...] | None:
    """The colours *oracle_text*'s every-zone static sets, or None. Kept per
    text: the answer is the text's, and every colour read off a card asks it
    of every permanent."""
    if "aren't on the battlefield" not in oracle_text.lower():
        return None

    static = global_static_for(oracle_text)
    if static is None or not static.colors_every_zone or static.sets_colors is None:
        return None
    return _symbols_of(static.sets_colors)


def card_colors(game=None, card=None, seat=None) -> tuple[str, ...]:
    """The effective colours of *card* while *seat* owns or controls it.

    Falls back to the printed colours whenever the caller cannot say whose card
    it is or there is no game to ask, which is what every caller did before this
    module existed — so a site that has not been taught the seat keeps exactly
    the behaviour it had rather than guessing.

    A **land card is not recoloured by a seat's static**: Celestial Dawn's
    sentence says "nonland cards", and a land in a hand is one whatever the
    battlefield has done to the lands already on it.

    **An every-zone static needs no seat** (Mycosynth Lattice, "All cards that
    aren't on the battlefield, spells, and permanents are colorless"): it
    reaches every player's cards and spells, lands among them, so a caller
    holding a game and no seat is answered by it all the same. Where a seat's
    static and an every-zone one both reach a card, the newer source wins
    (CR 613.7a): each *sets* the colours (CR 105.3).
    """
    printed = tuple(getattr(card, "colors", ()) or ())
    if card is None:
        return printed
    candidates = [_every_zone_override(game)]
    if "land" not in (getattr(card, "type_line", "") or "").lower():
        candidates.append(_seat_override(game, seat))
    found = [candidate for candidate in candidates if candidate is not None]
    if not found:
        return printed
    return max(found, key=lambda candidate: candidate[0])[1]


def _names_the_spell(item, card) -> bool:
    """Whether *card* is how a reader holding only a card names the spell
    *item*: its printed card, or what it says now (CR 612,
    ``text_changes.spell_text_card`` — memoised by the changes, so one text
    is one object). Never an ability, whose ``card`` is its source's."""
    if item is None or card is None or getattr(item, "is_ability", True):
        return False
    if getattr(item, "card", None) is card:
        return True

    return spell_text_card(item) is card


def spell_colors(game=None, card=None, seat=None) -> tuple[str, ...]:
    """The colours of *card* **as the spell it is now**: where *card* names a
    stack object this game can say is the one asked about, that object's own
    colours (``Game._stack_item_colors`` — a Lace's recolour on the object,
    then the controller's board), else :func:`card_colors`.

    A spell reaches protection and the damage paths as its printed card, which
    records nothing an effect did to it on the stack: Purelace made a Lightning
    Bolt white, and the Bolt — read through :func:`card_colors` — went on being
    red, dealt its 3 to a Black Knight (protection from white, CR 702.16b/e)
    and was stopped by protection from red. Every copy of a card in a game is
    one ``CardDefinition``, so identity names a spell only where the game says
    which object is meant, and two places say it:

    * the object whose targets are being **judged** from outside its own
      resolution (``Game.judged_stack_items``, :func:`judging_targets_of`) —
      a retarget's candidates (CR 115.7a), a copy's new targets (CR 707.10c),
      asked while some *other* object resolves. First, because a copy made
      during its original's resolution (Chain Lightning) shares the original's
      card and is not the original: the Lace that made the original white is
      not a copiable value (CR 707.2), and Fork's copy is red where its
      original was not;
    * the object **resolving** (``Game.resolving_items``' last entry).
    """
    if game is not None:
        for items in (
            getattr(game, "judged_stack_items", None),
            getattr(game, "resolving_items", None),
        ):
            if items and _names_the_spell(items[-1], card):
                return tuple(game._stack_item_colors(items[-1]))
    return card_colors(game, card, seat)


@contextmanager
def judging_targets_of(game, item):
    """While the block runs, a bare card naming *item* is *item*
    (:func:`spell_colors`): the legal targets being enumerated are the stack
    object's, judged by what it is now. Pushed by
    ``_enumerate_targets(stack_item=…)``; a no-op for ``None``."""
    if item is None or game is None:
        yield
        return
    judged = game.judged_stack_items
    judged.append(item)
    try:
        yield
    finally:
        judged.pop()


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

    # A spell on the stack is asked what it says (CR 612, ``spell_text_card``);
    # a bare card is its own answer.
    return card_colors(
        game, spell_text_card(obj) if hasattr(obj, "card") else obj, seat,
    )


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
    "every_zone_color_override",
    "colors_among_described",
    "is_multicolored", "judging_targets_of", "object_colors", "of_each_color",
    "share_a_color",
]

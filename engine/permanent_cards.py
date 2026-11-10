"""Which cards can be put onto the battlefield (CR 110.4a), and what happens to
one that cannot (CR 400.4a).

    110.4a The term "permanent card" is used to refer to a card that could be
    put onto the battlefield. Specifically, it means an artifact, battle,
    creature, enchantment, land, or planeswalker card.

    400.4a If an instant or sorcery card would enter the battlefield, it
    remains in its previous zone.

CR 110.4 says why this is a question at all once Kindred cards exist: "Some
kindred cards can enter the battlefield and some can't, depending on their
other card types." A "Goblin card" is any card with the subtype (CR 205.3m,
308.2) — a Kindred Instant — Goblin among them — so every road that puts a
described card onto the battlefield out of a library, a graveyard, a hand or
an exile can be handed one, and every such road asks :func:`is_permanent_card`
**before it takes the card out of its zone**: "remains in its previous zone"
is a card that never left, so nothing that watches a card leave a zone sees
it, and it keeps its place in an ordered pile. The road then goes on doing as
much as it can (CR 609.3) — the library is still shuffled, the rest of a
revealed pile still goes where the card sends it.

**One predicate**, where there were four spellings of it: ``handlers/hand``'s
``_PERMANENT_CARD_TYPES`` check before an entry (the shape), its
``primary_type in _PERMANENT_TYPES`` reading of "permanent card" for a pick
(which ``primary_type`` answers with one word of a type line, and which left
out battles), and Dodecapod's ``primary_type in ("instant", "sorcery")``.

The printed type line, through ``search_filters.card_has_any_type``: a card
outside the battlefield has no computed characteristics (CR 613.1), and a
split card off the stack is its whole card (CR 709.4) — "Instant // Instant",
no permanent type. A modal double-faced card would ask its front face instead
(CR 712.14b); no such layout is in the pool (``faces.CAST_FACE_LAYOUTS``).
A face-down entry (manifest, CR 701.40f) is a different question about a
different object, and nothing in the pool makes one out of a card in a zone.

``tests/engine/test_kg5_kindred_entry_roads.py`` holds every caller of the
battlefield funnel to this question: each asks it, or is listed with the
reason its card is a permanent card by construction.

**And the "can't" (CR 614.17), asked by the same roads at the same moment.**

    614.17 Some effects state that something can't happen. These effects
    aren't replacement effects, but follow similar rules.

Worms of the Earth's "Lands can't enter the battlefield" stops a land card
the same way 400.4a stops an instant, and its ruling (2004-10-04) says the
same thing about where the card is: "an effect that 'puts a land onto the
battlefield' won't do anything, and the land will stay where it is" — "You'll
still do everything else the spell or ability tells you to do, such as
shuffle the library." So :func:`stays_out_of_battlefield` answers both
questions, one ask per road: the card is no permanent card, or an effect says
it can't enter (:func:`cant_enter_sources`, the registry's own
``cant_enter_battlefield`` predicates — the ones the battlefield funnel
applies, ``ZoneFunnelsMixin._begin_entry``). Asked at the funnel alone, the
answer came after the road had taken the card out of its zone, and a Show and
Tell'd, searched-for or reanimated land went to no zone at all.

The funnel still asks it, of the permanent as it would exist on the
battlefield (CR 614.17d, after the board's statics are folded on): that is
the answer for an object no zone holds — a token, a spell resolving — and for
whatever a road could not know beforehand. A card in a zone is asked here
by its printed types: no effect in the pool makes a land card enter as
anything but a land, or another card enter as a land, except a copy chosen
as it enters (CR 707.5), which no road can know before the entry state.
``tests/engine/test_kg5_entry2_cant_enter_roads.py`` holds every road that
can carry a land out of a zone to asking it.
"""

from __future__ import annotations

from .search_filters import card_has_any_type

#: The rule a card that stays out is logged under.
CANT_ENTER_RULE = "400.4a"


def is_permanent_card(card) -> bool:
    """Whether *card* could be put onto the battlefield (CR 110.4a): it has an
    artifact, battle, creature, enchantment, land or planeswalker type.

    An instant or sorcery card has none, and neither has a Kindred instant or
    sorcery (CR 308.1: a kindred card's other type is the one that counts);
    a Kindred artifact or enchantment has one.
    """
    # Imported here: the handlers import this module while ``engine.grammar``
    # is still being initialised (its package imports the lowering, which
    # reaches back into the handlers).
    from .grammar.vocabulary import PERMANENT_CARD_TYPES

    return card is not None and card_has_any_type(card, PERMANENT_CARD_TYPES)


def cant_enter_sources(game, card, seat: int | None) -> list[str]:
    """The names of what says *card* can't enter the battlefield (CR 614.17)
    under *seat*'s control — empty when nothing does.

    Asked of the registry's ``cant_enter_battlefield`` predicates over the
    event the funnel itself raises (``ZoneFunnelsMixin._begin_entry``), with a
    provisional permanent of the card standing for the one that would enter:
    one set of predicates, asked before a road takes the card and applied at
    the funnel. The provisional object takes no id and no timestamp from the
    game's counters (CR 400.7: nothing has entered)."""
    from .effect_ordering import source_names
    from .models import Permanent
    from .replacements.registry import replacement_candidates

    if card is None or not getattr(game, "players", None):
        return []
    if seat is None or not 0 <= seat < len(game.players):
        seat = 0
    event = {
        "permanent": Permanent(card=card, permanent_id=0, timestamp=0),
        "controller_index": seat,
        "was_cast": False,
        "player": game.players[seat],
    }
    names: list[str] = []
    for candidate in replacement_candidates("cant_enter_battlefield", game, event):
        if not candidate.applies(game, event):
            continue
        sources = candidate.sources(game, event) if candidate.sources else ()
        for name in source_names(sources) or [candidate.label]:
            if name not in names:
                names.append(name)
    return names


def stays_out_of_battlefield(
    game, card, owner, zone: str, *, shown: str | None = None,
    seat: int | None = None,
) -> bool:
    """Ask CR 400.4a and CR 614.17 of *card* on its way out of *owner*'s
    *zone*: True — and logged — when it cannot enter the battlefield, so the
    caller leaves it where it is; False when it can, and nothing is written.

    *shown* is the name the table may be told (``game.log`` is every seat's):
    the card's own by default, which is right for a graveyard, a revealed card
    and a card a pick showed; a caller taking a card out of a hidden zone
    unrevealed passes "a card".

    *seat* is the seat it would enter under, for a "can't" that names one;
    its owner's by default.
    """
    who = getattr(owner, "name", None) or "its owner"
    name = shown if shown is not None else card.name
    if not is_permanent_card(card):
        game.log.append(
            f"{name} can't enter the battlefield and stays in {who}'s {zone} "
            f"({CANT_ENTER_RULE})"
        )
        return True
    if seat is None and owner is not None:
        seat = next(
            (index for index, player in enumerate(game.players) if player is owner),
            None,
        )
    stopping = cant_enter_sources(game, card, seat)
    if not stopping:
        return False
    game.log.append(
        f"{name} can't enter the battlefield and stays in {who}'s {zone} "
        f"({', '.join(stopping)})"
    )
    return True

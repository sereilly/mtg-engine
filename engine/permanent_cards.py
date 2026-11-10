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


def stays_out_of_battlefield(game, card, owner, zone: str, *, shown: str | None = None) -> bool:
    """Ask CR 400.4a of *card* on its way out of *owner*'s *zone*: True — and
    logged — when it cannot enter the battlefield, so the caller leaves it
    where it is; False when it can, and nothing is written.

    *shown* is the name the table may be told (``game.log`` is every seat's):
    the card's own by default, which is right for a graveyard, a revealed card
    and a card a pick showed; a caller taking a card out of a hidden zone
    unrevealed passes "a card".
    """
    if is_permanent_card(card):
        return False
    who = getattr(owner, "name", None) or "its owner"
    game.log.append(
        f"{shown if shown is not None else card.name} can't enter the "
        f"battlefield and stays in {who}'s {zone} ({CANT_ENTER_RULE})"
    )
    return True

"""Where a card sits in a graveyard, and what "above it" means (CR 404.3).

A graveyard is an **ordered** zone: CR 404.3 lets any player look through one in
any order, and CR 400.4's "a card put into a zone goes on top" is what gives
that order a meaning at all. Three cards in the pool print a sentence about it —
Death Spark and Krovikan Horror ("with a creature card **directly** above it"),
Nether Shadow ("with three or more creature cards above it") — and "above"
means *later in the list*, because a card put into a graveyard more recently is
appended.

One home for that reading, because two readers need it and they need it at
different moments: the intervening-if evaluator asks whether the ability may
fire at all (CR 603.4, checked once when the trigger would fire and again as it
resolves), and the fire site asks the same question a card at a time. A second
copy of the arithmetic is how "above" comes to mean two different things.

**Positions, not a card.** Every function here answers with graveyard *indices*
rather than with the card, and that is not scaffolding. A graveyard holds
``CardDefinition`` objects and ``load_cards`` dedupes by ``oracle_id``, so two
copies of one card in one graveyard are the **same Python object** — a caller
handed only the card cannot say which copy satisfied the clause, and an identity
filter over the list removes both. ``phases/upkeep_step._graveyard_return_candidates``
carries the same index for the same reason, and documents the five cards that
went missing before it did.
"""

from __future__ import annotations

from typing import Any

from .layer_bridge import printed_shape


def _is_type(card: Any, wanted: str) -> bool:
    """Whether *card* is printed with the *wanted* card type.

    Through ``printed_shape`` rather than ``primary_type``: CR 205.2a gives a
    card **every** type printed on it, and the collapsed word makes "Artifact
    Creature — Construct" a creature and not an artifact. A graveyard is exactly
    where that matters — nothing there is a permanent, so the layers cannot be
    asked and the printed line is the whole answer.
    """
    types, _subtypes = printed_shape(card)
    return wanted in types


def cards_above(graveyard: list, index: int) -> list:
    """The cards above the one at *index* — CR 404.3's order, later is higher."""
    return graveyard[index + 1:]


def satisfies_above(graveyard: list, index: int, spec: dict) -> bool:
    """Whether the card at *index* has what *spec* says above it.

    *spec* is the lowered ``self_in_graveyard_with_cards_above`` payload:
    ``card_type``, ``count``, ``op`` ("eq"/"ge") and ``directly``.

    "Directly above" is a different question from a count of one, not a
    narrowing of it, which is why it is its own branch: a graveyard holding a
    land on top of the card and a creature above that has one creature card
    above it and nothing directly above it. Death Spark and Nether Shadow
    disagree about exactly that board.
    """
    wanted_type = str(spec.get("card_type", "creature"))
    above = cards_above(graveyard, index)
    if spec.get("directly"):
        return bool(above) and _is_type(above[0], wanted_type)
    count = sum(1 for card in above if _is_type(card, wanted_type))
    wanted = int(spec.get("count", 1))
    return count >= wanted if spec.get("op") == "ge" else count == wanted


def positions_satisfying(graveyard: list, card: Any, spec: dict) -> list[int]:
    """Every index of *graveyard* holding *card* whose position satisfies *spec*.

    Several, in principle: two copies of one card are the same object, and the
    one lower in the pile may qualify while the one on top does not. The list is
    the honest answer — one ability per card in the zone (CR 113.6b), so a
    caller that fires per position fires the right number of times, and a caller
    that only needs a yes/no can ask whether it is empty.
    """
    return [
        index
        for index, held in enumerate(graveyard)
        if held is card and satisfies_above(graveyard, index, spec)
    ]

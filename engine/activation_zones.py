"""Which zone an activated ability functions in (CR 113.6).

CR 113.6's default is "abilities of an object function only while that object is
on the battlefield", and the engine had that default *implicitly* — every
activation path but two started from a ``Permanent``. The two exceptions each
carried their own hand-rolled test:

* ``Game.activate_from_hand`` asked ``ability.cost.discard_self``;
* ``Game.activate_from_graveyard`` asked the instruction's ``functions_from``
  payload key.

Two readers of one question, and **neither of them had a negative half**. An
ability that functions only from a hand was still offered on the battlefield by
``usable_activated_abilities``, still chosen by ``queue_permanent_ability``, and
still proposed by the AI's activation loop — so M21's Waker of Waves, a shipped
card, could stand on the battlefield and activate "{1}{U}, **Discard this
card**: Look at the top two cards of your library…" every turn, discarding
nothing and staying where it was. Not a crash and not a missing ability: an
ability that works *more often than the card allows*.

Urza's Saga is what makes that unaffordable rather than merely wrong. Cycling
(CR 702.29) compiles to exactly that cost on 34 cards, six of them lands and
eight of them creatures, so without this module the set ships fourteen
permanents with a free repeatable "draw a card" printed on them.

**The rule is about costs, not about the keyword.** CR 113.6j: *"An object's
activated ability that has a cost that can't be paid while the object is on the
battlefield functions from any zone in which its cost can be paid."* Discarding
a card is moving it from a hand to a graveyard (CR 701.9a), so an ability whose
cost discards the card it is printed on can be paid in a hand and nowhere else.
That is derived here from the compiled cost, so it reaches every card printed
that way and names none — cycling, Waker of Waves and whatever prints the shape
next all get the same answer.

CR 113.6b — an ability that *states* its zone — outranks the cost read, because
a printed sentence is the card's own claim and the cost read is an inference
from it. ``engine/activation_restrictions.py`` and
``engine/grammar/lowering/_bound_returns.py`` are where that statement is read;
this module only reads the key they stamp.
"""

from __future__ import annotations

BATTLEFIELD = "battlefield"
HAND = "hand"
GRAVEYARD = "graveyard"


def ability_functions_from(ability) -> str:
    """The zone *ability* — a ``ParsedActivatedAbility`` — functions in.

    One of :data:`BATTLEFIELD`, :data:`HAND` or :data:`GRAVEYARD`, and the
    single answer every activation path takes: the two hand-written gates this
    replaced could disagree with the list the picker was built from, and did.
    """
    instruction = getattr(ability, "instruction", None)
    payload = getattr(instruction, "payload", None) or {}
    # CR 113.6b: an ability that states which zones it functions in functions
    # only from those zones. Stated wins over inferred.
    stated = payload.get("functions_from")
    if stated:
        return str(stated)
    # CR 113.6j, reached through CR 701.9a: "Discard this card" moves the card
    # from its owner's *hand*, so the cost is payable there and nowhere else.
    if getattr(getattr(ability, "cost", None), "discard_self", False):
        return HAND
    return BATTLEFIELD


def functions_from_zone(ability, zone: str) -> bool:
    """Whether *ability* may be activated from *zone*."""
    return ability_functions_from(ability) == zone


__all__ = [
    "BATTLEFIELD",
    "GRAVEYARD",
    "HAND",
    "ability_functions_from",
    "functions_from_zone",
]

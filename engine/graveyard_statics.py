"""Static abilities that function from a graveyard (CR 113.6b, CR 611.3b).

"As long as this card is in your graveyard and you control a Mountain,
creatures you control have haste." (Anger, and Judgment's four other
Incarnations.) "As long as this card is in your graveyard, lands you control
have "{T}: Add {G} or {W}."" (Riftstone Portal.)

CR 113.6 says abilities of a permanent usually function only on the
battlefield, and CR 113.6b is the exception these print: "an ability that
states which zones it functions in functions only from those zones." CR 611.3b
then says what a static ability's effect does about it — it "applies at all
times that the permanent generating it is on the battlefield **or the object
generating it is in the appropriate zone**." Every board-wide static this
engine applies was gathered from the battlefield (``all_permanents``), so a
static stated to work from a graveyard had no place to be found. This module is
that place, for every such static and not per card:

* **which instructions function from a graveyard** — the ``functions_from``
  key, the same derived fact ``engine/events.py`` reads for a graveyard
  trigger and ``engine/activation_zones.py`` for a graveyard activation. For a
  static it is stamped by the anthem lowering (``grammar/statics.py``) from the
  condition that states the zone, because there the condition is the only place
  the card names one;
* **where each one is** — a :class:`GraveyardSource`: the card, the pile it is
  in, its position (CR 404.1) and the timestamp it got as it entered the zone
  (CR 613.7d, ``graveyard_order.graveyard_arrival_stamps``), which is the
  timestamp its effect carries (CR 613.7a). Anger's ruling (2004-10-04) says
  so in as many words: "The timestamp for the 'in your graveyard' ability is
  set at the time that this card goes to your graveyard, regardless of whether
  you control a Mountain at that time."
* **whether it is still there** — :func:`source_in_its_graveyard`, the answer
  ``static_bonuses.conditional_static_holds`` gives the printed "this card is
  in your graveyard" clause. A permanent asked the same clause answers no,
  which is what keeps an Incarnation on the battlefield from granting anything
  (CR 113.6b again: *only* from those zones).

**A GraveyardSource is not a permanent and does not pretend to be one.** It has
no controller (CR 108.4a: "if anything asks for the controller of a card that
doesn't have one … use its owner instead", which is :attr:`seat`), no
``permanent_id``, no counters and no metadata. The readers that take a source
ask :func:`static_source_seat` for its seat, and the condition evaluator asks
every clause but the zone one with no source at all — so a clause that would
need a permanent to measure "another" or "its" against answers no rather than
reading a stand-in. The lowering refuses those clauses on a graveyard static
before any of that is reached.

The consumer is ``LordBuffsMixin._recalculate_lord_buffs`` (layer 6's grants
and layer 7c's deltas), which rebuilds every channel it writes on each
recompute — so the card leaving the graveyard, or the land condition failing,
is the absence of a contribution on the next pass with nothing to undo
(CR 611.3a).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .activation_zones import GRAVEYARD

#: The payload key a zone-stating instruction carries — ``events.FUNCTIONS_FROM``'s
#: spelling, repeated rather than imported because ``engine/events.py`` sits
#: above the modules that ask this (``static_bonuses`` among them).
FUNCTIONS_FROM = "functions_from"

#: The instruction kinds a static that functions from a graveyard may be, by
#: the reader that gathers each from there. Only the board-wide anthem
#: (``lord_buff``) has one: ``_recalculate_lord_buffs``. Any other static
#: stamped ``functions_from: graveyard`` would be an instruction nothing
#: gathers from the zone it states — which is why the lowering only stamps
#: this one.
GRAVEYARD_STATIC_KINDS: frozenset[str] = frozenset({"lord_buff"})


@dataclass(frozen=True)
class GraveyardSource:
    """A card in a graveyard whose static ability functions there."""

    card: Any
    #: The graveyard's owner — CR 404.1 files a card in its owner's graveyard,
    #: and CR 108.4a makes the owner the controller of a card nobody controls.
    #: So this is "you" in "creatures **you** control".
    seat: int
    #: Its position in that pile, bottom first (CR 404.1's order). Positions,
    #: not identity: two copies of a card are one ``CardDefinition`` object
    #: (``engine/graveyard_order.py``), so the index is the only thing that
    #: tells them apart — and each is its own source (CR 113.6b, one ability
    #: per card in the zone).
    index: int
    #: CR 613.7d's timestamp, from when the card entered the zone.
    timestamp: int


def functions_from_graveyard(instruction) -> bool:
    """Whether *instruction* states it functions from a graveyard."""
    payload = getattr(instruction, "payload", None) or {}
    return payload.get(FUNCTIONS_FROM) == GRAVEYARD


def graveyard_static_instructions(card) -> tuple:
    """*card*'s compiled static instructions that function from a graveyard.

    The text is asked first, and only to skip a compile: CR 113.6b's statement
    is printed, so a card whose text never says "graveyard" has none — and
    nearly every card in nearly every pile is one, on a pass the recompute
    makes at every resolution seam.
    """
    if "graveyard" not in (getattr(card, "oracle_text", None) or "").lower():
        return ()
    from .oracle import compile_card_oracle

    return tuple(
        instruction
        for instruction in compile_card_oracle(card).instructions
        if instruction.kind in GRAVEYARD_STATIC_KINDS
        and functions_from_graveyard(instruction)
    )


def graveyard_static_sources(game) -> list[tuple[GraveyardSource, Any]]:
    """Every ``(source, instruction)`` a graveyard holds, seat by seat and
    bottom to top.

    One entry per **position**, so two Angers in one pile are two sources
    (CR 611.3a: each ability applies on its own) with two timestamps. The pile's
    arrival stamps are read only for a seat whose graveyard holds such a card,
    because reading them keeps the record in step with the pile.
    """
    from .graveyard_order import graveyard_arrival_stamps

    found: list[tuple[GraveyardSource, Any]] = []
    for seat, player in enumerate(game.players):
        pile = list(player.graveyard)
        statics = [graveyard_static_instructions(card) for card in pile]
        if not any(statics):
            continue
        stamps = graveyard_arrival_stamps(player)
        for index, (card, instructions) in enumerate(zip(pile, statics)):
            for instruction in instructions:
                found.append((
                    GraveyardSource(
                        card=card, seat=seat, index=index,
                        timestamp=stamps[index],
                    ),
                    instruction,
                ))
    return found


def source_in_its_graveyard(game, source, spec: dict) -> bool:
    """Whether *source* is in its owner's graveyard where *spec* says.

    *spec* is the lowered "this card is in your graveyard [with … above it]"
    payload (``self_in_graveyard_with_cards_above``), asked through the one
    reader of what "above" means (``graveyard_order.satisfies_above``) — so a
    static printing a position would be answered by the same arithmetic a
    trigger's intervening-if is.

    A permanent is never in a graveyard, so it answers no: an Incarnation on
    the battlefield grants nothing (CR 113.6b). A GraveyardSource whose card
    has left its position since it was gathered answers no as well.
    """
    from .graveyard_order import satisfies_above

    if not isinstance(source, GraveyardSource):
        return False
    players = getattr(game, "players", ())
    if not 0 <= source.seat < len(players):
        return False
    pile = players[source.seat].graveyard
    if not 0 <= source.index < len(pile) or pile[source.index] is not source.card:
        return False
    return satisfies_above(pile, source.index, spec)


def static_source_seat(game, source) -> "int | None":
    """The seat a static's "you" is measured from (CR 109.5).

    A permanent's controller, through the control seam; a card in a
    graveyard's owner (CR 108.4a).
    """
    if isinstance(source, GraveyardSource):
        return source.seat
    return game.controller_index_of(source)


__all__ = [
    "FUNCTIONS_FROM",
    "GRAVEYARD_STATIC_KINDS",
    "GraveyardSource",
    "functions_from_graveyard",
    "graveyard_static_instructions",
    "graveyard_static_sources",
    "source_in_its_graveyard",
    "static_source_seat",
]

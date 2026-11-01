"""What else a seat may pay mana for — the demand side of a payment.

A payment plan answers two questions: whether a cost can be paid, and **which
sources pay it**. The first is about the cost alone. The second is about
everything else the payer may still want to pay for, because a source tapped
now is a source gone for the rest of the turn: a {3} paid with three Plains
off four Plains and three Mountains leaves Exalted Angel's {2}{W}{W} turn-up
unpayable, where the Mountains would have left it payable (Onslaught's
Phase 5). ``mana_payment._sparing_choice`` is the preference every planner
shares; this is what it is a preference *for*.

The wants are symbol dicts, read off what the seat itself can see (CR 400.2:
its own hand; CR 708.5: its own face-down permanents) and nothing else — so
the AI's rehearsal copy, which conceals another seat's hand
(``ai_rehearsal.conceal_from``), reads the same wants of the seat it plans
for, and the web's auto-tap reads a person's own hand on their behalf:

* each spell in the hand — each half of a split card (CR 709.3) — at its
  printed mana cost, {X} as 0 (CR 107.3g);
* each ability that works from the hand (cycling, CR 702.29a) at its mana;
* each face-down permanent's morph cost, the price of turning it face up
  (CR 702.37e);
* each activated ability of a permanent the seat controls that is not a mana
  ability (CR 605.1a), at its mana — one whose {T} is already spent excepted.

Printed costs, not what the cast path would charge after taxes and
reductions: a want only has to say which colours the seat will be asked for,
and a tax is generic. A land in the hand wants nothing (CR 305.1: a land is
played, not paid for). The card being paid for is left out once
(*paying_for*): a spell on its way to the stack, or a card in the hand
paying for its own cycling, is not a want the payment it is making competes
with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .activation_zones import HAND
from .face_down import face_up_morph_cost, is_face_down
from .faces import castable_faces
from .mana_payment import is_mana_ability, mana_cost_x_as_zero
from .oracle import compile_card_oracle
from .targeting import usable_activated_abilities

if TYPE_CHECKING:
    from .game import Game


def mana_wants(game: "Game", seat: int, *, paying_for=None) -> "tuple[dict[str, int], ...]":
    """Every cost *seat* may still want to pay mana for, as symbol dicts —
    see the module's note. *paying_for* is a card (or a face of one) the
    payment being planned is for, left out of the hand once."""
    player = game.players[seat]
    wants: list[dict[str, int]] = []
    skipped = paying_for is None
    whole = getattr(paying_for, "face_of", None) or paying_for
    for card in player.hand:
        if not skipped and (card is paying_for or card is whole):
            skipped = True
            continue
        for face in castable_faces(card):
            if face.primary_type == "land":
                continue
            cost = mana_cost_x_as_zero(face.mana_cost or "")
            if cost:
                wants.append(cost)
        for ability in usable_activated_abilities(compile_card_oracle(card), zone=HAND):
            _add_ability_cost(wants, ability)
    for permanent in game.controlled_by(seat):
        if is_face_down(permanent):
            cost = mana_cost_x_as_zero(face_up_morph_cost(permanent) or "")
            if cost:
                wants.append(cost)
            continue
        for ability in usable_activated_abilities(compile_card_oracle(permanent.effective_card)):
            if ability.cost is not None and ability.cost.requires_tap and permanent.tapped:
                continue
            _add_ability_cost(wants, ability)
    return tuple(wants)


def _add_ability_cost(wants: list, ability) -> None:
    cost = getattr(ability, "cost", None)
    if cost is None or ability.instruction is None or is_mana_ability(ability.instruction):
        return
    mana = {symbol: int(amount) for symbol, amount in (cost.mana or {}).items() if int(amount or 0) > 0}
    if mana:
        wants.append(mana)


__all__ = ["mana_wants"]

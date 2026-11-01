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

The first three are a card's own price — a card held back that does nothing
until it is paid for — and the last is an ability that can wait, so they are
handed over as two tiers (``mana_payment.PaymentWants``): where two choices
keep as many wants payable together, the one keeping more cards wins.

Printed costs, not what the cast path would charge after taxes and
reductions: a want only has to say which colours the seat will be asked for,
and a tax is generic. A land in the hand wants nothing (CR 305.1: a land is
played, not paid for). The card being paid for is left out once
(*paying_for*): a spell on its way to the stack, or a card in the hand
paying for its own cycling, is not a want the payment it is making competes
with.

**What it brings is** (:func:`wants_brought_by`). A card cast face down is
paid for twice: {3} now (CR 702.37a), and its morph cost later, as the special
action that turns it face up (CR 702.37e) — out of whatever the {3} left. So
the face-down spell the cast path casts (CR 702.37c: the 2/2, its real card
riding on it as ``face_down_of``) is read as the card it hides leaving the
hand, and its turn-up as a want of the first tier, the same want it is the
moment it lands. Read as the 2/2, the Angel was no card in the hand and
wanted its printed {4}{W}{W}; read as itself, it was left out and wanted
nothing — and on four Plains and three Mountains both readings tapped three
Plains for the {3} (Onslaught's Phase 5, which round kg2's census never
asked: its want was always a *second* card).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .activation_zones import HAND
from .face_down import face_up_morph_cost, hidden_card, is_face_down, morph_cost
from .faces import castable_faces
from .mana_payment import PaymentWants, is_mana_ability, mana_cost_x_as_zero
from .oracle import compile_card_oracle
from .targeting import usable_activated_abilities

if TYPE_CHECKING:
    from .game import Game


def mana_wants(game: "Game", seat: int, *, paying_for=None) -> PaymentWants:
    """Every cost *seat* may still want to pay mana for, as symbol dicts in
    two tiers — see the module's note. *paying_for* is a card (or a face of
    one) the payment being planned is for, left out of the hand once."""
    player = game.players[seat]
    wants: list[dict[str, int]] = list(wants_brought_by(paying_for))
    abilities: list[dict[str, int]] = []
    skipped = paying_for is None
    whole = (
        hidden_card(paying_for) or getattr(paying_for, "face_of", None) or paying_for
    )
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
            _add_ability_cost(abilities, ability)
    return PaymentWants(cards=tuple(wants), abilities=tuple(abilities))


def wants_brought_by(paying_for) -> "tuple[dict[str, int], ...]":
    """What the card a payment is for will still want paid once this payment
    is made, as symbol dicts of the cards' tier — see the module's note.

    A face-down spell (CR 702.37c) brings its turn-up: the morph cost of the
    card it hides (CR 702.37e), {X} as 0 (CR 107.3d lets the player choose
    it). Nothing else is one today: every other cost a cast carries is paid
    as it is cast (CR 601.2f-h), and an echo or a cumulative upkeep is paid
    after the next untap step. A permanent (an ability being paid for) or a
    face-up card brings nothing."""
    hidden = hidden_card(paying_for)
    if hidden is None:
        return ()
    turn_up = mana_cost_x_as_zero(morph_cost(hidden) or "")
    return (turn_up,) if turn_up else ()


def _add_ability_cost(wants: list, ability) -> None:
    cost = getattr(ability, "cost", None)
    if cost is None or ability.instruction is None or is_mana_ability(ability.instruction):
        return
    mana = {symbol: int(amount) for symbol, amount in (cost.mana or {}).items() if int(amount or 0) > 0}
    if mana:
        wants.append(mana)


__all__ = ["mana_wants", "wants_brought_by"]

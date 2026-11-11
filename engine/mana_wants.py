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
its own hand; CR 708.5: its own face-down permanents; the public graveyards
and exile) and nothing else — so the AI's rehearsal copy, which conceals
another seat's hand (``ai_scratch_copy.conceal_from``), reads the same wants of
the seat it plans for, and the web's auto-tap reads a person's own hand on
their behalf:

* each spell in the hand — each half of a split card (CR 709.3) — at its
  printed mana cost, {X} as 0 (CR 107.3g);
* each ability that works from the hand (cycling, CR 702.29a) at its mana;
* each face-down permanent's morph cost, the price of turning it face up
  (CR 702.37e);
* each card the seat may cast from **outside its hand** under a permission
  (CR 601.3: a flashback card in its graveyard, CR 702.34a; a card an effect
  lets it play from exile or the top of its library), at the permission's
  price — its required alternative cost (CR 118.9b), nothing for a waiver,
  else the mana cost (``ai_weighed_cast.permitted_casts``, the list an AI seat
  is offered and a person's zone badges are built from);
* each activated ability of a permanent the seat controls that is not a mana
  ability (CR 605.1a), at its mana — one whose {T} is already spent excepted.

The first four are a card's own price — a card held back that does nothing
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

**And what a face-up card leaves behind** (:func:`wants_left_behind`), which
only the payment's caller can say — whether the payment is a cast:

* a **permanent spell** brings its own activated abilities once it resolves
  (the abilities' tier): the {R} of a Shivan Dragon's firebreathing is the
  next thing its caster pays for, and a payment blind to it spent the
  Mountains on the Dragon's generic. A {T} ability of a creature without
  haste is left out — it cannot be activated this turn (CR 302.6);
* an **instant or sorcery with flashback** that leaves the hand brings its
  flashback cost (the cards' tier): cast (CR 608.2n), cycled or discarded to
  pay for its own ability, it lands in the graveyard, where its flashback is
  the next price it asks (CR 702.34a).

A **face-down permanent being turned face up** (CR 702.37e) is the payment's
own card (*paying_for*, ``Game._pay_planned_cost``): its turn-up is what the
payment buys, so it is no want beside it — it was, a redundant first-tier
want that outranked the rest of the hand — and its face-up abilities join the
abilities' tier as a cast permanent's do.

**And what a graveyard ability brings back** (:func:`bringing_back`): "Return
this card from your graveyard to your hand" (Eternal Dragon, Hammer of
Bogardan, CR 113.6m) is a payment for a card that will be in the hand once it
resolves, and then wants what a held card wants — its mana cost, its hand
abilities (the cards' tier); returned to the battlefield, its activated
abilities (the abilities' tier). The card is in the graveyard while the
payment is planned, where no reading above sees it, so its upkeep return
paid {3}{W}{W} with four Plains and an Island and left seven Islands that
could not cast the Dragon it had just bought back.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from .activation_zones import HAND
from .face_down import face_up_morph_cost, hidden_card, is_face_down, morph_cost
from .faces import castable_faces
from .mana_abilities import is_mana_ability
from .mana_payment import PaymentWants, mana_cost_x_as_zero
from .models import Permanent
from .oracle import compile_card_oracle
from .targeting import usable_activated_abilities

if TYPE_CHECKING:
    from .game import Game


#: ``(card, zone)`` — the card a graveyard ability being paid for returns,
#: and where to (:func:`bringing_back`).
_BRINGING_BACK: ContextVar["tuple | None"] = ContextVar("mana_wants_bringing_back", default=None)


@contextmanager
def bringing_back(card, zone: str):
    """Plan every payment in this block as one for an ability that returns
    *card* to *zone* (``"hand"`` or ``"battlefield"``) — see the module's
    note. A context variable for ``ai_payment._PaymentContext``'s reason: the
    land plan (``ai_payment._plan_land_taps``) is reached by a caller that
    knows what the ability does, and reads the wants without being told."""
    token = _BRINGING_BACK.set((card, zone))
    try:
        yield
    finally:
        _BRINGING_BACK.reset(token)


def _wants_of_the_returned() -> "tuple[list, list]":
    """``(cards' tier, abilities' tier)`` of the card :func:`bringing_back`
    names: in a hand, its castable faces' mana costs and its hand abilities;
    on the battlefield, its activated abilities, a {T} one of a creature
    without haste left out (CR 302.6)."""
    held = _BRINGING_BACK.get()
    if held is None:
        return [], []
    card, zone = held
    if zone == "battlefield":
        from .search_filters import card_has_type

        return [], _abilities_brought(card, sick=card_has_type(card, "creature"))
    cards: list = []
    for face in castable_faces(card):
        if face.primary_type == "land":
            continue
        cost = mana_cost_x_as_zero(face.mana_cost or "")
        if cost:
            cards.append(cost)
    for ability in usable_activated_abilities(compile_card_oracle(card), zone=HAND):
        _add_ability_cost(cards, ability)
    return cards, []


def mana_wants(
    game: "Game", seat: int, *, paying_for=None, cast: bool = False,
) -> PaymentWants:
    """Every cost *seat* may still want to pay mana for, as symbol dicts in
    two tiers — see the module's note. *paying_for* is a card (or a face of
    one) the payment being planned is for, left out of the hand once — or the
    face-down permanent a turn-up pays for. *cast* says the payment is
    *paying_for*'s cast (:func:`wants_left_behind`)."""
    player = game.players[seat]
    wants: list[dict[str, int]] = list(wants_brought_by(paying_for))
    abilities: list[dict[str, int]] = []
    skipped = paying_for is None
    left_the_hand = False
    whole = (
        hidden_card(paying_for) or getattr(paying_for, "face_of", None) or paying_for
    )
    for card in player.hand:
        if not skipped and (card is paying_for or card is whole):
            skipped = left_the_hand = True
            continue
        for face in castable_faces(card):
            if face.primary_type == "land":
                continue
            cost = mana_cost_x_as_zero(face.mana_cost or "")
            if cost:
                wants.append(cost)
        for ability in usable_activated_abilities(compile_card_oracle(card), zone=HAND):
            _add_ability_cost(wants, ability)
    if paying_for is not None and hidden_card(paying_for) is None and not isinstance(
        paying_for, Permanent,
    ):
        cards, brought = wants_left_behind(
            paying_for, cast=cast, from_hand=left_the_hand,
        )
        wants.extend(cards)
        abilities.extend(brought)
    wants.extend(_permitted_cast_wants(game, seat, paying_for))
    returned_cards, returned_abilities = _wants_of_the_returned()
    wants.extend(returned_cards)
    abilities.extend(returned_abilities)
    for permanent in game.controlled_by(seat):
        if is_face_down(permanent):
            if permanent is paying_for:
                # A turn-up being paid for (CR 702.37e): its morph cost is
                # this payment, and what it brings is its face-up abilities.
                real = hidden_card(permanent.card)
                if real is not None:
                    abilities.extend(_abilities_brought(
                        real, sick=game._is_summoning_sick(permanent),
                    ))
                continue
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
    it). What a face-up card leaves behind is :func:`wants_left_behind`'s,
    which is told what the payment is. A permanent (an ability being paid
    for) brings nothing."""
    hidden = hidden_card(paying_for)
    if hidden is None:
        return ()
    turn_up = mana_cost_x_as_zero(morph_cost(hidden) or "")
    return (turn_up,) if turn_up else ()


def wants_left_behind(
    card, *, cast: bool, from_hand: bool,
) -> "tuple[tuple[dict[str, int], ...], tuple[dict[str, int], ...]]":
    """``(cards' tier, abilities' tier)`` — what *card* (the face-up card, or
    face, a payment is for) still wants paid once it has left the hand, by
    where it went. See the module's note.

    * *cast* of a **permanent** spell: its battlefield activated abilities
      that are not mana abilities, at their mana — a {T} ability of a creature
      without haste excepted (CR 302.6);
    * *from_hand*, an **instant or sorcery** printing a flashback cost: that
      cost, {X} as 0, because the card lands in the graveyard whether it is
      cast (CR 608.2n) or paid away for its own ability (cycling, CR 702.29a).
      A flashback cast is not from the hand — the card is exiled as it leaves
      the stack (CR 702.34a) — and brings nothing.
    """
    from .flashback import printed_flashback_cost
    from .search_filters import card_has_type

    cards: list[dict[str, int]] = []
    abilities: list[dict[str, int]] = []
    instant_or_sorcery = card_has_type(card, "instant") or card_has_type(card, "sorcery")
    if from_hand and instant_or_sorcery:
        flashback = printed_flashback_cost(card)
        cost = mana_cost_x_as_zero(getattr(flashback, "mana", None) or "") if flashback else None
        if cost:
            cards.append(cost)
    if cast and not instant_or_sorcery and card.primary_type != "land":
        abilities.extend(_abilities_brought(card, sick=card_has_type(card, "creature")))
    return tuple(cards), tuple(abilities)


def _abilities_brought(card, *, sick: bool) -> "list[dict[str, int]]":
    """The mana of *card*'s battlefield activated abilities that are not mana
    abilities — a {T} ability left out while *sick* and the card prints no
    haste (CR 302.6)."""
    hasty = any(str(keyword).lower() == "haste" for keyword in getattr(card, "keywords", ()) or ())
    found: list[dict[str, int]] = []
    for ability in usable_activated_abilities(compile_card_oracle(card)):
        cost = getattr(ability, "cost", None)
        if cost is not None and cost.requires_tap and sick and not hasty:
            continue
        _add_ability_cost(found, ability)
    return found


def _permitted_cast_wants(game: "Game", seat: int, paying_for) -> "list[dict[str, int]]":
    """Each card *seat* may cast from outside its hand under a permission
    (``ai_weighed_cast.permitted_casts``), at the price the permission
    charges: its required alternative cost's mana (a flashback cost), nothing
    for a waiver, else the card's mana cost; {X} as 0. One want per card —
    the first price the list names for it — and none for a land (CR 305.1).
    The card the payment is for (a flashback cast) is left out once."""
    from .ai_weighed_cast import permitted_casts

    found: list[dict[str, int]] = []
    seen: set[tuple[str, int, int]] = set()
    skipped = paying_for is None
    whole = getattr(paying_for, "face_of", None) or paying_for
    for entry in permitted_casts(game, seat):
        key = (entry.zone, entry.owner_seat, entry.index)
        if key in seen:
            continue
        seen.add(key)
        if entry.held.primary_type == "land" or entry.spell.primary_type == "land":
            continue
        if not skipped and (entry.held is whole or entry.spell is paying_for):
            skipped = True
            continue
        if entry.cost is not None:
            printed = entry.cost.mana or ""
        elif entry.waives_mana_cost:
            continue
        else:
            printed = entry.spell.mana_cost or ""
        cost = mana_cost_x_as_zero(printed)
        if cost:
            found.append(cost)
    return found


def _add_ability_cost(wants: list, ability) -> None:
    cost = getattr(ability, "cost", None)
    if cost is None or ability.instruction is None or is_mana_ability(ability.instruction):
        return
    mana = {symbol: int(amount) for symbol, amount in (cost.mana or {}).items() if int(amount or 0) > 0}
    if mana:
        wants.append(mana)


__all__ = ["bringing_back", "mana_wants", "wants_brought_by", "wants_left_behind"]

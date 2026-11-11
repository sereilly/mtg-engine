"""What a card exiled from the hand by an **imprint** is worth, and when a seat
holds a card back for one.

"Imprint — {X}, {T}: You may exile an instant or sorcery card with mana
value X from your hand. / At the beginning of your upkeep, you may copy a
card exiled with this artifact. If you do, you may cast the copy without
paying its mana cost." (Panoptic Mirror.) With nothing exiled its upkeep
ability does nothing for the rest of the game, so the activation is the
only thing the permanent its seat paid for ever does — the reading
``ai_prompts`` already takes of an imprint *offer* (Chrome Mox, Isochron
Scepter: "taken", ``ai_prompt_readers.offers_a_hand_imprint``). As an
*activation* it was rehearsed like any other, and a rehearsal reads to the
end of the turn: the card leaving the hand was all it saw, every X measured
under nothing, and the AI never imprinted (DST W1G3: 0 imprints in five
seeded games).

The imprint is priced here as what it is: the card is **kept** — it is cast
from exile, not spent — and every upkeep after this turn brings a cast of it
for no mana. The first of those casts is counted, at what the seat's own
copy-cast chooser (``ai_policy.choose_copy_cast``, the one the upkeep
trigger asks) measures a free cast of that card to be worth on this board;
the rest of the game's are a horizon no rehearsal reads. A card whose free
cast is worth nothing — a combat trick in an upkeep, a counterspell with
nothing to counter — is not imprinted.

And because the main phase's casts come before its activations
(``ai_simulator``'s doors, the web AI's the same), a card worth imprinting
is **held** from the cast chooser while an imprint that would take it can
be paid for this turn (:func:`held_for_an_imprint`): cast first, it left the
Mirror nothing to take.
"""

from __future__ import annotations

import random
import weakref

from .ai_prompt_readers import offers_a_hand_imprint
from .ai_standing import CARD_WORTH
from .linked_exile import cards_still_exiled_with

#: `free_cast_worth`'s answers for one position of one game: ``{"game": a weak
#: reference to it, "at": stamp, (seat, card name): worth}`` — the cast
#: chooser asks of every card in the hand at every pass of a main phase, and
#: each answer is a scratch copy and a rehearsed cast. Held by identity and
#: stamped by what can be counted, as ``ai_scoring._TUTOR_SCORES`` is.
_FREE_CAST_WORTHS: dict = {}


def empty_hand_imprint(game, permanent, ability) -> "dict | None":
    """The exile step's payload when *ability*'s whole effect is a hand
    imprint of *permanent*'s (``offers_a_hand_imprint``: "you may exile <a
    card> from your hand", read by another of its abilities, CR 607.2a) and
    nothing is exiled with *permanent* yet — or None."""
    instruction = getattr(ability, "instruction", None)
    if instruction is None or instruction.kind != "may":
        return None
    steps = tuple(instruction.payload.get("action") or ())
    if not offers_a_hand_imprint(steps, permanent):
        return None
    if cards_still_exiled_with(game, permanent):
        return None
    return dict(steps[0].payload)


def imprinted_card(game, seat: int, payload: dict, x_value: "int | None"):
    """The card an imprint whose exile step is *payload* takes out of
    *seat*'s hand at *x_value*: the engine's candidates
    (``handlers.hand.exile_from_hand_candidates``, "mana value X" bound to
    the X announced) in the order its default pick takes them (the lowest
    mana value, the lowest slot) — or None."""
    from .handlers.hand import exile_from_hand_candidates

    described = dict(payload.get("card_filter") or {})
    bound = described.get("mana_value")
    if isinstance(bound, dict) and str(bound.get("value")).lower() == "x":
        if x_value is None:
            return None
        described["mana_value"] = {**bound, "value": int(x_value)}
    player = game.players[seat]
    slots = exile_from_hand_candidates(game, {**payload, "card_filter": described}, player)
    if not slots:
        return None
    hand = player.hand
    return hand[min(slots, key=lambda slot: (hand[slot].cmc, slot))]


def free_cast_worth(game, seat: int, card) -> "float | None":
    """What a cast of *card* without paying its mana cost is worth to
    *seat* on this board, beside the same board with nothing cast — or None
    where the seat would not make it.

    Asked of the seat's own copy-cast chooser (``ai_policy.choose_copy_cast``)
    over a copy of *card* made in exile on a scratch copy of the game and
    offered free (``copy_casts.make_copy_in_exile``, ``offer_permission``):
    the very question the imprint's upkeep trigger will ask. The score's
    spell base and its zone's bonus are taken off (``ai_cast_score.
    zone_cast_bonus``), leaving the swing the cast's rehearsal measured. In
    a deliberation of its own (``ai_rehearsal.deliberating_apart``): the
    table is another one. Never from inside a rehearsal."""
    from . import ai_rehearsal
    from .ai_scratch_copy import public_counts

    if ai_rehearsal.rehearsing():
        return None
    stamp = (
        public_counts(game),
        tuple(sorted(permanent.permanent_id for permanent in game.all_permanents())),
    )
    held = _FREE_CAST_WORTHS.get("game")
    if held is None or held() is not game or _FREE_CAST_WORTHS.get("at") != stamp:
        _FREE_CAST_WORTHS.clear()
        _FREE_CAST_WORTHS["game"] = weakref.ref(game)
        _FREE_CAST_WORTHS["at"] = stamp
    key = (seat, card.name)
    if key not in _FREE_CAST_WORTHS:
        _FREE_CAST_WORTHS[key] = _free_cast_worth(game, seat, card)
    return _FREE_CAST_WORTHS[key]


def _free_cast_worth(game, seat: int, card) -> "float | None":
    from .ai_actions import cast_announcement
    from .ai_policy import choose_copy_cast
    from .ai_rehearsal import deliberating_apart
    from .ai_scoring import _rehearse_announcement, _weighed_through_the_fight
    from .ai_scratch_copy import scratch_copy
    from .copy_casts import make_copy_in_exile, offer_permission

    sequence = random.getstate()
    try:
        with deliberating_apart():
            table = scratch_copy(game)
            copy = make_copy_in_exile(table, seat, card)
            permission = offer_permission(table, seat, copy, "the imprint")
            action = choose_copy_cast(table, seat, copy, permission)
            if action is None:
                return None
            # The reading the chooser's builder made of that very cast, asked
            # again of the same deliberation (the builder's own two calls, so
            # the same keys and the same answers): its swing, which is what
            # the cast does, and not its score, which ranks it.
            announcement = cast_announcement(action)
            rehearsal = _weighed_through_the_fight(
                table, seat, copy, announcement,
                _rehearse_announcement(table, seat, copy, announcement, planned=action),
                planned=action,
            )
            if rehearsal is None or not rehearsal.accepted:
                return None
            return rehearsal.swing
    finally:
        random.setstate(sequence)


def imprint_worth(game, seat: int, payload: dict, rehearsal, x_value: int) -> "float | None":
    """What an empty hand imprint (*payload*, :func:`empty_hand_imprint`)
    activated at *x_value* leaves *seat* — *rehearsal* is that activation
    carried out on a copy (``ai_activation_rehearsal._rehearse_activation``)
    — or None where it is not worth activating: the engine refused it, it
    took nothing, or the card it takes is worth nothing cast for free.

    The rehearsal's lasting reading, which charges the card leaving the
    hand, with the card given back (it is kept, in exile, where the upkeep
    copies it) and the next upkeep's free cast of it added
    (:func:`free_cast_worth`)."""
    card = imprinted_card(game, seat, payload, x_value)
    if card is None or rehearsal is None or not (rehearsal.accepted and rehearsal.changed):
        return None
    worth = free_cast_worth(game, seat, card)
    if worth is None or worth <= 0.0:
        return None
    return rehearsal.lasting + CARD_WORTH + worth


def held_for_an_imprint(game, seat: int, card) -> "str | None":
    """Why *seat* holds *card* back from a cast in its own main phase, or
    None: an untapped permanent of its has an empty hand imprint
    (:func:`empty_hand_imprint`), and of the cards in the hand that imprint
    would take — each at X = its mana value, where the board can pay that
    activation's charge (``Game.activation_mana_charge``, planned by
    ``ai_payment._plan_land_taps``) — *card* is the one whose free cast is
    worth most, and something (:func:`free_cast_worth`). Cast instead, the
    card is spent once and the imprint has nothing to take; imprinted, it is
    cast every upkeep. Only that card: the imprint takes one, and every other
    is cast as it would have been."""
    if card.primary_type not in ("instant", "sorcery"):
        return None
    for permanent in game.controlled_by(seat):
        if permanent.tapped:
            continue
        for ability in game.usable_abilities_of(permanent):
            payload = empty_hand_imprint(game, permanent, ability)
            if payload is None:
                continue
            best, best_worth = None, 0.0
            for x_value in sorted({int(held.cmc or 0) for held in game.players[seat].hand}):
                taken = imprinted_card(game, seat, payload, x_value)
                if taken is None or not _payable(game, seat, permanent, ability, x_value):
                    continue
                worth = free_cast_worth(game, seat, taken)
                if worth is not None and worth > best_worth:
                    best, best_worth = taken, worth
            if best is card:
                return (
                    f"held for {permanent.card.name}'s imprint: a free cast of it"
                    f" every upkeep, the next worth {best_worth:+.2f}"
                    " (ai_imprint.held_for_an_imprint)"
                )
    return None


def _payable(game, seat: int, permanent, ability, x_value: int) -> bool:
    """Whether the board pays *ability*'s charge at *x_value* — the price
    the activation path will charge (``Game.activation_mana_charge``),
    planned as the activation chooser plans it."""
    from .ai_payment import _plan_land_taps

    if not game.enforce_mana_costs:
        return True
    charge = game.activation_mana_charge(seat, permanent, ability, x_value=x_value)
    if isinstance(charge, str):
        return False
    return _plan_land_taps(
        game, game.players[seat], dict(charge[0]), paying_for=permanent,
    ) is not None


__all__ = [
    "empty_hand_imprint",
    "free_cast_worth",
    "held_for_an_imprint",
    "imprint_worth",
    "imprinted_card",
]

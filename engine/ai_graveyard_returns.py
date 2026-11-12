"""Which card in a graveyard a return names: the one worth most back.

"Return target creature card from your graveyard to the battlefield"
(Resurrection, Zombify, Breath of Life); "…to your hand" (Raise Dead,
Regrowth, Gravedigger's trigger, Argivian Archaeologist's ability). A card
in a graveyard is a target like any other (CR 115.1c), and the AI named
none on its cast — the handler's fallback then took the **first** card the
phrase admits in pile order, so a Resurrection over a Grizzly Bears and a
Shivan Dragon returned the Bears — while a trigger's default took the first
offer in a pile, and an activation the card of greatest mana value. None of
them asked whether the card could enter the battlefield at all: an instant
with a creature type (a Kindred instant, CR 308.1) is a legal "Zombie card"
target and stays in the graveyard (CR 400.4a), so a cast aimed at one did
nothing — and with the creature beside it never returned.

One ranking for every road (:func:`graveyard_return_order`): for the
battlefield, the cards that can be put there first
(``permanent_cards.is_permanent_card``, CR 110.4a — the "can't" of an
effect is the engine's to apply), then by what the card is worth as a
permanent (``ai_prompt_picks.battlefield_worth``); for a hand, by what it is
worth to hold (``held_worth``). Asked by the cast (:func:`cast_graveyard_return`),
the trigger default (``choices/triggers._default_trigger_target``), the
activation chooser (``ai_abilities``) and a several-target return
(``ai_slot_targets._choose_several_targets``). An exile that denies a graveyard
card is ``ai_targets._graveyard_denial_target``'s, and a card put on a
library is not ranked here.
"""

from __future__ import annotations

from .ai_weighed_cast import _effect_steps

#: Where each graveyard-target return step puts its card.
RETURN_DESTINATIONS = {
    "reanimate_creature": "battlefield",
    "reanimate_creature_to_battlefield": "battlefield",
    "reanimate_aura_onto_source": "battlefield",
    "return_creature_from_graveyard_to_hand": "hand",
}


def graveyard_return_destination(instructions) -> "str | None":
    """``"battlefield"`` or ``"hand"`` — where the first graveyard-target
    return among *instructions*' steps puts its card — or None."""
    for instruction in instructions or ():
        if instruction is None:
            continue
        for step in _effect_steps(instruction):
            if step.kind in RETURN_DESTINATIONS:
                return RETURN_DESTINATIONS[step.kind]
    return None


def _option_card(game, option: dict):
    pile = game.players[option.get("seat")].graveyard
    slot = option.get("index", option.get("graveyard_index"))
    return pile[slot] if isinstance(slot, int) and 0 <= slot < len(pile) else None


def can_be_returned_to(card, destination: str) -> bool:
    """Whether *card* could arrive where the return puts it: a hand takes any
    card, the battlefield a permanent card (CR 110.4a)."""
    from .permanent_cards import is_permanent_card

    return destination != "battlefield" or is_permanent_card(card)


def graveyard_return_order(game, seat: int, options, destination: str) -> list:
    """*options* — the engine's graveyard entries (``seat`` with ``index`` or
    ``graveyard_index``) — best first for *seat*'s return to *destination*:
    a card that can arrive there before one that cannot, then the dearest
    (``battlefield_worth`` for the battlefield, ``held_worth`` for a hand),
    the engine's order between equals."""
    from .ai_prompt_picks import battlefield_worth, held_worth

    def key(option) -> tuple:
        card = _option_card(game, option)
        if card is None:
            return (True, True, 0.0)
        worth = (
            battlefield_worth(card) if destination == "battlefield"
            else held_worth(game, seat, card)
        )
        return (False, not can_be_returned_to(card, destination), -worth)

    return sorted(options, key=key)


def best_graveyard_return(game, seat: int, options, destination: str) -> "dict | None":
    """The first of :func:`graveyard_return_order` — or None when no option's
    card can arrive at *destination* (the return would do nothing)."""
    ranked = graveyard_return_order(game, seat, options, destination)
    if not ranked:
        return None
    card = _option_card(game, ranked[0])
    if card is None or not can_be_returned_to(card, destination):
        return None
    return ranked[0]


def cast_graveyard_return(game, player_index: int, card) -> "tuple[int, int] | None":
    """``(pile's seat, slot)`` — the card a spell announcing **one card in a
    graveyard** returns (:func:`best_graveyard_return` over the picker's own
    list for the announcement being built) — or None for any other spell, and
    for one none of whose legal cards can arrive (its rehearsal reads the
    cast as changing nothing)."""
    from .ai_actions import (_OFFERS_ANNOUNCED, _announced_mode, _announced_steps,
                             _cast_spec, _cast_zone)
    from .ai_prompt_readers import exiles_a_graveyard_target
    from .cost_pickers import spec_is_a_cost
    from .oracle import compile_card_oracle
    from .targeting import GRAVEYARD_TARGET_KIND, spec_roles

    program = compile_card_oracle(card)
    spec = _cast_spec(card, program)
    steps = _announced_steps(card, program)
    if (
        not isinstance(spec, dict)
        or spec.get("kind") != GRAVEYARD_TARGET_KIND
        or spec_roles(spec) or spec_is_a_cost(spec)
        or spec.get("max_targets") or spec.get("x_targets")
        or exiles_a_graveyard_target(steps)
    ):
        return None
    destination = graveyard_return_destination(steps)
    if destination is None:
        return None
    legal = [
        entry for entry in game.cast_target_spec(
            player_index, card, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
            mode_index=_announced_mode(card), from_zone=_cast_zone(card),
        ).get("valid_targets") or []
        if entry.get("kind") == "graveyard"
    ]
    best = best_graveyard_return(game, player_index, legal, destination)
    if best is None:
        return None
    return int(best["seat"]), int(best["index"])


def ranked_graveyard_slots(game, seat: int, by_seat: dict, instructions) -> dict:
    """*by_seat* — ``{pile's seat: [slots]}`` a several-card graveyard
    announcement chooses among — with each pile's slots best first for the
    return *instructions* make (:func:`graveyard_return_order`), so the first
    N taken are the N worth most back; unchanged for any other effect."""
    destination = graveyard_return_destination(instructions)
    if destination is None:
        return by_seat
    return {
        pile: [
            option["index"] for option in graveyard_return_order(
                game, seat, [{"seat": pile, "index": slot} for slot in slots], destination,
            )
        ]
        for pile, slots in by_seat.items()
    }


__all__ = [
    "RETURN_DESTINATIONS",
    "best_graveyard_return",
    "can_be_returned_to",
    "cast_graveyard_return",
    "graveyard_return_destination",
    "graveyard_return_order",
    "ranked_graveyard_slots",
]

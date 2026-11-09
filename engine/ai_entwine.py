"""Whether an AI seat entwines a spell (CR 702.42a), and the cast it makes if
it does.

Entwine is not a larger version of one mode, so it is not weighed where the
other optional costs are (``ai_casts._times_worth_taking`` declines
``OFFER_ENTWINES``): paying it **is** choosing every mode, and every mode has
its own targets (CR 601.2c) on the side its own effect wants. So it is weighed
one level out, after ``ai_casts._cast_candidate_in_each_mode`` has built each
mode as a whole candidate of its own — the targets it would name, a payable
cost, a rehearsal that says it is worth casting — exactly as
``ai_casts._every_mode_worth_casting`` combines the modes of a "choose one or
more" spell. The difference is the price: those modes share one cost, an
entwined spell pays its entwine on top, so the cast is planned again with that
mana (or that sacrifice) included and **rehearsed as the combined cast** —
what the board looks like after every mode has resolved in printed order is
the score, and the seat entwines only when that beats the best single mode.

A mode whose targets do not fit a mode's announcement (one seat and one
battlefield slot: several targets, a division or a cross-board list do not
travel in it) leaves the seat casting its best single mode, never an entwined
cast the engine would refuse.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .entwine import entwine_cost
from .oracle import compile_card_oracle
from .targeting import derive_cast_spec

if TYPE_CHECKING:
    from .ai_actions import CastAction
    from .game import Game
    from .models import CardDefinition


#: A non-mana entwine ("Entwine—Sacrifice three lands.") is paid only by a
#: seat that still controls this many lands afterwards — the buyback rule
#: (``ai_casts.BUYBACK_PERMANENTS_KEPT``) for the same reason: enough lands to
#: cast everything a limited deck holds.
ENTWINE_LANDS_KEPT = 6


def _entwine_offer(card: "CardDefinition"):
    """The card's entwine as a ``CastOffer`` (``ai_valuation.cast_offers``),
    or None."""
    from .ai_valuation import cast_offers

    key = entwine_cost(card.oracle_text or "")
    if key is None:
        return None
    return next((offer for offer in cast_offers(card) if offer.key == key), None)


def _mode_entry(candidate: "CastAction") -> "dict | None":
    """One ``mode_choices`` entry for *candidate* (a single-mode cast), or None
    when its targets do not fit a mode's announcement."""
    slot = candidate.target_permanent_index
    if slot is not None and not isinstance(slot, int):
        return None
    if candidate.divided_targets or candidate.target_role_refs:
        return None
    if candidate.target_permanent_ids and slot is None:
        return None
    return {
        "index": candidate.mode_index,
        "target_player_index": candidate.target_player_index,
        "target_permanent_index": slot,
        "target_stack_index": candidate.target_stack_index,
    }


def _price_is_spare(game: "Game", player_index: int, card, offer) -> bool:
    """Whether a non-mana entwine price leaves the seat its reserve."""
    price = offer.price
    if price is None:
        return True
    if (
        price.pay_life or price.pay_life_x or price.discard_cards
        or price.discard_filters or price.discard_whole_hand
        or price.return_filter is not None
        or price.sacrifice_all_filter is not None
        or price.exile_filter is not None
    ):
        # Every entwine printed in this pool is mana or a sacrifice of lands;
        # a price of any other resource is declined rather than guessed at.
        return False
    if price.sacrifice_filter is None:
        return True
    available = game._additional_cost_candidates(
        player_index, price, giving_up="sacrifice"
    )
    return len(available) - max(1, price.sacrifice_count) >= ENTWINE_LANDS_KEPT


def entwined_cast(
    game: "Game", player_index: int, card: "CardDefinition",
    built: "list[CastAction]", best: "CastAction",
    *, from_zone: str = "hand", extra_generic: int = 0,
) -> "CastAction | None":
    """The entwined cast of *card*, scored by its rehearsal — or None when the
    seat would not, or could not, make one.

    *built* is every single-mode candidate ``_cast_candidate_in_each_mode``
    found (each a mode with a legal announcement, a payable cost and a
    rehearsal worth proposing) and *best* the one it would cast. None unless
    every mode has a legal announcement (CR 700.2a) and every mode that
    *targets* is in *built*: CR 702.42a chooses all of them, and a targeting
    mode the seat would not cast on its own (nothing on the side its effect
    wants) is a mode the entwined cast would have to aim anyway. A mode that
    names no target is announced bare, and the rehearsal says what it adds.
    """
    from .ai_actions import cast_announcement
    from .ai_cast_gates import _printed_costs_are_payable
    from .ai_payment import _cost_for, _plan_land_taps
    from .ai_scoring import (_rehearse_announcement, _score_cast,
                             _weighed_through_the_fight, _worth_proposing)

    offer = _entwine_offer(card)
    if offer is None or best is None:
        return None
    program = compile_card_oracle(card)
    if not program.modes:
        return None
    by_mode = {candidate.mode_index: candidate for candidate in built}
    announceable = set(game.announceable_modes(player_index, card))
    entries = []
    for index in range(len(program.modes)):
        if index not in announceable:
            # CR 700.2a: a mode with no legal announcement cannot be chosen,
            # and an entwined cast chooses every one.
            return None
        candidate = by_mode.get(index)
        if candidate is None:
            # A mode the seat would not cast **alone** may still be worth
            # casting after its siblings: "Create an X/X black Demon …, where
            # X is the number of cards in your hand" is a 0/0 from an empty
            # hand and a 5/5 after "You draw five cards" (Promise of Power's
            # 2004-12-01 ruling). A mode that names no target needs no
            # candidate to be announced; one that does is left to the single
            # modes, whose targets this seat has weighed.
            if derive_cast_spec(
                card, program, from_zone=from_zone, mode_index=index,
            ) is not None:
                return None
            entries.append({"index": index})
            continue
        if (
            candidate.optional_cost_payments
            or candidate.alternative_cost
            or candidate.x_value != best.x_value
        ):
            return None
        entry = _mode_entry(candidate)
        if entry is None:
            return None
        entries.append(entry)
    taken = {offer.key: 1}
    hand_index = best.hand_index
    if not _printed_costs_are_payable(
        game, player_index, card, hand_index, from_zone, best.x_value, taken=taken,
    ):
        return None
    if not _price_is_spare(game, player_index, card, offer):
        return None
    player = game.players[player_index]
    tap_indices: tuple = ()
    tap_colors: tuple = ()
    if game.enforce_mana_costs:
        required = dict(_cost_for(game, player, card, best.x_value, extra_generic=extra_generic))
        if offer.mana is not None:
            for symbol, amount in offer.mana.cost_at(None).items():
                required[symbol] = required.get(symbol, 0) + amount
        plan = _plan_land_taps(game, player, required)
        if plan is None:
            return None
        tap_indices, tap_colors = plan
    action = replace(
        best,
        mode_index=None,
        mode_choices=entries,
        optional_cost_payments=taken,
        target_permanent_index=None,
        target_permanent_ids=None,
        target_stack_index=None,
        land_tap_indices=tap_indices,
        land_tap_colors=tap_colors,
        score=0.0,
    )
    announcement = cast_announcement(action)
    rehearsal = _rehearse_announcement(
        game, player_index, card, announcement, planned=action,
    )
    rehearsal = _weighed_through_the_fight(
        game, player_index, card, announcement, rehearsal, planned=action,
    )
    if not _worth_proposing(rehearsal):
        return None
    score = _score_cast(
        game, player_index, card, best.target_player_index, best.x_value, rehearsal,
    )
    return replace(action, score=score)


__all__ = ["ENTWINE_LANDS_KEPT", "entwined_cast"]
